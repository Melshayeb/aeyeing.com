"""Kill switch helper.

Usage:
  python disable.py scanner          # disable just the scanner
  python disable.py all              # disable everything (master switch)
  python disable.py --status           # show current kill switch state

After disabling a switch, the skill's main.py will skip that component on the
next run. No files or credentials are deleted.
"""
import argparse
import sys
from pathlib import Path

import yaml

SKILL_DIR = Path.home() / ".hermes/skills/ozmoeg-money-maker"
CONFIG_PATH = SKILL_DIR / "config.yaml"

VALID_SWITCHES = [
    "master", "scanner", "news", "strategy",
    "telegram_alerts", "email_alerts", "website_updates", "okx_sentiment",
]


def load():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save(cfg):
    SKILL_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, sort_keys=False)


def set_switch(cfg, key: str, value: bool):
    cfg.setdefault("kill_switches", {})
    if key not in VALID_SWITCHES:
        print(f"Unknown switch: {key}. Valid: {VALID_SWITCHES}")
        sys.exit(1)
    cfg["kill_switches"][key] = value


def show_status(cfg):
    ks = cfg.get("kill_switches", {})
    print("Kill switches:")
    for k in VALID_SWITCHES:
        state = ks.get(k, True)
        print(f"  {k:20} {'ON' if state else 'OFF'}")


def main():
    parser = argparse.ArgumentParser(description="OzMoEg kill switch helper")
    parser.add_argument("action", nargs="?", choices=VALID_SWITCHES + ["all", "status"], default="status")
    args = parser.parse_args()

    cfg = load()

    if args.action == "status":
        show_status(cfg)
        return

    if args.action == "all":
        set_switch(cfg, "master", False)
        print("Master kill switch OFF. Entire skill is now disabled.")
    else:
        set_switch(cfg, args.action, False)
        print(f"Kill switch '{args.action}' set to OFF.")

    save(cfg)
    show_status(cfg)


if __name__ == "__main__":
    main()
