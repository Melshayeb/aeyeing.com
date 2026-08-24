#!/usr/bin/env python3
"""
OzMoEg Money Maker — Website Updater
Writes latest scan results to the aeyeing.com website.
Uses simple string markers for reliable updates.
"""
import json
from hermes_cli._subprocess_compat import windows_hide_flags
import subprocess
import html
import re
import time
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import logging

import pages_status
_html_escape = html.escape

logger = logging.getLogger(__name__)

class WebsiteUpdater:
    """Updates the OzMoEg Trader website with live scan results."""

    def __init__(self, config: dict, webull_client=None):
        self.config = config
        self.is_au = str(config.get('market', 'us')).lower() == 'au'
        self.repo_path = config.get('website_repo_path', str(Path.home() / "Desktop/aeyeing.com"))
        self.html_file = Path(self.repo_path) / ("ozmoeg-trader-au.html" if self.is_au else "ozmoeg-trader.html")
        self.scan_results_file = Path(self.repo_path) / ("ozmoeg-latest-au.json" if self.is_au else "ozmoeg-latest.json")
        self.wb = webull_client

    def update(self, scan_results: list, active_plan: dict = None, scan_stats: dict = None, ticker_ids: Dict[str, int] = None):
        is_au = str((scan_stats or {}).get('market', self.config.get('market', 'us'))).lower() == 'au'
        self.scan_results_file = Path(self.repo_path) / ('ozmoeg-latest-au.json' if is_au else 'ozmoeg-latest.json')
        if not self.scan_results_file.parent.exists():
            logger.warning("Website repo not found at %s — skipping update", self.repo_path)
            return False

        try:
            scan_stats = scan_stats or {}
            market_status = str(scan_stats.get('market_status', '')).upper()
            # Save the extended-hours (pre-market or after-hours) watchlist whenever we are outside
            # regular trading hours. When the market is open, keep the last extended-hours snapshot
            # so users can compare the live scan against the pre-market/after-hours setup list.
            pre_market_results = []
            pre_market_watchlist = []
            if market_status in ('PRE-MARKET', 'AFTER-HOURS'):
                pre_market_results = scan_results
            elif self.scan_results_file.exists():
                try:
                    old_data = json.loads(self.scan_results_file.read_text(encoding='utf-8'))
                    pre_market_results = old_data.get('pre_market_results', []) or []
                    pre_market_watchlist = old_data.get('pre_market_watchlist', []) or []
                except Exception:
                    pre_market_results = []
                    pre_market_watchlist = []

            # Catalyst watchlist mode: when the scan explicitly ships a watchlist,
            # overwrite the saved one; otherwise keep the previous watchlist.
            explicit_watchlist = scan_stats.get('pre_market_watchlist')
            if explicit_watchlist is not None:
                pre_market_watchlist = explicit_watchlist

            # Preserve the previous scan's live quotes so the tracker can compute
            # real scan-to-scan P&L without relying on browser localStorage.
            previous_live_quotes = {}
            previous_scan_results = []
            if self.scan_results_file.exists():
                try:
                    old_data = json.loads(self.scan_results_file.read_text(encoding='utf-8'))
                    previous_live_quotes = old_data.get('live_quotes', {}) or {}
                    previous_scan_results = old_data.get('scan_results', []) or []
                except Exception:
                    previous_live_quotes = {}
                    previous_scan_results = []

            # Build a lookup of the previous scan price per ticker so the website tracker
            # can show a reliable "Proposed Entry" that reflects the last refresh,
            # even when the previous live-quote fetch lacked this ticker.
            previous_price_by_ticker = {}
            for r in previous_scan_results:
                t = str(r.get('ticker', '')).upper()
                if not t:
                    continue
                previous_price_by_ticker[t] = r.get('price') or previous_live_quotes.get(t, {}).get('price')
            for t, q in previous_live_quotes.items():
                if q and q.get('price'):
                    previous_price_by_ticker.setdefault(str(t).upper(), q['price'])

            # Tag every result with its previous-scan price for the tracker.
            for r in scan_results:
                t = str(r.get('ticker', '')).upper()
                if t:
                    r['previous_price'] = previous_price_by_ticker.get(t)

            # Live quotes for the tracker — same Webull source the scanner uses
            # For US tickers in pre/after-hours, we also ask for extended-hours price
            # by using rank_type='preMarket'/'afterHours' endpoints if needed, and we
            # explicitly prefer the Webull 'pprice' (latest trade) field over 'close'.
            live_quotes = self._fetch_live_quotes(scan_results, active_plan, ticker_ids=ticker_ids)
            # Extended hours: if the regular Webull quote only gives prior close, try
            # fetching the pre-market/after-hours quote for US alerts so the tracker
            # reflects the actual current extended-hours price.
            if market_status in ('PRE-MARKET', 'AFTER-HOURS') and not is_au:
                # Pass market_status explicitly so the helper can pick the right rank type
                self.config['market_status'] = market_status
                extended_quotes = self._fetch_extended_hours_quotes(scan_results, active_plan)
                # Merge: extended quote wins when available and non-zero.
                for t, q in extended_quotes.items():
                    if q and q.get('price', 0) > 0:
                        live_quotes[t.upper()] = q

            timestamp_utc = datetime.now(timezone.utc)
            timestamp = timestamp_utc.isoformat().replace('+00:00', 'Z')

            data = {
                "last_updated": timestamp,
                "scan_results": scan_results,
                "pre_market_results": pre_market_results,
                "pre_market_watchlist": pre_market_watchlist,
                "bounce_results": scan_stats.get('bounce_results', []),
                "losers_scanned": scan_stats.get('losers_scanned', 0),
                "active_plan": active_plan,
                "total_candidates": len(scan_results),
                "alerts_generated": sum(1 for r in scan_results if r.get('status') == 'ALERT'),
                "all_gainers": scan_stats.get('all_gainers', []),
                "all_losers": scan_stats.get('all_losers', []),
                "live_quotes": live_quotes,
                "previous_live_quotes": previous_live_quotes,
                "scan_stats": {
                    "gainers_scanned": scan_stats.get('gainers_scanned', '—') if scan_stats else '—',
                    "losers_scanned": scan_stats.get('losers_scanned', 0) if scan_stats else 0,
                    "market_status": scan_stats.get('market_status', 'UNKNOWN') if scan_stats else 'UNKNOWN',
                    "market_time": scan_stats.get('market_time', '') if scan_stats else '',
                    "market": scan_stats.get('market', 'us') if scan_stats else 'us',
                    "au_filters": scan_stats.get('au_filters', {}) if scan_stats else {},
                    "us_filters": scan_stats.get('us_filters', {}) if scan_stats else {},
                }
            }
            # Write a uniquely-named snapshot per minute plus a manifest that points to it.
            # Cloudflare/GitHub Pages cannot cache a filename it has not seen before, defeating
            # the 10-minute max-age stale-JSON problem once and for all.
            base_name = self.scan_results_file.stem  # ozmoeg-latest or ozmoeg-latest-au
            snapshot_name = f"{base_name}_{timestamp_utc.strftime('%Y%m%d_%H%M%S')}.json"
            snapshot_file = self.scan_results_file.parent / snapshot_name
            manifest_file = self.scan_results_file.parent / (base_name.replace('-latest', '-manifest') + '.json')
            # Keep both the rolling latest file and the unique snapshot
            self.scan_results_file.write_text(json.dumps(data, indent=2))
            snapshot_file.write_text(json.dumps(data, indent=2))
            manifest_file.write_text(json.dumps({"latest": snapshot_name, "last_updated": timestamp}, indent=2))
            logger.info("Wrote scan snapshot %s and manifest %s", snapshot_file, manifest_file)

            # HTML is now fully client-side rendered from the JSON snapshot.
            # Do not rewrite ozmoeg-trader*.html here; the marker-based updater was
            # corrupting the file (0-byte writes / malformed HTML) and overwriting
            # manual JS fixes. Only update JSON/manifest and push.
            self._git_push()
            return True
        except Exception as e:
            logger.error("Website update failed: %s", e)
            return False

    def _fetch_live_quotes(self, scan_results: list, active_plan: dict = None, ticker_ids: Dict[str, int] = None) -> dict:
        """Fetch real-time quotes for every alert/candidate ticker so the website tracker
        shows the same live price source as the rest of the scanner."""
        if not self.wb:
            return {}
        tickers = set()
        for r in (scan_results or []):
            t = r.get('ticker')
            if t:
                tickers.add(str(t).upper())
        if active_plan and active_plan.get('ticker'):
            tickers.add(str(active_plan['ticker']).upper())
        if not tickers:
            return {}
        try:
            quotes = self.wb.get_quotes(list(tickers), max_workers=10, ticker_ids=ticker_ids or {})
        except Exception as e:
            logger.warning("Failed to fetch live quotes for website: %s", e)
            return {}
        normalized = {}
        for ticker, q in quotes.items():
            if not q:
                continue
            # Webull quote payloads use several price field names; normalize to 'price'.
            # For extended hours / current last trade, prefer 'pprice' over 'close'.
            price = (
                float(q.get('pprice') or 0)
                or float(q.get('price') or 0)
                or float(q.get('close') or 0)
                or float(q.get('faPrice') or 0)
                or float(q.get('lastPrice') or 0)
            )
            if price <= 0:
                continue
            normalized[str(ticker).upper()] = {
                'price': price,
                'open': float(q.get('open') or 0),
                'high': float(q.get('high') or 0),
                'low': float(q.get('low') or 0),
                'close': float(q.get('close') or 0),
                'preClose': float(q.get('preClose') or 0),
                'volume': int(q.get('volume') or 0),
                'changeRatio': float(q.get('changeRatio') or 0),
                'marketValue': float(q.get('marketValue') or 0),
                'name': q.get('name', ticker),
                '_timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
            }
        return normalized

    def _fetch_extended_hours_quotes(self, scan_results: list, active_plan: dict = None) -> dict:
        """Try to fetch the current pre-market or after-hours price via Webull active_gainer_loser ranking.
        Webull's regular quote may return the prior close; the ranking payload for rank_type='preMarket'
        or 'afterHours' contains the real extended-hours pprice/close."""
        if not self.wb:
            return {}
        tickers = set()
        for r in (scan_results or []):
            t = r.get('ticker')
            if t:
                tickers.add(str(t).upper())
        if active_plan and active_plan.get('ticker'):
            tickers.add(str(active_plan['ticker']).upper())
        if not tickers:
            return {}
        try:
            # Determine appropriate rank_type from current market status
            market_status = str(self.config.get('market_status', '')).upper()
            if market_status == 'PRE-MARKET':
                rank_type = 'preMarket'
            elif market_status == 'AFTER-HOURS':
                rank_type = 'afterHours'
            else:
                rank_type = '1d'
            raw = self.wb.active_gainer_loser(direction='gainer', rank_type=rank_type, count=200)
            items = []
            if isinstance(raw, dict):
                items = raw.get('data', []) or []
            elif isinstance(raw, list):
                items = raw
            by_ticker = {}
            for item in items:
                t = item.get('ticker', item)
                sym = t.get('symbol', '') if isinstance(t, dict) else (item if isinstance(item, str) else '')
                if not sym:
                    continue
                sym = str(sym).upper()
                if sym not in tickers:
                    continue
                v = item.get('values', {})
                # Prefer pprice (last trade), then price, then close
                price = (
                    float(v.get('pprice', 0) or t.get('pprice', 0) or 0)
                    or float(v.get('price', 0) or t.get('price', 0) or 0)
                    or float(t.get('close', 0) or 0)
                )
                if price <= 0:
                    continue
                by_ticker[sym] = {
                    'price': price,
                    'open': float(t.get('open', 0) or 0),
                    'high': float(t.get('high', 0) or 0),
                    'low': float(t.get('low', 0) or 0),
                    'close': float(t.get('close', 0) or 0),
                    'preClose': float(t.get('preClose', 0) or 0),
                    'volume': int(t.get('volume', 0) or 0),
                    'changeRatio': float(t.get('changeRatio', 0) or 0),
                    'marketValue': float(t.get('marketValue', 0) or 0),
                    'name': t.get('name', sym),
                    '_timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                }
            return by_ticker
        except Exception as e:
            logger.warning("Failed to fetch extended-hours quotes: %s", e)
            return {}

    def _update_html(self, scan_results: list, active_plan: dict = None, scan_stats: dict = None, pre_market_results: list = None):
        """DEPRECATED — kept for backwards compatibility, but does nothing.

        The trader pages are now client-side rendered from ozmoeg-latest*.json.
        Rewriting the HTML from markers repeatedly corrupted the page and overwrote
        manual fixes. Do not call this method for live updates.
        """
        logger.warning("_update_html is deprecated and no longer writes HTML files.")
        return
        """Push updated website files to GitHub Pages.

        Uses a directory lock, a minimum cool-down between pushes, and checks
        GitHub's public API to avoid colliding with an in-flight Pages
        deployment.  Concurrent pushes cause Pages to fail with the generic
        annotation "Deployment failed, try again later."
        """
        if not self.repo_path:
            logger.warning("No website repo path configured — skipping git push")
            return

        # 1. Ask GitHub if Pages is currently deploying or just failed.
        try:
            skip, reason = pages_status.should_skip_push(min_recent_failure_minutes=15.0)
            if skip:
                logger.warning("Skipping git push: %s", reason)
                return
            logger.info("Pages status check: %s", reason)
        except Exception as e:
            logger.warning("Pages status check failed (%s) — proceeding with existing lock/cool-down", e)

        # 2. Enforce a minimum 180-second cool-down after any successful Pages deploy,
        #    tracked by a sentinel file. Pages builds take ~20-30s and cannot safely
        #    accept commits faster than once every ~3 minutes.
        # NOTE: disabled — we now write uniquely-named snapshot files every minute, so
        # Pages can build continuously without the same-file overwrite race that
        # originally required this throttle.
        # try:
        #     cool_down_file = Path(self.repo_path) / '.ozmoeg_last_push'
        #     now = time.time()
        #     if cool_down_file.exists():
        #         last_push = float(cool_down_file.read_text().strip() or 0)
        #         elapsed = now - last_push
        #         if elapsed < 180:
        #             logger.warning("Git push cool-down active (%.0fs left) — skipping push", 180 - elapsed)
        #             return
        #     cool_down_file.write_text(str(now))
        # except Exception:
        #     pass

        # 3. Directory lock to avoid multiple local scanners racing.
        lock_path = Path(self.repo_path) / '.ozmoeg_push.lock'
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with open(lock_path, 'w') as _lf:
                pass
        except Exception:
            pass

        try:
            subprocess.run(['git', '-C', self.repo_path, 'add', '.'], check=False, capture_output=True, text=True, creationflags=windows_hide_flags(),)
            result = subprocess.run(['git', '-C', self.repo_path, 'commit', '-m', self.config.get('website_commit_message', 'Auto-update OzMoEg trader dashboard')], 
                                    check=False, capture_output=True, text=True, creationflags=windows_hide_flags(),)
            if result.returncode == 0:
                subprocess.run(['git', '-C', self.repo_path, 'push'], check=False, capture_output=True, text=True, creationflags=windows_hide_flags(),)
        except Exception as e:
            logger.error("Git push failed: %s", e)