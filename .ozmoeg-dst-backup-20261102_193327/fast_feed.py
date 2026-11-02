#!/usr/bin/env python3
"""OzMoEg fast quote feed.

Reads the last full scan snapshot, fetches fresh quotes for the tickers that
the scanner is currently tracking, and writes a small ozmoeg-fast.json.
The website polls this file every 15 s for near-real-time price/volume updates
while the full scanner continues to run every minute for discovery and plans.
"""
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

import pytz

# Allow importing project modules
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from kill_switch import load_config
from webull_client import WebullClient

logger = logging.getLogger(__name__)


def _load_last_snapshot(market: str = 'us') -> Dict[str, Any]:
    suffix = '-au' if market == 'au' else ''
    paths = [
        SCRIPT_DIR.parent.parent / f'ozmoeg-latest{suffix}.json',
        SCRIPT_DIR / f'ozmoeg-latest{suffix}.json',
    ]
    for p in paths:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding='utf-8'))
            except Exception as e:
                logger.warning("Failed to read %s: %s", p, e)
    return {}


def _write_fast_feed(data: Dict[str, Any], market: str = 'us') -> None:
    suffix = '-au' if market == 'au' else ''
    paths = [
        SCRIPT_DIR.parent.parent / f'ozmoeg-fast{suffix}.json',
        SCRIPT_DIR / f'ozmoeg-fast{suffix}.json',
    ]
    for p in paths:
        try:
            p.write_text(json.dumps(data, indent=2), encoding='utf-8')
        except Exception as e:
            logger.warning("Failed to write %s: %s", p, e)


def _quote_fields(quote: Dict[str, Any]) -> Dict[str, Any]:
    price = float(quote.get('pprice') or quote.get('price') or quote.get('close') or 0)
    close = float(quote.get('close') or 0)
    change_pct = 0.0
    if price and close and close != price:
        change_pct = (price - close) / close * 100
    elif 'changeRatio' in quote:
        cr = float(quote['changeRatio'])
        change_pct = (cr - 1) * 100 if cr > 1 else cr * 100
    return {
        'price': price,
        'change_pct': change_pct,
        'volume': int(quote.get('volume', 0) or 0),
        'market_cap': float(quote.get('marketValue', 0) or 0),
        'name': (quote.get('name') or quote.get('symbol') or '').strip(),
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


def _is_active_market_window(market: str) -> bool:
    """Return True during the US active window (Sydney 17:00 through next day 11:00)."""
    sydney = pytz.timezone('Australia/Sydney')
    now = datetime.now(sydney)
    # Active Sydney hours: 17-23 same day, 0-11 next day, Mon-Fri for 17-23 and Tue-Sat for 0-11.
    if market != 'us':
        return False
    if now.hour >= 17 and now.weekday() < 5:
        return True
    if now.hour <= 11 and now.weekday() >= 1:
        return True
    return False


def run_fast_feed(market: str = 'us') -> bool:
    if not _is_active_market_window(market):
        logger.info("Outside active %s window; skipping fast feed", market.upper())
        return True

    snapshot = _load_last_snapshot(market)
    if not snapshot:
        logger.warning("No snapshot found for fast feed")
        return False

    tickers = []
    for r in (snapshot.get('scan_results') or []):
        t = r.get('ticker')
        if t:
            tickers.append(str(t).upper())
    # Also include tickers in pre_market_results/watchlist if present
    for key in ['pre_market_results', 'pre_market_watchlist']:
        for r in (snapshot.get(key) or []):
            t = r.get('ticker')
            if t:
                tickers.append(str(t).upper())

    tickers = list(dict.fromkeys(tickers))
    if not tickers:
        logger.info("No tickers to refresh in fast feed")
        return True

    config = load_config()
    client = WebullClient(config.get('webull', {}))

    # Fetch quotes in batches to keep it fast
    updates = {}
    batch_size = 25
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            quotes = client.get_quotes(batch)
            for tkr, q in (quotes or {}).items():
                if q:
                    updates[str(tkr).upper()] = _quote_fields(q)
        except Exception as e:
            logger.warning("Fast feed quote batch failed: %s", e)

    fast_feed = {
        'market': market,
        'last_updated': datetime.now(timezone.utc).isoformat(),
        'based_on_snapshot': snapshot.get('last_updated'),
        'ticker_count': len(tickers),
        'updates': updates,
    }
    _write_fast_feed(fast_feed, market)
    logger.info("Fast feed updated for %d tickers (%d quotes)", len(tickers), len(updates))
    return True


if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    parser = argparse.ArgumentParser()
    parser.add_argument('--market', choices=['us', 'au'], default='us')
    args = parser.parse_args()
    ok = run_fast_feed(args.market)
    sys.exit(0 if ok else 1)
