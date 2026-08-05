"""Re-enable kill switches.

Usage:
  python enable.py scanner
  python enable.py all
  python enable.py status
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
    parser = argparse.ArgumentParser(description="OzMoEg enable helper")
    parser.add_argument("action", nargs="?", choices=VALID_SWITCHES + ["all", "status"], default="status")
    args = parser.parse_args()

    cfg = load()

    if args.action == "status":
        show_status(cfg)
        return

    if args.action == "all":
        for k in VALID_SWITCHES:
            set_switch(cfg, k, True)
        print("All kill switches ON.")
    else:
        set_switch(cfg, args.action, True)
        print(f"Kill switch '{args.action}' set to ON.")

    save(cfg)
    show_status(cfg)


if __name__ == "__main__":
    main()
