#!/usr/bin/env python3
"""Quick smoke test for OzMoEg notification deduplication."""
import json
import sys
from pathlib import Path

skill_dir = Path.home() / ".hermes/skills/ozmoeg-money-maker"
sys.path.insert(0, str(skill_dir))

from state_store import NotificationState

store = NotificationState()

# Reset state for a clean test run
state_file = skill_dir / ".notification_state.json"
if state_file.exists():
    state_file.unlink()
    store = NotificationState()

print("=== Milestone / change-based dedup smoke test ===")

# 1. Market status transitions
print("Market OPEN first time:", store.should_notify_market_status("us", "OPEN"))   # True
print("Market OPEN again:", store.should_notify_market_status("us", "OPEN"))         # False
print("Market CLOSED:", store.should_notify_market_status("us", "CLOSED"))           # True

# 2. Scan summary dedup
print("Summary A first:", store.should_notify_scan_summary("us", ["AAPL", "TSLA"], 5, "OPEN"))  # True
print("Summary A repeat:", store.should_notify_scan_summary("us", ["AAPL", "TSLA"], 5, "OPEN"))   # False (within quiet window)
print("Summary B changed:", store.should_notify_scan_summary("us", ["AAPL", "NVDA"], 5, "OPEN"))  # True

# 3. No-gainers / no-candidates throttling
print("No gainers first:", store.should_notify_no_gainers("us"))    # True
print("No gainers repeat:", store.should_notify_no_gainers("us"))  # False (within 1h window)
print("No candidates first:", store.should_notify_no_candidates("us"))  # True
print("No candidates repeat:", store.should_notify_no_candidates("us"))  # False

print("\nFinal state file:", state_file)
print(json.dumps(store._state, indent=2))
print("\nState store logic OK")
