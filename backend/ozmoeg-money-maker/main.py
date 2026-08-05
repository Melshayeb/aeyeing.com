#!/usr/bin/env python3
"""
OzMoEg Money Maker — Full Pipeline Main Entry Point
1. Check kill switches
2. Fetch and enrich Webull gainers/losers
3. Apply momentum + bounce filters
4. For each candidate: technical analysis, news scoring, trade plan
5. Send high-quality Telegram alerts (if configured)
6. Update website JSON/HTML with full scan data
"""
import argparse
import logging
import sys
import json
import os
import hashlib
import time
import pytz
from pathlib import Path
from datetime import datetime, timezone as dt_timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional

from kill_switch import load_config, is_enabled, component_enabled
from webull_client import WebullClient
from scanner import SmallCapScanner, _country_from_quote
from analyzer import TechnicalAnalyzer
from trade_planner import TradePlanner
from news_monitor import NewsMonitor
from tape_analyzer import TapeAnalyzer
from notifier import Notifier
from website_updater import WebsiteUpdater
from state_store import NotificationState
from sec_filings import summarize_filings

# Configure logging
log_file = Path.home() / ".hermes/skills/ozmoeg-money-maker/logs/ozmoeg.log"
log_file.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

SKILL_DIR = Path.home() / ".hermes/skills/ozmoeg-money-maker"
def _market_status_now(market: str = 'us', _now_override=None) -> str:
    """Return market status for US or AU.

    US: OPEN, PRE-MARKET, AFTER-HOURS, WEEKEND, CLOSED (ET clock).
    AU: OPEN, CLOSED, WEEKEND (ASX 10:00-16:00 AEST/AEDT).

    _now_override is an optional timezone-aware datetime for deterministic tests.
    """
    import pytz
    from datetime import datetime as _dt
    market = str(market).lower()
    if market == 'au':
        sydney = pytz.timezone('Australia/Sydney')
        now = _now_override if _now_override else _dt.now(sydney)
        if now.tzinfo is None:
            now = sydney.localize(now)
        weekday = now.weekday()
        minutes = now.hour * 60 + now.minute
        if weekday >= 5:
            return 'WEEKEND'
        if 600 <= minutes < 960:  # 10:00 - 16:00
            return 'OPEN'
        return 'CLOSED'
    # US
    et = pytz.timezone('America/New_York')
    now = _now_override if _now_override else _dt.now(et)
    if now.tzinfo is None:
        now = et.localize(now)
    weekday = now.weekday()
    minutes = now.hour * 60 + now.minute
    if weekday >= 5:
        return 'WEEKEND'
    if minutes < 570:  # 09:30
        if minutes >= 240:  # 04:00
            return 'PRE-MARKET'
        return 'CLOSED'
    if minutes < 960:  # 16:00
        return 'OPEN'
    if minutes < 1200:  # 20:00
        return 'AFTER-HOURS'
    return 'CLOSED'
def _market_status_label_for_telegram(market: str, status: str) -> str:
    """Return a user-friendly label for Telegram market-status notifications."""
    market = str(market).lower()
    if market == 'au':
        if status == 'OPEN':
            return 'ASX Open'
        if status == 'WEEKEND':
            return 'ASX Weekend Closed'
        return 'ASX Closed'
    return f"US Market {status}"
def _is_us_active_trading_window() -> bool:
    """
    Return True for the Sydney-time active US window:
    17:00 Sydney through 23:59 Sydney.  During this window the website
    refreshes every 1 minute by cron and covers:
      - 17:00-17:59 Sydney: pre-market catalyst watchlist (1h before US pre-market)
      - 18:00-23:59 Sydney: US pre-market + first 30 minutes of market open.
    Outside this window (US open after 09:30 ET, after-hours, closed, weekends)
    the website uses a slower cadence or no refresh at all.
    """
    import pytz
    from datetime import datetime as _dt
    sydney = pytz.timezone('Australia/Sydney')
    sydney_now = _dt.now(sydney)
    if sydney_now.weekday() >= 5:
        return False
    sydney_today_17 = sydney_now.replace(hour=17, minute=0, second=0, microsecond=0)
    sydney_today_2359 = sydney_now.replace(hour=23, minute=59, second=59, microsecond=0)
    return sydney_today_17 <= sydney_now <= sydney_today_2359

