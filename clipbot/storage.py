"""Full-quality videos are kept as assets of a GitHub release called "clips".

Telegram bots can only download files up to 20 MB, which forced low bitrates.
So the bot stores the high-quality file in the repository's release and the
publish step downloads it from there. Assets are deleted after publishing.
Uses the GitHub CLI (`gh`), preinstalled on GitHub Actions runners.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from .common import log

TAG = "clips"


def _gh(*args, check=True):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def _ensure_release():
    if _gh("release", "view", TAG, check=False).returncode != 0:
        _gh("release", "create", TAG, "--title", "Fila de clips (ficheiros temporários do bot)",
            "--notes", "Vídeos em alta qualidade à espera de publicação. Apagados depois de publicados.",
            "--prerelease")


def save(path, key):
    """Upload the video; returns the asset name, or None if storage is unavailable."""
    name = f"{key}.mp4"
    try:
        _ensure_release()
        with tempfile.TemporaryDirectory() as d:
            named = Path(d) / name  # the asset is named after the file
            shutil.copy(path, named)
            _gh("release", "upload", TAG, str(named), "--clobber")
        return name
    except Exception as e:
        detail = getattr(e, "stderr", "") or ""
        log(f"AVISO: não consegui guardar o vídeo em alta qualidade ({e} {detail.strip()})")
        return None


def load(name, dest):
    dest.unlink(missing_ok=True)
    _gh("release", "download", TAG, "--pattern", name, "--output", str(dest), "--clobber")
    return dest


def delete(name):
    r = _gh("release", "delete-asset", TAG, name, "--yes", check=False)
    if r.returncode != 0:
        log(f"AVISO: não consegui apagar {name}: {r.stderr.strip()}")
