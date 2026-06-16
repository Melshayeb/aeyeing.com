#!/usr/bin/env python3
"""
OzMoEg Money Maker — Website Updater
Writes latest scan results to the aeyeing.com website.
Uses simple string markers for reliable updates.
"""
import json
import subprocess
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class WebsiteUpdater:
    """Updates the OzMoEg Trader website with live scan results."""

    def __init__(self, config: dict):
        self.config = config
        self.is_au = str(config.get('market', 'us')).lower() == 'au'
        self.repo_path = config.get('website_repo_path', str(Path.home() / "Desktop/aeyeing.com"))
        self.html_file = Path(self.repo_path) / "ozmoeg-trader.html"
        self.scan_results_file = Path(self.repo_path) / "ozmoeg-latest.json"

    def update(self, scan_results: list, active_plan: dict = None, scan_stats: dict = None):
        if not self.scan_results_file.parent.exists():
            logger.warning("Website repo not found at %s — skipping update", self.repo_path)
            return False

        try:
            data = {
                "last_updated": datetime.now().isoformat(),
                "scan_results": scan_results,
                "active_plan": active_plan,
                "total_candidates": len(scan_results),
                "alerts_generated": sum(1 for r in scan_results if r.get('status') == 'ALERT'),
                "all_gainers": scan_stats.get('all_gainers', []),
                "scan_stats": {
                    "gainers_scanned": scan_stats.get('gainers_scanned', '—') if scan_stats else '—',
                    "market_status": scan_stats.get('market_status', 'UNKNOWN') if scan_stats else 'UNKNOWN',
                    "market_time": scan_stats.get('market_time', '') if scan_stats else '',
                    "market": scan_stats.get('market', 'us') if scan_stats else 'us'
                }
            }
            self.scan_results_file.write_text(json.dumps(data, indent=2))
            logger.info("Wrote scan results to %s", self.scan_results_file)

            self._update_html(scan_results, active_plan, scan_stats)
            self._git_push()
            return True
        except Exception as e:
            logger.error("Website update failed: %s", e)
            return False

    def _update_html(self, scan_results: list, active_plan: dict = None, scan_stats: dict = None):
        """Replace content using simple string markers. Only updates static sections; trade plan / tracker / news are rendered client-side from ozmoeg-latest.json."""
        if not self.html_file.exists():
            logger.warning("HTML file not found: %s", self.html_file)
            return

        html = self.html_file.read_text(encoding='utf-8')
        alert_results = [r for r in scan_results if r.get('status') == 'ALERT']
        total_candidates = len(scan_results)
        alert_count = len(alert_results)
        scan_stats = scan_stats or {}
        gainers_scanned = scan_stats.get('gainers_scanned', '—')
        market_status = scan_stats.get('market_status', 'UNKNOWN')
        market_time = scan_stats.get('market_time', '')
        market = str(scan_stats.get('market', 'us')).lower()
        is_au = market == 'au'

        def replace_between(html: str, start_marker: str, end_marker: str, new_content: str) -> str:
            """Replace content between start_marker and end_marker with new_content."""
            s = html.find(start_marker)
            e = html.find(end_marker)
            if s >= 0 and e >= 0:
                before = html[:s + len(start_marker)]
                after = html[e:]
                return before + '\n' + new_content + '\n                    ' + after
            return html

        # Update badge
        status_emoji = {"OPEN": "🟢", "PRE-MARKET": "🟡", "AFTER-HOURS": "🟡", "WEEKEND": "🔴", "CLOSED": "🔴"}.get(market_status, "⚪")
        market_label = 'AUS' if is_au else 'US'
        badge_text = f'{status_emoji} {market_label} {market_status} {market_time} | Scanned: {gainers_scanned} | {total_candidates} candidates | {alert_count} alerts'
        html = replace_between(html, '<!-- SCANNER_BADGE -->', '<!-- END_SCANNER_BADGE -->', badge_text)

        # Update table body
        table_rows = []
        for result in scan_results:
            ticker = result.get('ticker', '')
            name = result.get('name', '')
            status = result.get('status', 'PENDING')
            result_text = result.get('result', '')
            if status == 'ALERT':
                status_class = 'result-alert'
                emoji = "🚨"
            elif status == 'CANDIDATE':
                status_class = 'result-candidate'
                emoji = "🔬"
            else:
                status_class = 'result-skip'
                emoji = "⏭️"
            escaped = (result_text or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            table_rows.append(f'''                            <tr>
                                <td class="ticker-cell">{ticker}</td>
                                <td>{name}</td>
                                <td><span class="{status_class}">{emoji} {status}</span></td>
                                <td>{escaped}</td>
                            </tr>''')

        if not table_rows:
            table_rows = ['                            <tr><td colspan="4" style="text-align: center; color: var(--text-secondary);">No candidates met the full alert criteria in this scan</td></tr>']

        tbody_content = '\n'.join(table_rows)
        html = replace_between(html, '<!-- SCANNER_TABLE_BODY -->', '<!-- END_SCANNER_TABLE_BODY -->', tbody_content)

        # Build "All Scanned Tickers" table (collapsed by default) with reason each was skipped
        all_gainers = scan_stats.get('all_gainers', [])
        scanned_rows = []
        for stock in all_gainers:
            t = stock.get('ticker', stock)
            v = stock.get('values', {})
            symbol = t.get('symbol', '') if isinstance(t, dict) else (stock if isinstance(stock, str) else '')
            name = t.get('name', symbol) if isinstance(t, dict) else symbol
            price = float(v.get('price', 0) or (t.get('pprice', 0) if isinstance(t, dict) else 0) or (t.get('close', 0) if isinstance(t, dict) else 0) or 0)
            close = float(t.get('close', 0) or 0) if isinstance(t, dict) else 0
            pre_close = float(t.get('preClose', 0) or 0) if isinstance(t, dict) else 0
            change_ratio = float(t.get('changeRatio', 0) or 0) if isinstance(t, dict) else 0
            if is_au and pre_close > 0:
                change_pct = (close - pre_close) / pre_close * 100
            elif close > 0 and price > 0:
                change_pct = (price - close) / close * 100
            else:
                change_pct = (change_ratio - 1) * 100 if change_ratio > 1 else (change_ratio * 100)
            volume = int(t.get('volume', 0) or 0) if isinstance(t, dict) else 0
            market_cap = float(t.get('marketValue', 0) or 0) if isinstance(t, dict) else 0
            rvol = float(t.get('rvol') or 0) if isinstance(t, dict) else 0
            reason = stock.get('_scan_reason', 'Unknown')
            passed = stock.get('_scan_passed', False)
            status_badge = 'PASS' if passed else 'SKIP'
            badge_class = 'scan-pass' if passed else 'scan-skip'
            price_decimals = 3 if is_au else 2
            scanned_rows.append(f'''                            <tr>
                                <td class="ticker-cell">{symbol}</td>
                                <td>{name}</td>
                                <td>${price:.{price_decimals}f}</td>
                                <td>{change_pct:+.1f}%</td>
                                <td>{volume:,}</td>
                                <td>{rvol:.1f}x</td>
                                <td>${market_cap/1e6:.1f}M</td>
                                <td><span class="{badge_class}">{status_badge}</span></td>
                                <td>{reason}</td>
                            </tr>''')

        if scanned_rows:
            scanned_table = (
                '                        <details class="scanned-details">\n'
                '                            <summary>🔍 Show all 50 scanned tickers with filter reasons</summary>\n'
                '                            <div class="table-wrap">\n'
                '                                <table class="scanned-table">\n'
                '                                    <thead>\n'
                '                                        <tr>\n'
                '                                            <th>Ticker</th><th>Name</th><th>Price</th><th>Change</th><th>Volume</th><th>RVOL</th><th>Mkt Cap</th><th>Filter</th><th>Reason</th>\n'
                '                                        </tr>\n'
                '                                    </thead>\n'
                '                                    <tbody>\n'
                + '\n'.join(scanned_rows) +
                '\n                                    </tbody>\n'
                '                                </table>\n'
                '                            </div>\n'
                '                        </details>'
            )
        else:
            scanned_table = ''
        html = replace_between(html, '<!-- SCANNED_GAINERS_TABLE -->', '<!-- END_SCANNED_GAINERS_TABLE -->', scanned_table)

        # Update news ticker
        news_items = []
        for result in scan_results:
            ticker = result.get('ticker', '')
            name = result.get('name', '')
            status = result.get('status', 'SKIP')
            result_text = result.get('result', '')
            time_str = result.get('time', datetime.now().strftime('%I:%M %p'))
            date_str = result.get('date', '')
            date_html = f'<span class="date">{date_str}</span> ' if date_str else ''
            news_items.append(f'''                        <div class="news-item {status.lower()}">
                            <span class="score">{status}</span>
                            {date_html}<span class="time">{time_str}</span> — {ticker} ({name}) — {result_text}
                        </div>''')

        if not news_items:
            news_items = ['                        <div class="news-item skip"><span class="score">INFO</span><span class="time">Now</span> — No candidates passed filter criteria — Scan continues every 15 min</div>']

        news_content = '\n'.join(news_items)
        looped_content = news_content + '\n' + news_content
        html = replace_between(html, '<!-- NEWS_TICKER_ITEMS -->', '<!-- END_NEWS_TICKER_ITEMS -->', looped_content)

        # NOTE: We no longer replace the trade plan / performance tracker / catalyst-news HTML.
        # Those sections are dynamic and rendered client-side from ozmoeg-latest.json by loadLiveData().

        self.html_file.write_text(html, encoding='utf-8')
        logger.info("Updated HTML file with %d results", len(scan_results))

    def _git_push(self):
        try:
            repo = str(self.repo_path)
            subprocess.run(['git', '-C', repo, 'add', '-A'], check=False, capture_output=True)
            subprocess.run(
                ['git', '-C', repo, 'commit', '-m', f'Update OzMoEg scan results — {datetime.now().strftime("%Y-%m-%d %H:%M")}'],
                check=False, capture_output=True
            )
            subprocess.run(['git', '-C', repo, 'push'], check=False, capture_output=True)
            logger.info("Pushed website updates to GitHub")
        except Exception as e:
            logger.warning("Git push failed (non-critical): %s", e)
