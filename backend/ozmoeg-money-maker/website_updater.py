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

            self._update_html(scan_results, active_plan, scan_stats, pre_market_results=pre_market_results)
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
        """Replace content using simple string markers. Only updates static sections; trade plan / tracker / news are rendered client-side from ozmoeg-latest.json."""
        if not self.html_file.exists():
            logger.warning("HTML file not found: %s", self.html_file)
            return

        # Use scan_stats to determine market if provided, else fall back to config
        market = str((scan_stats or {}).get('market', self.config.get('market', 'us'))).lower()

        html_content = self.html_file.read_text(encoding='utf-8')
        alert_results = [r for r in scan_results if r.get('status') == 'ALERT']
        candidate_results = [r for r in scan_results if r.get('status') in ('ALERT', 'CANDIDATE')]
        alert_count = len(alert_results)
        candidate_count = len(candidate_results)
        skipped_count = len([r for r in scan_results if r.get('status') == 'SKIP'])
        skip_injected = len([r for r in scan_results if r.get('status') == 'INFO'])
        scan_stats = scan_stats or {}
        gainers_scanned = scan_stats.get('gainers_scanned', '—')
        market_status = scan_stats.get('market_status', 'UNKNOWN')
        market_time = scan_stats.get('market_time', '')
        # Use the same market determination as above
        market = str((scan_stats or {}).get('market', self.config.get('market', 'us'))).lower()
        is_au = market == 'au'

        def replace_between(html_text: str, start_marker: str, end_marker: str, new_content: str) -> str:
            """Replace content between start_marker and end_marker with new_content."""
            s = html_text.find(start_marker)
            e = html_text.find(end_marker)
            if s >= 0 and e >= 0:
                before = html_text[:s + len(start_marker)]
                after = html_text[e:]
                return before + '\n' + new_content + '\n                    ' + after
            return html_text

        # Update badge - count actual candidates (ALERT + CANDIDATE), not SKIP entries
        status_emoji = {"OPEN": "🟢", "PRE-MARKET": "🟡", "AFTER-HOURS": "🟡", "WEEKEND": "🔴", "CLOSED": "🔴"}.get(market_status, "⚪")
        market_label = 'AUS' if is_au else 'US'
        badge_text = f'{status_emoji} {market_label} {market_status} {market_time} | Scanned: {gainers_scanned} | {candidate_count} candidates | {alert_count} alerts (skipped: {skipped_count})'
        html_content = replace_between(html_content, '<!-- SCANNER_BADGE -->', '<!-- END_SCANNER_BADGE -->', badge_text)

        # Update table body - show only actionable results (ALERT/CANDIDATE), not all SKIP entries
        main_results = [r for r in scan_results if r.get('status') in ('ALERT', 'CANDIDATE')]
        if not main_results:
            main_results = []  # will show empty message below
        tbody_content = self._render_table_rows(main_results)
        if not tbody_content:
            tbody_content = '                            <tr><td colspan="8" style="text-align: center; color: var(--text-secondary);">No candidates met the full alert criteria in this scan</td></tr>'
        html_content = replace_between(html_content, '<!-- SCANNER_TABLE_BODY -->', '<!-- END_SCANNER_TABLE_BODY -->', tbody_content)

        all_gainers_output = scan_stats.get('all_gainers', []) or []
        all_losers_output = scan_stats.get('all_losers', []) or []

        # Regenerate the all-scanned gainers details table so it always reflects the latest scan.
        scanned_gainers_content = self._render_scanned_details_rows(
            all_gainers_output, 'scanned-gainers-details',
            '🔍 Show all 50 scanned gainers with filter reasons',
            'No gainers data available for this scan', is_au
        )
        html_content = replace_between(html_content, '<!-- SCANNED_GAINERS_TABLE -->', '<!-- END_SCANNED_GAINERS_TABLE -->', scanned_gainers_content)

        # Regenerate the all-scanned losers details table so it always reflects the latest scan.
        scanned_losers_content = self._render_scanned_details_rows(
            all_losers_output, 'scanned-losers-details',
            '🔻 Show all 50 scanned losers with filter reasons',
            'No losers data available for this scan', is_au
        )
        html_content = replace_between(html_content, '<!-- SCANNED_LOSERS_TABLE -->', '<!-- END_SCANNED_LOSERS_TABLE -->', scanned_losers_content)

        # Structural guard: ensure Forecast vs Actual and Latest Catalyst & News
        # remain INSIDE the right-panel div (below the active trade plan) instead of
        # accidentally being written as a third column next to the left panel.
        html_content = self._repair_panel_structure(html_content)

        # Structural guard 2: ensure news-catalyst-card inner content is not split out.
        # Some HTML rewrites have left the header's closing </div> premature, orphaning
        # the legend, ticker-line, catalyst-title and news-list outside the card.
        html_content = self._repair_news_catalyst_structure(html_content)

        # Persist the updated HTML so the static sections are served from GitHub Pages.
        self.html_file.write_text(html_content, encoding='utf-8')

    def _repair_panel_structure(self, html_content: str) -> str:
        """Move performance-card and news-catalyst-card back inside right-panel if a previous
        generator/rewrite left them stranded as direct children of main-grid."""
        try:
            from bs4 import BeautifulSoup
        except Exception:
            return html_content

        soup = BeautifulSoup(html_content, 'html.parser')
        main_grid = soup.find('div', class_='main-grid')
        if not main_grid:
            return html_content

        right_panel = main_grid.find('div', class_='right-panel', recursive=False)
        if not right_panel:
            return html_content

        # Find any performance-card / news-catalyst-card that are direct children of main-grid
        for cls in ('performance-card', 'news-catalyst-card'):
            for el in main_grid.find_all('div', class_=cls, recursive=False):
                right_panel.append(el)

        return str(soup)

    def _repair_news_catalyst_structure(self, html_content: str) -> str:
        """Ensure the news-catalyst-card contains its header, legend, ticker, title and news-list.

        When the template is regenerated, the closing </div> for news-header can end up
        immediately after the impact badge, leaving the rest of the content outside the
        news-catalyst-card and breaking the original card styling.
        """
        try:
            from bs4 import BeautifulSoup
        except Exception:
            return html_content

        soup = BeautifulSoup(html_content, 'html.parser')
        card = soup.find('div', {'id': 'news-catalyst-section'})
        if not card:
            return html_content

        # Identify the intended children by id/class and move any that are siblings after the card back inside.
        child_ids = ('impact-score',)
        child_classes = ('news-legend', 'news-ticker-line', 'catalyst-title', 'news-list')
        for cls in child_classes:
            for el in card.find_all_next(class_=cls):
                # Only move if it is a direct sibling of the card (or a child of a sibling)
                # and hasn't already been moved.
                if el.parent is not card and el.parent is card.parent:
                    card.append(el.extract())

        # Ensure there is exactly one closing for news-header; if the header contains the
        # impact badge and then an extra closing div, normalize by rebuilding header.
        header = card.find('div', class_='news-header')
        impact = card.find('span', id='impact-score')
        if header and impact and impact.parent is not header:
            # Impact badge is outside header; move it back.
            header.append(impact.extract())

        return str(soup)

    def _render_scanned_details_rows(self, rows_list: list, element_id: str,
                                     summary_text: str, empty_text: str,
                                     is_au: bool) -> str:
        """Render the static <details> table body for all scanned gainers or losers."""
        price_decimals = 3 if is_au else 2
        def _format_float_shares(n: float) -> str:
            if not n:
                return '—'
            if n >= 1_000_000_000:
                return f"{n / 1_000_000_000:.2f}B"
            if n >= 1_000_000:
                return f"{n / 1_000_000:.2f}M"
            if n >= 1_000:
                return f"{n / 1_000:.2f}K"
            return f"{n:,}"

        if not rows_list:
            body_rows = f'\u003ctr\u003e\u003ctd colspan="9" style="text-align:center;color:var(--text-secondary)"\u003e{empty_text}\u003c/td\u003e\u003c/tr\u003e'
        else:
            rendered_rows = []
            for stock in rows_list:
                ticker = stock.get('ticker', '')
                name = stock.get('name', '')
                price = float(stock.get('price', 0))
                change_pct = float(stock.get('change_pct', 0))
                volume = int(stock.get('volume', 0))
                rvol = float(stock.get('rvol', 0))
                market_cap = float(stock.get('market_cap', 0))
                float_shares = float(stock.get('float_shares', 0) or 0)
                if not float_shares:
                    # Fallback: derive proxy float from market cap / price
                    if market_cap > 0 and price > 0:
                        float_shares = round(market_cap / price)
                passed = bool(stock.get('passed', False))
                reason = stock.get('reason', '')
                cap_size = stock.get('cap_size', '')
                is_penny_stock = bool(stock.get('is_penny_stock', False))
                badge_class = 'scan-pass' if passed else 'scan-skip'
                badge_text = 'PASS' if passed else 'SKIP'
                cap_badge = f' <span class="country-badge">{_html_escape(cap_size.upper().replace("-", " "))}</span>' if cap_size else ''
                penny_badge = ' <span class="country-badge">PENNY</span>' if is_penny_stock else ''
                rendered_rows.append(f'''                            <tr>
                                <td class="ticker-cell">{_html_escape(ticker)}{cap_badge}{penny_badge}</td>
                                <td>{_html_escape(name)}</td>
                                <td>${price:.{price_decimals}f}</td>
                                <td>{change_pct:+.1f}%</td>
                                <td>{volume:,}</td>
                                <td>{rvol:.1f}x</td>
                                <td>${market_cap/1e6:.1f}M</td>
                                <td>{_format_float_shares(float_shares)}</td>
                                <td>{_html_escape(reason)}</td>
                            </tr>''')
            body_rows = '\n'.join(rendered_rows)

        return f'''                        <details class="scanned-details" id="{element_id}">
                            <summary>{summary_text}</summary>
                            <div class="table-wrap">
                                <table class="scanned-table">
                                    <thead>
                                        <tr>
                                            <th>Ticker</th><th>Name</th><th>Price</th><th>Change</th><th>Volume</th><th>RVOL</th><th>Mkt Cap</th><th>Float</th><th>Reason</th>
                                        </tr>
                                    </thead>
                                    <tbody>
{body_rows}
                                    </tbody>
                                </table>
                            </div>
                        </details>'''

    def _render_table_rows(self, scan_results: list) -> str:
        """Render scanner table rows HTML from a list of scan results."""
        def _impact_label(score):
            if score >= 4:
                return '🔥 High', 'impact-high'
            if score >= 2:
                return '⚡ Medium', 'impact-medium'
            return '🌱 Low', 'impact-low'

        def _tape_label(tape):
            if not tape or not isinstance(tape, dict):
                return '<span class="tape-mini tape-missing" title="Volume data unavailable">—</span>'
            if tape.get('not_available'):
                return '<span class="tape-mini tape-missing" title="Volume indicator not available for ASX">— N/A</span>'

            rvol = float(tape.get('rvol', 0) or 0)
            volume = tape.get('volume', 0)
            adv = tape.get('adv', 0)
            indicator = tape.get('volume_indicator', '')
            last = tape.get('last_trade_time', '')
            age = tape.get('stale_age_seconds', 0)
            age_note = f" · stale {int(age/60)}m" if age else ""

            if indicator == 'high':
                cls = 'tape-high'
                text = '🔥 high volume'
            elif indicator == 'moderate':
                cls = 'tape-medium'
                text = '⚡ moderate volume'
            elif indicator == 'low':
                cls = 'tape-low'
                text = '🌱 low volume'
            elif tape.get('no_move'):
                title = f"No volume recorded. Last: {last or 'unknown'}{age_note}"
                return f'<span class="tape-mini tape-missing" title="{_html_escape(title)}">— no move</span>'
            else:
                cls = 'tape-missing'
                text = '— missing'

            title = f"RVOL {rvol}x vs ADV ({volume:,} today / {adv:,} avg). Last: {last or 'unknown'}{age_note}"
            return f'<span class="tape-mini {cls}" title="{_html_escape(title)}">{text}</span>'

        def _get_score(r):
            return (r.get('news') or {}).get('max_score', 0) or 0

        def _youngest_news_age_minutes(news):
            if not news or not isinstance(news.get('headlines'), list) or not news['headlines']:
                return 999999
            raw_times = [h.get('raw_time') for h in news['headlines'] if h.get('raw_time')]
            if not raw_times:
                return 999999
            newest = min(raw_times)
            if not newest:
                return 999999
            try:
                diff_min = int((datetime.now(timezone.utc) - datetime.fromisoformat(newest.replace('Z', '+00:00'))).total_seconds() // 60)
                return max(0, diff_min)
            except Exception:
                return 999999

        # Sort: ALERT status first, then by impact score descending, then by youngest news age.
        sorted_results = sorted(
            scan_results,
            key=lambda r: (
                0 if r.get('status') == 'ALERT' else 1,
                -_get_score(r),
                _youngest_news_age_minutes(r.get('news'))
            )
        )

        table_rows = []
        for result in sorted_results:
            ticker = result.get('ticker', '')
            name = result.get('name', '')
            status = result.get('status', 'PENDING')
            result_text = result.get('result', '')
            max_score = _get_score(result)
            if status == 'ALERT':
                status_class = 'result-alert'
                emoji = "🚨"
                imp_text, imp_cls = _impact_label(max_score)
                status_html = f'<span class="{status_class}">{emoji} {status}</span> <span class="impact-mini {imp_cls}">{imp_text} ({max_score})</span>'
            elif status == 'CANDIDATE':
                status_class = 'result-candidate'
                emoji = "🔬"
                status_html = f'<span class="{status_class}">{emoji} {status}</span>'
            else:
                status_class = 'result-skip'
                emoji = "⏭️"
                status_html = f'<span class="{status_class}">{emoji} {status}</span>'
            escaped = (result_text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            news_age_html = self._render_news_age_cell(result.get('news'))
            country = result.get('country', '')
            country_badge = f' <span class="country-badge">{_html_escape(country)}</span>' if country else ''
            cap_size = result.get('cap_size', '')
            cap_badge = f' <span class="country-badge">{_html_escape(cap_size.upper().replace("-", " "))}</span>' if cap_size else ''
            penny_badge = ' <span class="country-badge">PENNY</span>' if result.get('is_penny_stock') else ''
            tape = result.get('tape') or {}
            tape_html = _tape_label(tape)

            float_val = result.get('float_shares') or 0
            if not float_val:
                # Fallback: derive a proxy float from market cap / price
                price = float(result.get('price', 0) or 0)
                mcap = float(result.get('market_cap', 0) or 0)
                if price > 0 and mcap > 0:
                    float_val = round(mcap / price)
            if not float_val:
                float_html = '—'
            elif float_val >= 1_000_000:
                float_html = f"{float_val / 1_000_000:.2f}M"
            elif float_val >= 1_000:
                float_html = f"{float_val / 1_000:.2f}K"
            else:
                float_html = f"{float_val:,}"

            sec_filings_summary = result.get('sec_filings', '') or ''
            if sec_filings_summary:
                sec_filings_html = f'<span class="sec-filings-mini" title="{_html_escape(sec_filings_summary)}">{_html_escape(sec_filings_summary)}</span>'
            else:
                sec_filings_html = '—'

            table_rows.append(f'''                            <tr>
                                <td class="ticker-cell">{ticker}{country_badge}{cap_badge}{penny_badge}</td>
                                <td>{name}</td>
                                <td>{status_html}</td>
                                <td class="news-age-cell">{news_age_html}</td>
                                <td>{tape_html}</td>
                                <td>{escaped}</td>
                                <td>{float_html}</td>
                                <td>{sec_filings_html}</td>
                            </tr>''')
        return '\n'.join(table_rows)

    def _render_news_age_cell(self, news: dict) -> str:
        """Render the newest headline age as a badge with exact-date tooltip.
        Age is recomputed from the headline's raw timestamp so saved snapshots remain accurate."""
        if not news or not isinstance(news.get('headlines'), list) or not news['headlines']:
            return '<span class="news-age missing" title="No qualifying news headlines">—</span>'
        headlines = [h for h in news['headlines'] if h.get('raw_time')]
        if not headlines:
            return '<span class="news-age missing" title="No qualifying news headlines">—</span>'
        newest = min(headlines, key=self._news_age_minutes)
        age_text = self._format_age_from_raw(newest.get('raw_time', ''))
        if not age_text:
            return '<span class="news-age missing" title="No qualifying news headlines">—</span>'
        raw_time = newest.get('raw_time', '')
        is_stale = self._is_stale_age(age_text)
        stale_class = 'news-age stale' if is_stale else 'news-age'
        stale_emoji = '⚠️ ' if is_stale else ''
        title_attr = f' title="First published: {_html_escape(raw_time)}"' if raw_time else ''
        return f'<span class="{stale_class}"{title_attr}>{stale_emoji}{_html_escape(age_text)}</span>'

    def _render_news_age_inline(self, news: dict) -> str:
        """Compact inline age badge for the live news ticker."""
        cell = self._render_news_age_cell(news)
        if 'missing' in cell:
            return ''
        return ' ' + cell

    def _news_age_minutes(self, h: dict) -> float:
        """Convert a headline's raw ISO timestamp to minutes since publication (smaller = newer)."""
        raw = h.get('raw_time', '')
        if not raw:
            return float('inf')
        try:
            from datetime import datetime as _dt, timezone as _tz
            parsed = _dt.fromisoformat(raw.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_tz.utc)
            return max(0.0, (_dt.now(_tz.utc) - parsed).total_seconds() / 60.0)
        except Exception:
            return float('inf')

    def _format_age_from_raw(self, raw: str) -> str:
        """Convert a raw ISO timestamp to a human-readable age string relative to now."""
        if not raw:
            return ''
        try:
            from datetime import datetime as _dt, timezone as _tz
            parsed = _dt.fromisoformat(raw.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_tz.utc)
            diff_min = max(0, int((_dt.now(_tz.utc) - parsed).total_seconds() / 60))
            if diff_min < 1:
                return 'just now'
            if diff_min < 60:
                return f'{diff_min}m ago'
            diff_hour = diff_min // 60
            if diff_hour < 24:
                return f'{diff_hour}h ago'
            diff_day = diff_hour // 24
            if diff_day < 30:
                return f'{diff_day}d ago'
            diff_month = int(diff_day / 30.44)
            if diff_month < 12:
                return f'{diff_month}mo ago'
            diff_year = diff_month // 12
            return f'{diff_year}y ago'
        except Exception:
            return ''

    def _is_stale_age(self, age_text: str) -> bool:
        """Return True if the age string indicates older than 7 days."""
        if not age_text:
            return False
        m = re.match(r'^(\d+)d\s+ago', age_text)
        if m and int(m.group(1)) > 7:
            return True
        if re.match(r'^(\d+)mo\s+ago|^(\d+)y\s+ago', age_text):
            return True
        return False

    def _git_push(self):
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