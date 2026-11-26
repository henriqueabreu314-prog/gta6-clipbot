"""Download a clip, transcribe it and render a 1080x1920 Short with captions."""
import json
import re
import subprocess
from pathlib import Path

from .common import log

W, H = 1080, 1920
MAX_BYTES = 48 * 1024 * 1024  # Telegram accepts bot uploads up to 50 MB


def download(url, dest):
    from yt_dlp import YoutubeDL

    opts = {
        "outtmpl": str(dest), "quiet": True, "no_warnings": True,
        # Highest resolution available (Kick/Twitch clips come as HLS with several qualities)
        "format": "bv*+ba/b", "format_sort": ["res", "fps", "br"], "merge_output_format": "mp4",
    }
    with YoutubeDL(opts) as ydl:
        ydl.download([url])
    return dest


def duration_of(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def load_audio(path, sr=16000):
    """Decode audio with ffmpeg (avoids PyAV version problems inside faster-whisper)."""
    import numpy as np

    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-vn",
         "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


_model = None


def transcribe(path, model_size, language):
    global _model
    from faster_whisper import WhisperModel

    if _model is None:
        log(f"A carregar Whisper '{model_size}'...")
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = _model.transcribe(
        load_audio(path), language=language or None, word_timestamps=True, vad_filter=True
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            t = w.word.strip()
            if t:
                words.append((w.start, w.end, t))
    return words


def group_words(words, max_words=3, max_gap=0.6):
    groups, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or w[0] - cur[-1][1] > max_gap):
            groups.append(cur)
            cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    return [(g[0][0], g[-1][1], " ".join(x[2] for x in g)) for g in groups]


def _ts(t):
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(text):
    text = re.sub(r"[{}\\]", "", text)
    return " ".join(text.split())


_ALIGN = {"top-left": 7, "top-right": 9, "bottom-left": 1, "bottom-right": 3}


def build_ass(words, hook, credit, duration, path, watermark=None):
    # Colours are &HAABBGGRR
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,DejaVu Sans,74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,7,0,8,70,70,300,1
Style: Sub,DejaVu Sans,86,&H0000FFFF,&H0000FFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,7,0,8,60,60,1330,1
Style: Credit,DejaVu Sans,46,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,4,0,2,60,60,260,1
Style: Mark,DejaVu Sans,44,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,0,9,50,50,110,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [
        f"Dialogue: 1,{_ts(0)},{_ts(duration)},Hook,,0,0,0,,{_clean(hook).upper()}",
        f"Dialogue: 1,{_ts(0)},{_ts(duration)},Credit,,0,0,0,,{_clean(credit)}",
    ]
    wm = watermark or {}
    if wm.get("text"):
        alpha = f"{int((1 - float(wm.get('opacity', 0.6))) * 255):02X}"
        an = _ALIGN.get(wm.get("position", "top-right"), 9)
        lines.append(
            f"Dialogue: 2,{_ts(0)},{_ts(duration)},Mark,,0,0,0,,{{\\an{an}\\alpha&H{alpha}&}}{_clean(wm['text'])}"
        )
    for start, end, text in group_words(words):
        lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end + 0.05)},Sub,,0,0,0,,{_clean(text).upper()}")
    Path(path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


def _logo_xy(position, margin=50):
    x = f"{margin}" if "left" in position else f"W-w-{margin}"
    y = f"{margin + 60}" if "top" in position else f"H-h-{margin + 60}"
    return x, y


def ffmpeg_render(src, ass_name, out, workdir, duration, scale=1.0, logo=None, wm=None):
    # Bitrate chosen so a 60 s clip stays under Telegram's 20 MB download limit.
    # Quality-based encoding (CRF) with a bitrate ceiling so the file stays under MAX_BYTES.
    vbit = int(min(12000, (MAX_BYTES * 8 / 1000 / max(duration, 1)) - 192) * 0.92 * scale)
    graph = (
        f"[0:v]split=2[a][b];"
        f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,eq=brightness=-0.08[bg];"
        f"[b]scale={W}:-2[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,subtitles={ass_name}[base];"
    )
    inputs = ["-i", str(src)]
    if logo:
        wm = wm or {}
        x, y = _logo_xy(wm.get("position", "top-right"))
        op = float(wm.get("opacity", 0.6))
        inputs += ["-i", str(logo)]
        graph += (
            f"[1:v]scale=180:-1,format=rgba,colorchannelmixer=aa={op}[logo];"
            f"[base][logo]overlay={x}:{y},format=yuv420p[v]"
        )
    else:
        graph += "[base]format=yuv420p[v]"
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", *inputs,
        "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high",
        "-maxrate", f"{vbit}k", "-bufsize", f"{vbit * 2}k", "-fpsmax", "60",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
    ]
    subprocess.run(cmd, cwd=workdir, check=True)


def render_clip(clip, cfg, workdir):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    raw = workdir / "raw.mp4"
    out = workdir / "short.mp4"
    for p in (raw, out):
        p.unlink(missing_ok=True)

    # Prefer the clip page (yt-dlp picks the best quality); fall back to the direct stream URL.
    sources = [u for u in dict.fromkeys([clip.get("url"), clip.get("download_url")]) if u]
    for i, src in enumerate(sources):
        try:
            log(f"A descarregar {src}")
            raw.unlink(missing_ok=True)
            download(src, raw)
            break
        except Exception as e:
            if i == len(sources) - 1:
                raise
            log(f"Falhou ({e}); a tentar outra fonte")
    dur = duration_of(raw)

    log("A gerar legendas...")
    words = transcribe(raw, cfg["whisper"]["model"], cfg["whisper"].get("language"))

    if clip.get("_ai_title"):
        from .titles import make_hook as ai_hook
        clip["_hook"] = ai_hook(clip, words, cfg) or clip["_hook"]
    hook = clip["_hook"]
    credit = f"🎮 {clip['channel_url']}"
    wm = cfg.get("watermark") or {}
    logo = None
    if wm.get("logo"):
        logo = (Path(__file__).resolve().parent.parent / wm["logo"])
        if not logo.exists():
            log(f"AVISO: logo '{wm['logo']}' não encontrado; a ignorar")
            logo = None
    # With a logo, the logo is the watermark; otherwise use the text.
    build_ass(words, hook, credit, dur, workdir / "subs.ass", None if logo else wm)

    log("A montar o vídeo vertical...")
    scale = 1.0
    for _ in range(3):
        ffmpeg_render(raw.name, "subs.ass", out.name, workdir, dur, scale, logo, wm)
        if out.stat().st_size <= MAX_BYTES:
            break
        scale *= 0.8
    return out