def _is_catalyst_watchlist_window() -> bool:
    """Return True during Sydney 17:00-17:59 (1 hour before US pre-market opens)."""
    import pytz
    from datetime import datetime as _dt
    sydney = pytz.timezone('Australia/Sydney')
    sydney_now = _dt.now(sydney)
    if sydney_now.weekday() >= 5:
        return False
    return sydney_now.hour == 17

def _scan_allowed_minute(market: str, market_status: str) -> bool:
    """
    Return True only when the current wall-clock minute aligns with the allowed
    cadence for this market status.  The cron job fires every minute; this gate
    silently no-ops when the current phase does not need a scan.

    Rules (Sydney time, US market clock is secondary):
    - US CLOSED/WEEKEND      : NO scans.
    - US CLOSED but Sydney 17:00-17:59: catalyst watchlist scans every 1 minute.
    - US PRE-MARKET          : every 1 minute.
      Active pre-market window is Sydney 18:00-23:59 (after 23:30 ET the US market
      is open and the website shifts to 1-minute cadence).
    - US OPEN                : every 1 minute (user requested 1-min refresh across
      all active US phases; previously throttled to 10 minutes).
    - US AFTER-HOURS         : every 1 minute (same 1-min refresh policy).
    - AU OPEN                : exactly twice per day at 10:30 and 13:30 Sydney.
    - AU CLOSED/WEEKEND      : NO scans.
    """
    from datetime import datetime as _dt
    import pytz
    sydney_now = _dt.now(pytz.timezone('Australia/Sydney'))
    minute = sydney_now.minute
    hour = sydney_now.hour
    weekday = sydney_now.weekday()

    market = str(market).lower()
    status = str(market_status).upper()

    if market == 'au':
        if status != 'OPEN' or weekday >= 5:
            return False
        # Exactly two scans during ASX hours: 10:30 and 13:30 Sydney
        return (hour == 10 and minute == 30) or (hour == 13 and minute == 30)

    if market == 'us':
        # Catalyst watchlist window: 1h before US pre-market, no live market data yet.
        if _is_catalyst_watchlist_window():
            return True
        if status in ('CLOSED', 'WEEKEND'):
            return False
        # User wants 1-minute refresh across every active US phase (pre-market,
        # open market, after-hours).  The old 10-minute throttle for open/after-hours
        # is removed; CLOSED and WEEKEND still skip entirely.
        if status in ('PRE-MARKET', 'OPEN', 'AFTER-HOURS'):
            return True
    return False


def _is_telegram_notification_allowed(market: str, market_status: str) -> bool:
    """
    Telegram notification policy:
    - US PRE-MARKET (active Sydney window ~18:00 until 09:30 ET): Telegram ON.
    - US OPEN: NO Telegram.
    - US AFTER-HOURS: NO Telegram.
    - US CLOSED/WEEKEND: NO Telegram and no scans.
    - AU: no Telegram (website-only refresh at 10:30 and 13:30 Sydney).
    """
    status = str(market_status).upper()
    market = str(market).lower()

    if market == 'us':
        return status == 'PRE-MARKET'

    if market == 'au':
        return False

    return False

def _change_pct_from_ranking(item: Dict) -> float:
    """Extract change percentage from a Webull ranking payload (legacy shape)."""
    if not isinstance(item, dict):
        return 0.0
    t = item.get('ticker', {}) if isinstance(item.get('ticker'), dict) else item
    values = item.get('values', {}) if isinstance(item, dict) else {}
    # Try explicit change ratio fields first (legacy decimals, e.g. 1.7365 = +73.65%)
    for key in ('changeRatio', 'change_ratio', 'change'):
        v = values.get(key) if isinstance(values, dict) else t.get(key)
        if v is None:
            v = t.get(key)
        if v is not None:
            try:
                fv = float(v)
                return (fv - 1) * 100 if fv > 1 else fv * 100
            except (TypeError, ValueError):
                continue
    # Derive from price vs close
    close = float(t.get('close', 0) or 0)
    price = float(t.get('pprice', 0) or values.get('price', 0) or 0)
    if close > 0 and price > 0:
        return (price - close) / close * 100
    return 0.0


def _extract_ticker_dict(stock: Dict) -> Dict:
    """Return the inner ticker dict from a Webull ranking payload."""
    t = stock.get('ticker', stock)
    return t if isinstance(t, dict) else {}
