"""Commit data/state.json safely when "prepare" and "tick" run at the same time.

Each job started from some commit (the base). Before pushing, we take the newest
state on GitHub and do a 3-way merge per clip: whatever one side changed wins;
if both changed the same clip, the more advanced status wins.
Usage (in a workflow): python -m clipbot.savestate "commit message"
"""
import json
import subprocess
import sys

PATH = "data/state.json"
RANK = {"failed": 0, "pending": 1, "rerender": 2, "expired": 2, "approved": 3, "rejected": 4, "published": 5}


def git(*args, check=True):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def show(ref):
    r = git("show", f"{ref}:{PATH}", check=False)
    return json.loads(r.stdout) if r.returncode == 0 else {"clips": {}}


def pick(base, ours, theirs):
    if ours == base:
        return theirs
    if theirs == base or theirs == ours:
        return ours
    return None  # both changed differently


def merge(base, ours, theirs):
    out = dict(theirs)
    for key in set(ours) | set(theirs):
        if key in ("clips", "events", "tg_offset"):
            continue
        v = pick(base.get(key), ours.get(key), theirs.get(key))
        out[key] = v if v is not None else max(ours.get(key) or "", theirs.get(key) or "", key=str)
    out["tg_offset"] = max(ours.get("tg_offset", 0), theirs.get("tg_offset", 0))
    events = list(theirs.get("events", []))
    events += [e for e in ours.get("events", []) if e not in events]
    out["events"] = sorted(events)[-40:]
    bc, oc, tc = base.get("clips", {}), ours.get("clips", {}), theirs.get("clips", {})
    clips = {}
    for k in set(oc) | set(tc):
        b, o, t = bc.get(k), oc.get(k), tc.get(k)
        v = pick(b, o, t)
        if v is None:  # both changed: keep the more advanced one
            v = o if RANK.get(o["status"], 0) >= RANK.get(t["status"], 0) else t
        if v is not None:
            clips[k] = v
    out["clips"] = clips
    return out


def main():
    msg = sys.argv[1] if len(sys.argv) > 1 else "estado"
    git("config", "user.name", "clipbot")
    git("config", "user.email", "clipbot@users.noreply.github.com")
    base = show("HEAD")
    with open(PATH, encoding="utf-8") as f:
        ours = json.load(f)
    if ours == base:
        print("estado sem alterações")
        return
    for attempt in range(6):
        git("fetch", "-q", "origin", "main")
        theirs = show("origin/main")
        merged = merge(base, ours, theirs)
        git("reset", "-q", "--hard", "origin/main")
        with open(PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        if git("diff", "--quiet", "--", PATH, check=False).returncode == 0:
            print("nada a guardar depois de juntar")
            return
        git("add", PATH)
        git("commit", "-q", "-m", msg)
        if git("push", "-q", "origin", "HEAD:main", check=False).returncode == 0:
            print(f"estado guardado (tentativa {attempt + 1})")
            return
        base, ours = theirs, merged
    sys.exit("não consegui guardar o estado depois de 6 tentativas")


if __name__ == "__main__":
    main()
