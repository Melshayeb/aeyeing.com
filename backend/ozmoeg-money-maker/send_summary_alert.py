#!/usr/bin/env python3
"""One-off summary Telegram alert for current scan results.

This helper is kept for manual use. It respects the same deduplication rules
as the main scanner:
  - Only sends if there is at least one ALERT status result.
  - Skips if the same alert ticker set was already notified recently.
"""
import json
import sys
from pathlib import Path

# Ensure skill imports work
skill_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(skill_dir))

from notifier import Notifier
from state_store import NotificationState
from kill_switch import load_config, is_enabled

# Load config
config = load_config()

json_path = Path.home() / "Desktop" / "aeyeing.com" / "ozmoeg-latest.json"
with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

results = data.get("scan_results", [])
alert_results = [r for r in results if r.get("status") == "ALERT"]
alert_tickers = [r.get("ticker", "") for r in alert_results]
candidates = len(results)
alerts_count = len(alert_results)
market = data.get("market", "us").lower()
market_status = data.get("market_status", "UNKNOWN")

if alerts_count == 0:
    print("No active alerts — summary not sent (no spam).")
    sys.exit(0)

state = NotificationState()
if not state.should_notify_scan_summary(market, alert_tickers, candidates, market_status):
    print("Recent identical summary already sent — skipping.")
    sys.exit(0)

notifier = Notifier(config)
if is_enabled(config, "telegram_alerts"):
    notifier.notify_scan_summary(market, alerts_count, candidates, alert_tickers, market_status)
    print("Summary sent.")
else:
    print("Telegram alerts disabled in config.")