def _symbol(stock: Dict) -> str:
    """Return symbol from a Webull ranking payload."""
    t = _extract_ticker_dict(stock)
    return t.get('symbol', '') or stock.get('symbol', '')
def _name(stock: Dict) -> str:
    """Return company name from a Webull ranking payload."""
    t = _extract_ticker_dict(stock)
    return t.get('name', '') or _symbol(stock)
def _price(stock: Dict) -> float:
    """Return current/last price from a Webull ranking payload."""
    t = _extract_ticker_dict(stock)
    v = stock.get('values', {})
    price = float(v.get('price', 0) or t.get('pprice', 0) or t.get('close', 0) or 0)
    return price
def _change_pct(stock: Dict) -> float:
    """Compute change percentage from a Webull ranking payload."""
    t = _extract_ticker_dict(stock)
    v = stock.get('values', {})
    close = float(t.get('close', 0) or 0)
    pre_close = float(t.get('preClose', 0) or 0)
    price = float(v.get('price', 0) or t.get('pprice', 0) or 0)
    change_ratio = float(v.get('changeRatio', 0) or t.get('changeRatio', 0) or 0)
    if close > 0 and price > 0 and price != close:
        return (price - close) / close * 100
    if pre_close > 0 and close > 0:
        return (close - pre_close) / pre_close * 100
    if change_ratio > 1:
        return (change_ratio - 1) * 100
    return change_ratio * 100
def _volume(stock: Dict) -> int:
    """Return volume from a Webull ranking payload."""
    t = _extract_ticker_dict(stock)
    return int(t.get('volume', 0) or 0)
def _market_cap(stock: Dict) -> float:
    """Return market cap from a Webull ranking payload."""
    t = _extract_ticker_dict(stock)
    return float(t.get('marketValue', 0) or 0)

def _cap_size(mcap: float) -> str:
    """Classify market-cap tier for display badges (not a hard filter)."""
    if mcap <= 0:
        return ''
    if mcap < 50_000_000:
        return 'nano-cap'
    if mcap < 300_000_000:
        return 'micro-cap'
    return 'small-cap'

def _is_penny_stock(price: float) -> bool:
    """Penny-stock display flag: price under $1.00 (or A$1.00 for ASX)."""
    return price > 0 and price < 1.0

def _float_shares(stock: Dict) -> int:
    """Return float (outstanding shares proxy) from a Webull ranking payload.
    If Webull does not expose outstandingShares, fall back to market_cap / price
    so the website still shows a reasonable float proxy for display/filters."""
    t = _extract_ticker_dict(stock)
    fl = int(t.get('outstandingShares', 0) or t.get('totalShares', 0) or 0)
    if fl <= 0:
        mcap = _market_cap(stock)
        price = _price(stock)
        if mcap > 0 and price > 0:
            fl = int(round(mcap / price))
    return fl

def _country(stock: Dict) -> str:
    """Return origin country if already enriched."""
    t = _extract_ticker_dict(stock)
    return stock.get('country', '') or t.get('_country', '')
def _rvol(stock: Dict) -> float:
    """Return an approximate relative volume if already computed, else 0."""
    return float(stock.get('_rvol', stock.get('rvol', 0)) or 0)
def _scan_reason(stock: Dict) -> str:
    """Return the filter reason attached by SmallCapScanner."""
    return stock.get('_scan_reason', '')
def _scan_passed(stock: Dict) -> bool:
    """Return whether the stock passed the scanner filter."""
    return bool(stock.get('_scan_passed', False))
def _format_market_time() -> str:
    """Return formatted market time string for logging/info."""
    sydney = pytz.timezone('Australia/Sydney')
    return datetime.now(sydney).strftime('%I:%M %p AEST')

