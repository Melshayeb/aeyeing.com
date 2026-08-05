#!/usr/bin/env python3
"""
OzMoEg Money Maker — Stateful notification store.
Persists hashes of recent alerts, market statuses, and scan summaries so we
only notify when something actually changes.
"""
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_FILE = Path.home() / ".hermes/skills/ozmoeg-money-maker/.notification_state.json"

DEFAULT_QUIET_WINDOWS = {
    "no_gainers": 3600,       # 1 hour between "no gainers" warnings
    "no_candidates": 3600,    # 1 hour between "no candidates" summaries
    "scan_summary": 900,      # 15 min minimum between identical summaries
    "market_status": 10800,   # 3 hour quiet window for the SAME market status
    "new_alert": 0,           # new alerts always alert (per-ticker dedup in notifier)
}


class NotificationState:
    """Persistent deduplication/state store for OzMoEg notifications."""

    def __init__(self, quiet_windows: Optional[Dict[str, int]] = None):
        self.quiet_windows = {**DEFAULT_QUIET_WINDOWS, **(quiet_windows or {})}
        self._state = self._load()

    def _load(self) -> Dict[str, Any]:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning("Failed to load notification state: %s", e)
        return {}

    def _save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    def _hash(self, obj) -> str:
        """Stable hash for deduplication."""
        return hashlib.md5(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

    def should_notify_market_status(self, market: str, new_status: str) -> bool:
        """Notify on market status transitions immediately. Re-alert the same status only
        after the configured quiet window has passed."""
        key = f"market_status:{market}"
        now = time.time()
        record = self._state.get(key, {})
        last_status = record.get("status")
        last_ts = record.get("ts", 0)
        quiet = self.quiet_windows.get("market_status", 10800)

        if last_status == new_status:
            if now - last_ts < quiet:
                return False
            # Same status but quiet window passed: allow re-alert and refresh timestamp
            record["ts"] = now
            self._state[key] = record
            self._save()
            return True

        # Transition to a new status: alert immediately
        self._state[key] = {"status": new_status, "ts": now}
        self._save()
        return True

    def should_notify_scan_summary(self, market: str, alerts: List[str], candidates: int,
                                   market_status: str) -> bool:
        """Notify on scan summary only if content changed or quiet window passed."""
        key = f"scan_summary:{market}"
        now = time.time()
        payload = {
            "alerts": sorted(alerts),
            "candidates": candidates,
            "market_status": market_status,
        }
        digest = self._hash(payload)
        last = self._state.get(key, {})
        if last.get("digest") == digest:
            # Same content — respect quiet window
            if now - last.get("ts", 0) < self.quiet_windows.get("scan_summary", 900):
                return False
        self._state[key] = {"digest": digest, "ts": now}
        self._save()
        return True

    def should_notify_no_gainers(self, market: str) -> bool:
        """Throttle repeated 'no gainers' warnings."""
        key = f"no_gainers:{market}"
        now = time.time()
        last = self._state.get(key, 0)
        if now - last < self.quiet_windows.get("no_gainers", 3600):
            return False
        self._state[key] = now
        self._save()
        return True

    def should_notify_no_candidates(self, market: str) -> bool:
        """Throttle repeated 'no candidates' summaries."""
        key = f"no_candidates:{market}"
        now = time.time()
        last = self._state.get(key, 0)
        if now - last < self.quiet_windows.get("no_candidates", 3600):
            return False
        self._state[key] = now
        self._save()
        return True

    def get_last_alert_tickers(self, market: str) -> List[str]:
        """Return list of tickers that were recently alerted."""
        return self._state.get(f"last_alerts:{market}", [])

    def record_alert(self, ticker: str, result: dict) -> bool:
        """Record that an alert was sent for a ticker.

        Returns True if this is a new alert (should notify), False if it's a duplicate.
        """
        market = result.get('market', 'unknown')
        key = f"last_alerts:{market}"
        last_tickers = self._state.get(key, [])

        # Create a hash of the result (just using ticker for now to avoid storing large results)
        result_hash = hashlib.md5(f"{ticker}:{result.get('entry')}:{result.get('stop')}:{result.get('targets')}".encode()).hexdigest()

        # Check if this exact alert was already recorded
        if result_hash in last_tickers:
            return False

        # Add the result hash to the list
        last_tickers.append(result_hash)
        self._state[key] = last_tickers
        self._save()
        return True
