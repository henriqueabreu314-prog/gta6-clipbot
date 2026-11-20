import argparse

from .common import load_config, load_state


def main():
    p = argparse.ArgumentParser(prog="clipbot")
    p.add_argument("command", choices=["prepare", "tick"])
    p.add_argument("--dry-run", action="store_true", help="prepare: só gera os vídeos em output/, sem Telegram")
    a = p.parse_args()
    cfg, st = load_config(), load_state()
    if a.command == "prepare":
        from . import prepare
        prepare.run(cfg, st, dry_run=a.dry_run)
    else:
        from . import tick
        tick.run(cfg, st)


if __name__ == "__main__":
    main()