def _run_catalyst_watchlist(config: Dict[str, Any], args, client: WebullClient) -> Dict[str, Any]:
    """
    Catalyst-only watchlist run for Sydney 17:00-17:59 (1h before US pre-market opens).
    No live price/volume data is reliable yet, so we nominate tickers purely from
    news/catalyst quality, with no trade-plan or Telegram alert output.
    """
    market = 'us'
    market_status = 'CLOSED'
    scan_cfg = config.get('scanner', {})
    news_cfg = config.get('news', {})
    web_path = Path.home() / 'Desktop/aeyeing.com/ozmoeg-latest.json'

    logger.info("=== Running OzMoEg Catalyst Watchlist (US market still closed) ===")

    # Seed universe: yesterday's saved watchlist + alerts + any pre-market gainers Webull gives us.
    universe_symbols = set()
    previous_watchlist = []
    try:
        if web_path.exists():
            old_data = json.loads(web_path.read_text(encoding='utf-8'))
            for r in (old_data.get('pre_market_watchlist', []) or []):
                t = r.get('ticker')
                if t:
                    universe_symbols.add(str(t).upper())
                    previous_watchlist.append(r)
            for r in (old_data.get('pre_market_results', []) or []):
                t = r.get('ticker')
                if t:
                    universe_symbols.add(str(t).upper())
            for r in (old_data.get('scan_results', []) or []):
                t = r.get('ticker')
                if t:
                    universe_symbols.add(str(t).upper())
    except Exception as e:
        logger.warning("Could not load previous watchlist universe: %s", e)

    # Try to add current Webull pre-market gainers if any exist at 3 AM ET.
    try:
        pre_resp = client.active_gainer_loser(direction='gainer', rank_type='preMarket') or {}
        for item in pre_resp.get('gainer_list', []) or []:
            t = item.get('ticker', item) if isinstance(item, dict) else item
            sym = t.get('symbol', '') if isinstance(t, dict) else (t if isinstance(t, str) else '')
            if sym:
                universe_symbols.add(str(sym).upper())
    except Exception as e:
        logger.warning("Could not fetch pre-market gainers for watchlist seed: %s", e)

    logger.info("Catalyst watchlist universe size: %d", len(universe_symbols))

    # Load news and score each candidate.
    news_monitor = NewsMonitor(client, news_cfg)
    watchlist = []
    min_score = int(scan_cfg.get('catalyst_watchlist_min_news_score', 3))
    min_mkt = float(scan_cfg.get('catalyst_watchlist_min_mkt_cap', 1_000_000))
    max_mkt = float(scan_cfg.get('catalyst_watchlist_max_mkt_cap', 300_000_000))
    price_min = float(scan_cfg.get('extended_hours_price_min', 0.20))
    price_max = float(scan_cfg.get('extended_hours_price_max', 50.0))

    def _build_watchlist_item(sym: str):
        try:
            analysis = news_monitor.analyze(sym)
            max_score = 0
            red_flags = analysis.get('red_flags', [])
            for h in analysis.get('headlines', []):
                s = h.get('score', 0)
                if isinstance(s, (int, float)):
                    max_score = max(max_score, int(s))

            # Reject if red-flagged or below catalyst score threshold.
            if red_flags:
                return None
            if max_score < min_score:
                return None

            # Fetch a minimal quote for price/market-cap sanity only.
            quote = {}
            try:
                quotes = client.get_quotes([sym], max_workers=2, ticker_ids={})
                quote = quotes.get(sym.upper(), {}) or {}
            except Exception:
                pass

            price = (
                float(quote.get('pprice') or 0)
                or float(quote.get('price') or 0)
                or float(quote.get('close') or 0)
                or float(quote.get('preClose') or 0)
                or 0
            )
            market_cap = float(quote.get('marketValue', 0) or 0)
            name = quote.get('name', '') or sym

            if price and not (price_min <= price <= price_max):
                return None
            if market_cap and not (min_mkt <= market_cap <= max_mkt):
                return None

            # Compose a concise catalyst headline.
            catalyst_headline = analysis.get('catalyst', '')
            if not catalyst_headline and analysis.get('headlines'):
                catalyst_headline = analysis['headlines'][0].get('title', '')

            return {
                'ticker': sym,
                'name': name,
                'status': 'WATCHLIST',
                'source': 'watchlist',
                'price': price,
                'change_pct': 0.0,
                'volume': 0,
                'market_cap': market_cap,
                'scan_reason': f'Catalyst score {max_score}/{min_score}',
                'scan_passed': True,
                'result': f'Catalyst watchlist · score {max_score}',
                'news': analysis,
                'date': datetime.now().strftime('%Y-%m-%d'),
                'time': datetime.now().strftime('%H:%M:%S'),
                'catalyst_headline': catalyst_headline,
            }
        except Exception as e:
            logger.warning("Failed to build watchlist item for %s: %s", sym, e)
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(_build_watchlist_item, sym) for sym in universe_symbols]
        for future in as_completed(futures):
            item = future.result(timeout=30)
            if item:
                watchlist.append(item)

    # Sort by highest news score first.
    watchlist.sort(key=lambda x: max((h.get('score', 0) for h in x.get('news', {}).get('headlines', [])), default=0), reverse=True)
    watchlist = watchlist[:30]  # cap to avoid bloat

    scan_stats = {
        'market': market,
        'market_status': market_status,
        'market_time': _format_market_time(),
        'total_scanned': len(universe_symbols),
        'gainers_scanned': len(universe_symbols),
        'losers_scanned': 0,
        'filter_pass_count': len(watchlist),
        'bounce_pass_count': 0,
        'bounce_results': [],
        'all_gainers': [],
        'all_losers': [],
        'pre_market_watchlist': watchlist,
        'scan_time': time.time(),
    }

    # Update website. Telegram is suppressed because tg_allowed returns False for CLOSED.
    website_updater = WebsiteUpdater(config.get('website_updater', {}), client)
    website_updater.update(watchlist, None, scan_stats)
    logger.info("Catalyst watchlist completed: %d candidates", len(watchlist))
    return {"scan_results": watchlist, "active_plan": None, "scan_stats": scan_stats, "sent_alerts_summary": []}

def run_scan(config: Dict[str, Any], args) -> Dict[str, Any]:
    """Run single scanner cycle."""
    scan_type = config.get('scanner', {}).get('type', 'regular')  # 'regular' or 'bouncers'
    market = config.get('scanner', {}).get('market', 'us')
    market_status = _market_status_now(market)
    logger.info("=== Running OzMoEg %s Scan (Market=%s, Status=%s) ===", scan_type, market, market_status)

    # Check if this scan is allowed by cadence
    if not args.force and not _scan_allowed_minute(market, market_status):
        logger.info("Cadence gate: %s %s minute not aligned with schedule — skipping",
                    market.upper(), market_status)
        return {"skipped": True, "reason": "cadence gate"}

    # Re-apply overrides for US/AU mode and force mode effects (if any)
    if config.get('scanner', {}).get('market', 'us') != market:
        config['scanner']['market'] = market
        config['webull']['region_code'] = 18 if market == 'au' else 6
        config['webull']['market'] = market
        config.setdefault('news', {})['market'] = market

    # Merge active config merges for logging
    active_settings = {
        'market': market,
        'type': scan_type,
        'status': market_status,
        'force': bool(args.force)
    }

    try:
        # Get the client and run raw gainers / losers
        client = WebullClient(config.get('webull', {}))

        # Determine scanning logic: pre-market and regular scan
        market_status_lower = market_status.lower()
        if market_status_lower in ('pre-market', 'after-hours'):
            # Special logic for extended-hours: lower news gate, relaxed TA
            pass

        # --- Catalyst watchlist mode (Sydney 17:00-17:59, before US pre-market opens) ---
        if market == 'us' and _is_catalyst_watchlist_window() and market_status == 'CLOSED':
            return _run_catalyst_watchlist(config, args, client)

        # Determine the appropriate Webull ranking endpoint for the current market phase.
        market_status_lower = market_status.lower()
        if market_status_lower == 'pre-market':
            rank_type = 'preMarket'
        elif market_status_lower == 'after-hours':
            rank_type = 'afterMarket'
        elif market_status_lower == 'open':
            rank_type = 'openMarket'
        elif market_status_lower == 'closed':
            rank_type = 'preMarket'  # try to get something during the watchlist gap; normal scan won't run here
        else:
            rank_type = 'openMarket'

        logger.info(f"Starting US scan at {_format_market_time()} (status={market_status}, rank={rank_type})")

        # Main scanner run
        gainer_loser = client.active_gainer_loser(direction='gainer', rank_type=rank_type) or {"gainer_list": [], "loser_list": []}

        # Robust fallback: if the chosen ranking endpoint returned empty/no list,
        # try the daily ranking as a last resort so we never report 0 simply because
        # the endpoint name changed.  Never merge fallback results; replace them.
        if not gainer_loser.get('gainer_list') and not gainer_loser.get('loser_list') and rank_type != '1d':
            logger.info("Empty response from rank_type=%s — trying 1d fallback", rank_type)
            gainer_loser = client.active_gainer_loser(direction='gainer', rank_type='1d') or {"gainer_list": [], "loser_list": []}

        all_gainers = gainer_loser.get('gainer_list', [])
        all_losers = gainer_loser.get('loser_list', [])
        logger.info("Fetched %d gainers and %d losers", len(all_gainers), len(all_losers))

        # If we still have no losers but have gainers, ask for losers explicitly.
        if all_gainers and not all_losers:
            loser_resp = client.active_gainer_loser(direction='loser', rank_type=rank_type) or {"gainer_list": [], "loser_list": []}
            all_losers = loser_resp.get('loser_list', [])
            logger.info("Explicit loser fetch returned %d losers", len(all_losers))

        # Build scanner, feeding the current market_status so that the scanner uses
        # the same relaxed/regular thresholds as the website promises. The explicit
        # setting overrides the scanner's own ET clock detection.
        scanner_cfg = config.get('scanner', {})
        scanner_cfg['market_status'] = market_status
        scanner = SmallCapScanner(client, scanner_cfg, config.get('webull', {}).get('region_code', 6), market)

        # Separate regular candidates from bounce candidates (bouncers)
        regular_candidates = []
        bounce_candidates = []
        all_gainers_output = []
        all_losers_output = []

        # Batch-enrich all gainers in one parallel quote call, then filter.
        enriched_gainers = scanner.enrich_gainers_with_quotes(all_gainers)
        for enriched in enriched_gainers:
            passed, reason = scanner._passes_filter_with_reason(enriched, mode='momentum')
            enriched['_scan_passed'] = passed
            enriched['_scan_reason'] = reason
            if passed:
                regular_candidates.append(enriched)

        # Bounce scanner pass (Option C — beaten-down losers; research-only, never alerted)
        for gainer in all_losers:
            passed, reason = scanner._passes_filter_with_reason(gainer, mode='bounce')
            gainer['_scan_passed'] = passed
            gainer['_scan_reason'] = reason
            if passed:
                bounce_candidates.append(gainer)

        # Store all raw gainer/loser payloads for website visibility (debug purposes)
        for gainer in all_gainers:
            all_gainers_output.append({
                'ticker': _symbol(gainer),
                'name': _name(gainer),
                'price': _price(gainer),
                'change_pct': _change_pct(gainer),
                'volume': _volume(gainer),
                'rvol': _rvol(gainer),
                'market_cap': _market_cap(gainer),
                'float_shares': _float_shares(gainer),
                'cap_size': _cap_size(_market_cap(gainer)),
                'is_penny_stock': _is_penny_stock(_price(gainer)),
                'passed': _scan_passed(gainer),
                'reason': _scan_reason(gainer)
            })
        for gainer in all_losers:
            all_losers_output.append({
                'ticker': _symbol(gainer),
                'name': _name(gainer),
                'price': _price(gainer),
                'change_pct': _change_pct(gainer),
                'volume': _volume(gainer),
                'rvol': _rvol(gainer),
                'market_cap': _market_cap(gainer),
                'float_shares': _float_shares(gainer),
                'cap_size': _cap_size(_market_cap(gainer)),
                'is_penny_stock': _is_penny_stock(_price(gainer)),
                'passed': _scan_passed(gainer),
                'reason': _scan_reason(gainer)
            })

        # Determine scan status — keys must match website_updater.py expectations
        scan_stats = {
            'us_filters': config.get('scanner', {}).get('us_filters', {}),
            'au_filters': config.get('scanner', {}).get('au_filters', {}),
            'market': market,
            'market_status': scanner.cfg.get('market_status', market_status).upper(),
            'market_time': _format_market_time(),
            'total_scanned': len(all_gainers),
            'gainers_scanned': len(all_gainers),
            'losers_scanned': len(all_losers),
            'filter_pass_count': len(regular_candidates),
            'bounce_pass_count': len(bounce_candidates),
            'bounce_results': bounce_candidates,
            'all_gainers': all_gainers_output,
            'all_losers': all_losers_output,
            'scan_time': time.time()
        }

        # Build full result set: regular candidates (source 'regular') + bounce candidates (source 'bounce')
        scan_results = []

        # Create entries for regular candidates in parallel.
        # Each candidate still needs TA, news and a trade plan, but we run them
        # concurrently with a small thread pool instead of blocking sequentially.
        def _build_regular_result(gainer):
            ticker = _symbol(gainer)
            name = _name(gainer)

            # Technical analysis engine
            analyzer = TechnicalAnalyzer(config.get('analyzer', {}))
            analysis = analyzer.analyze(gainer)
            gainer['ta'] = analysis

            # News monitor and scoring
            news_monitor = NewsMonitor(client, config.get('news', {}))
            news_data = news_monitor.analyze(ticker)
            gainer['news'] = news_data

            # Build trade plan from quote fields
            planner = TradePlanner(config.get('strategy', {}))
            entry_price = _price(gainer)
            atr_val = analysis.get('atr', 0) or 0
            confidence = 'HIGH' if analysis.get('near_demand') else 'MED'
            account_balance = config.get('strategy', {}).get('account_balance', 10000.0)
            plan = planner.plan_trade(ticker, entry_price, atr_val, confidence=confidence, account_balance=account_balance)

            is_live_setup = (
                ticker and plan and
                (plan.get('entry_price') is not None or plan.get('entry') is not None) and
                (plan.get('stop_loss') is not None or plan.get('stop') is not None) and
                plan.get('targets') and
                plan.get('risk_reward') is not None
            )
            status = 'ALERT' if is_live_setup else 'CANDIDATE'
            if market == 'au' and not config.get('webull', {}).get('use_official_api'):
                status = 'CANDIDATE'

            # Build a concise result summary for the table
            entry = plan.get('entry') or plan.get('entry_price') or _price(gainer) or 0
            stop = plan.get('stop') or plan.get('stop_loss') or 0
            targets = plan.get('targets', {})
            t1 = targets.get('t1') if isinstance(targets, dict) else None
            t2 = targets.get('t2') if isinstance(targets, dict) else None
            t3 = targets.get('t3') if isinstance(targets, dict) else None
            change_str = f"{('+' if _change_pct(gainer) >= 0 else '')}{_change_pct(gainer):.1f}%"
            price_str = f"${float(entry):.2f}" if entry else '—'
            if status == 'ALERT' and entry and stop:
                result_summary = f"{change_str} · Entry {price_str} · T1 ${float(t1):.2f} · T2 ${float(t2):.2f} · T3 ${float(t3):.2f}" if t1 and t2 and t3 else change_str
            else:
                result_summary = _scan_reason(gainer) or change_str

            # Tape / volume indicator (15s proxy). Pass the inner ticker dict which holds
            # volume and average-volume fields enriched by the scanner quote batch.
            tape_analyzer = TapeAnalyzer(config.get('tape', {}))
            tape_data = tape_analyzer.analyze_ticker(ticker, None, gainer.get('ticker', gainer))
            gainer['tape'] = tape_data

            # Fetch recent SEC EDGAR filings for the alert/candidate row.
            # Rate-limited internally; if it fails we simply leave the field blank.
            sec_filings_summary = ''
            try:
                sec_filings_summary = summarize_filings(ticker, max_age_days=90, max_results=3)
            except Exception as e:
                logger.debug("SEC filings lookup failed for %s: %s", ticker, e)

            return {
                'ticker': ticker,
                'name': name,
                'status': status,
                'source': 'regular',
                'price': _price(gainer),
                'change_pct': _change_pct(gainer),
                'volume': _volume(gainer),
                'market_cap': _market_cap(gainer),
                'float_shares': _float_shares(gainer),
                'country': _country(gainer),
                'cap_size': _cap_size(_market_cap(gainer)),
                'is_penny_stock': _is_penny_stock(_price(gainer)),
                'scan_reason': _scan_reason(gainer),
                'scan_passed': _scan_passed(gainer),
                'sec_filings': sec_filings_summary,
                'result': result_summary,
                'plan': plan,
                'ta': analysis,
                'news': news_data,
                'tape': tape_data,
                'date': datetime.now().strftime('%Y-%m-%d'),
                'time': datetime.now().strftime('%H:%M:%S'),
                'skip_news_check': (market_status.lower() in ('open', 'after-hours'))
            }

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(_build_regular_result, g) for g in regular_candidates]
            for future in as_completed(futures):
                try:
                    result = future.result(timeout=30)
                    scan_results.append(result)
                except Exception as e:
                    logger.warning("Failed to build regular result: %s", e)

        # Create entries for bounce candidates (never alert)
        for gainer in bounce_candidates:
            # Bounce research: tag with 'bounce' source and note -20% to +20% range
            ticker = _symbol(gainer)
            name = _name(gainer)
            sec_filings_summary = ''
            try:
                sec_filings_summary = summarize_filings(ticker, max_age_days=90, max_results=3)
            except Exception as e:
                logger.debug("SEC filings lookup failed for bounce %s: %s", ticker, e)
            scan_results.append({
                'ticker': ticker,
                'name': name,
                'status': 'BOUNCE',
                'source': 'bounce',
                'price': _price(gainer),
                'change_pct': _change_pct(gainer),
                'volume': _volume(gainer),
                'market_cap': _market_cap(gainer),
                'float_shares': _float_shares(gainer),
                'cap_size': _cap_size(_market_cap(gainer)),
                'is_penny_stock': _is_penny_stock(_price(gainer)),
                'scan_reason': _scan_reason(gainer),
                'scan_passed': _scan_passed(gainer),
                'sec_filings': sec_filings_summary,
                'result': _scan_reason(gainer) or f"{('+' if _change_pct(gainer) >= 0 else '')}{_change_pct(gainer):.1f}%",
                'reason_note': 'bounce_research'
            })

        # Telegram is suppressed when market is closed and reduced to active-hours only.
        sent_alerts_summary = []
        tg_allowed = _is_telegram_notification_allowed(market, market_status)
        if tg_allowed and market == 'us' and config.get('scanner', {}).get('enabled', True):
            notifier = Notifier(config)
            # Send a single pre-market summary of unique ALERT triggers instead of one message per ticker.
            summary_sent = notifier.send_pre_market_summary(scan_results, market=market, market_status=market_status)
            sent_alerts_summary.append({'summary': summary_sent})
        elif not tg_allowed:
            logger.info("Telegram notifications suppressed: market=%s status=%s", market, market_status)

        # Update the website (html + json) with full scan data
        active_plan = None
        for result in scan_results:
            if result.get('status') == 'ALERT' and result.get('plan'):
                active_plan = result
                break
        website_updater = WebsiteUpdater(
            config.get('website_updater', {}),
            client
        )
        website_updater.update(
            scan_results, active_plan, scan_stats
        )
        logger.info("Website update completed successfully")
        return {"scan_results": scan_results, "active_plan": active_plan, "scan_stats": scan_stats, "sent_alerts_summary": sent_alerts_summary}
    except Exception as e:
        logger.error("Error in run_scan: %s", e)
        import traceback
        logger.error("Stack trace: %s", traceback.format_exc())
        return {"scan_results": [], "active_plan": None, "scan_stats": scan_stats, "sent_alerts_summary": {}, "error": str(e)}
def main():
    parser = argparse.ArgumentParser(description='OzMoEg Money Maker Scanner')
    parser.add_argument('--mode', choices=['scan', 'paper', 'live'], default='scan',
                        help='Trading mode (default: scan)')
    parser.add_argument('--market', choices=['us', 'au'], default=None,
                        help='Market to scan (us or au)')
    parser.add_argument('--force', action='store_true',
                        help='Force scan regardless of cadence gating')
    parser.add_argument('--kill-status', action='store_true',
                        help='Show kill-switch status and exit')
    args = parser.parse_args()

    config = load_config()

    if args.market:
        config['scanner']['market'] = args.market
        config['webull']['region_code'] = 18 if args.market == 'au' else 6
        config['webull']['market'] = args.market
        config.setdefault('news', {})['market'] = args.market
    elif args.mode in ('us', 'au'):
        config['scanner']['market'] = args.mode
        config['webull']['region_code'] = 18 if args.mode == 'au' else 6
        config['webull']['market'] = args.mode
        config.setdefault('news', {})['market'] = args.mode

    if args.mode == 'paper':
        config['webull']['paper_mode'] = True
    elif args.mode == 'live':
        config['webull']['paper_mode'] = False

    if args.kill_status:
        from kill_switch import show_kill_status
        show_kill_status(config)
        return 0

    result = run_scan(config, args)

    if result.get('skipped'):
        logger.info("Scanner skipped: %s", result.get('reason'))
        print(f"\n⚠️ Scanner skipped: {result.get('reason')}")

    return 0

if __name__ == "__main__":
    sys.exit(main())