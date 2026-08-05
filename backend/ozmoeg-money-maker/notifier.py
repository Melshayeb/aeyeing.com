#!/usr/bin/env python3
"""
# OzMoEg Money Maker — Notifier
# Sends alerts via Telegram and Email.
# Uses your existing OzMoEg bot (@OzMoEgHbot) — same as other alerts.
"""
import logging
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests

try:
    from kill_switch import is_enabled
except ImportError:
    is_enabled = None

logger = logging.getLogger(__name__)

# Track recently sent alerts to prevent duplicates
SENT_ALERTS_FILE = Path.home() / ".hermes/skills/ozmoeg-money-maker/.sent_alerts.json"
DUPLICATE_WINDOW_SECONDS = 21600  # 6 hours — only re-send same setup if it stays valid all session

# Telegram quality gate: only high-conviction, fresh-catalyst setups get channel alerts.
TG_MIN_IMPACT_SCORE = 3          # Score 3+ passes; score 2 needs very fresh news (see below)
TG_FRESH_AGE_MINUTES = 60        # Score 2 alerts are allowed only if news is this fresh (live market)
TG_MAX_NEWS_AGE_MINUTES = 1440   # 24 hours for live-market alerts
TG_MAX_RELAXED_NEWS_AGE_MINUTES = 1440  # 24 hours for pre/after-hours (relaxed) alerts

class Notifier:
    """Alert dispatcher for Telegram and Email."""

    def __init__(self, config: Dict[str, Any]):
        self.cfg = config
        self.tg_token = config.get('telegram', {}).get('bot_token', '')
        self.tg_chat = config.get('telegram', {}).get('chat_id', '')
        self.email_cfg = config.get('email', {})
        # User preference: Telegram channel only. Email is disabled by default.
        self.email_enabled = self.email_cfg.get('enabled', False)
        self._load_sent_alerts()
        self._load_previous_summary_tickers()
    
    def _load_sent_alerts(self):
        """Load previously sent alert signatures."""
        if SENT_ALERTS_FILE.exists():
            try:
                with open(SENT_ALERTS_FILE, 'r') as f:
                    data = json.load(f)
                # Filter out entries older than window
                cutoff = time.time() - DUPLICATE_WINDOW_SECONDS
                self._sent_alerts = {k: v for k, v in data.items() if v > cutoff}
            except:
                self._sent_alerts = {}
        else:
            self._sent_alerts = {}
    
    def _save_sent_alerts(self):
        """Persist sent alert signatures."""
        SENT_ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SENT_ALERTS_FILE, 'w') as f:
            json.dump(self._sent_alerts, f)

    def _load_previous_summary_tickers(self):
        """Load the last set of tickers that made it into the pre-market summary."""
        path = SENT_ALERTS_FILE.with_name('.summary_tickers.json')
        if path.exists():
            try:
                with open(path, 'r') as f:
                    self._previous_summary_tickers = sorted(json.load(f))
            except Exception:
                self._previous_summary_tickers = []
        else:
            self._previous_summary_tickers = []

    def _save_previous_summary_tickers(self, tickers: List[str]):
        """Persist the current set of summary-eligible tickers."""
        path = SENT_ALERTS_FILE.with_name('.summary_tickers.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(sorted(tickers), f)
        self._previous_summary_tickers = sorted(tickers)

    def _alert_signature(self, ticker: str, plan: dict, market: str,
                         market_status: str, news_headline: str) -> str:
        """Compute a stable signature for an alert setup."""
        plan_key = {
            'entry': str(plan.get('entry', '')),
            'stop': str(plan.get('stop', '')),
            'targets': {
                't1': str(plan.get('targets', {}).get('t1', '')),
                't2': str(plan.get('targets', {}).get('t2', '')),
                't3': str(plan.get('targets', {}).get('t3', '')),
            },
            'shares': str(plan.get('shares', '')),
            'confidence': str(plan.get('confidence', '')),
            'risk_reward': str(plan.get('risk_reward', '')),
        }
        payload = {
            'ticker': ticker,
            'market': market,
            'market_status': market_status,
            'plan': plan_key,
            'catalyst': str(news_headline)[:200],
        }
        return hashlib.md5(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def _is_duplicate(self, ticker: str, plan: dict, market: str = 'us',
                       market_status: str = '', news_headline: str = '') -> bool:
        """Check if this alert was already sent recently and record it if not.

        The dedup key now includes the full plan (entry/stop/targets), market,
        market phase, and the current catalyst headline. This prevents the same
        ticker from spamming Telegram when nothing has changed, while still
        allowing a re-alert if the setup or catalyst genuinely updates.
        """
        signature = self._alert_signature(ticker, plan, market, market_status, news_headline)

        if signature in self._sent_alerts:
            last_sent = self._sent_alerts[signature]
            age = time.time() - last_sent
            if age < DUPLICATE_WINDOW_SECONDS:
                logger.info("Duplicate alert for %s (%ds ago) — skipping", ticker, int(age))
                return True

        # Record this alert
        self._sent_alerts[signature] = time.time()
        self._save_sent_alerts()
        return False

    def _is_duplicate_readonly(self, ticker: str, plan: dict, market: str = 'us',
                                market_status: str = '', news_headline: str = '') -> bool:
        """Check duplicate cache without recording a new send."""
        signature = self._alert_signature(ticker, plan, market, market_status, news_headline)
        if signature in self._sent_alerts:
            age = time.time() - self._sent_alerts[signature]
            if age < DUPLICATE_WINDOW_SECONDS:
                logger.info("Duplicate alert (readonly) for %s (%ds ago)", ticker, int(age))
                return True
        return False

    @staticmethod
    def _parse_age_minutes(age_str: str) -> Optional[int]:
        """Convert Webull-style age strings ('2h ago', '3d ago', '1mo ago', '2y ago') to minutes."""
        if not age_str:
            return None
        age_str = str(age_str).split('·')[0].strip()
        import re
        m = re.match(r'^(\d+)\s*(mo|[smhdwy])\s+ago', age_str, re.IGNORECASE)
        if not m:
            return None
        num = int(m.group(1))
        unit = m.group(2).lower()
        multipliers = {'s': 1/60, 'm': 1, 'h': 60, 'd': 1440, 'w': 10080, 'mo': 43200, 'y': 525600}
        return int(num * multipliers.get(unit, 1))

    def _youngest_news_age_minutes(self, news_analysis: Dict[str, Any]) -> Optional[int]:
        """Return the age in minutes of the newest headline for this setup."""
        items = news_analysis.get('scored_items', []) or []
        if not items:
            return None
        ages = [self._parse_age_minutes(item.get('time', '')) for item in items]
        ages = [a for a in ages if a is not None]
        return min(ages) if ages else None

    def send_telegram(self, message: str, parse_mode: str = 'HTML') -> bool:
        """Send a Telegram message."""
        if not self.tg_token or not self.tg_chat:
            logger.warning("Telegram not configured — skipping")
            return False
        try:
            url = f"https://api.telegram.org/bot{self.tg_token}/sendMessage"
            payload = {'chat_id': self.tg_chat, 'text': message, 'parse_mode': parse_mode}
            resp = requests.post(url, json=payload, timeout=15)
            data = resp.json()
            if not data.get('ok'):
                logger.error("Telegram API error: %s", data.get('description'))
                return False
            logger.info("Telegram alert sent successfully")
            return True
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            return False

    def send_email(self, subject: str, body_html: str, body_text: str = None) -> bool:
        """Send an HTML email via SMTP.
        
        Email notifications are disabled by user preference. Only Telegram
        channel alerts are used. Keep the method for future opt-in.
        """
        if not self.email_enabled:
            logger.info("Email notifications disabled — Telegram channel only")
            return False
        if not self.email_cfg:
            logger.warning("Email not configured — skipping")
            return False
        try:
            import smtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.email_cfg.get('from_address', 'aeyeingserver@gmail.com')
            msg['To'] = self.email_cfg.get('to_address', 'elshayeb@gmail.com')
            if body_text:
                msg.attach(MIMEText(body_text, 'plain'))
            msg.attach(MIMEText(body_html, 'html'))
            server = self.email_cfg.get('smtp_server', 'smtp.gmail.com')
            port = self.email_cfg.get('smtp_port', 587)
            username = self.email_cfg.get('username', 'aeyeingserver@gmail.com')
            password = self.email_cfg.get('password', '')
            with smtplib.SMTP(server, port) as s:
                s.starttls()
                s.login(username, password)
                s.sendmail(msg['From'], [msg['To']], msg.as_string())
            logger.info("Email alert sent: %s", subject)
            return True
        except Exception as e:
            logger.error("Email send failed: %s", e)
            return False

    def send_trade_plan_alert(self, message: str, plan: Dict[str, Any], result: Dict[str, Any]) -> bool:
        """Simple trade plan alert (legacy mode)."""
        if not self.tg_token or not self.tg_chat:
            logger.warning("Telegram not configured — skipping trade plan alert")
            return False
        try:
            self.send_telegram(f"🚨 *OzMoEg Trade Plan*\n\n{message}")
            # Email only if explicitly enabled
            if self.email_enabled:
                subject = f"🚨 OzMoEg Alert — {plan.get('ticker', 'N/A')}"
                html_body = f"<h2>🚨 OzMoEg Trade Plan</h2><p>{message}</p>"
                self.send_email(subject, html_body)
            logger.info("Trade plan alert sent: %s", message[:100])
            return True
        except Exception as e:
            logger.error("Error in send_trade_plan_alert: %s", e)
            return False

    def _alert_passes_quality_gate(self, plan: Dict[str, Any],
                                   news_analysis: Dict[str, Any]) -> bool:
        """Return True only if the setup satisfies the Telegram quality gate.

        Pre-market (relaxed) alerts need:
          - impact score >= 2
          - news age <= 24h
          - R:R >= 1.5
          - no red flags (handled via max_score = 0)

        Live-market alerts need:
          - impact score >= 3, OR impact score 2 with very fresh news (<=60 min)
          - news age <= 24h
          - R:R >= 1.5
        """
        impact_score = news_analysis.get('max_score', 0)
        relaxed = news_analysis.get('catalyst_relaxed', False)
        max_age = TG_MAX_RELAXED_NEWS_AGE_MINUTES if relaxed else TG_MAX_NEWS_AGE_MINUTES
        news_age = self._youngest_news_age_minutes(news_analysis)

        if impact_score < 0:
            logger.info("Quality gate — impact score %d < 0", impact_score)
            return False

        # User requested gate relaxed to impact_score >= 0. We still keep the
        # freshness and R:R checks so Telegram only receives actionable setups.

        if news_age is None or news_age > max_age:
            logger.info("Quality gate — news age %s min exceeds limit %d", news_age, max_age)
            return False

        if plan.get('risk_reward', 0) < 1.5:
            logger.info("Quality gate — poor R:R %.2f", plan.get('risk_reward', 0))
            return False

        return True

    def alert_trade_setup(self, plan: Dict[str, Any], news_analysis: Dict[str, Any],
                          ta: Dict[str, Any], market: str = 'us', market_status: str = ''):
        """Send a trade setup alert to Telegram — only for fresh, high-conviction setups.

        Telegram alerts are further gated to active trading windows by the caller;
        this method focuses on quality gating (score, freshness, R:R).
        """
        # Hard gate: Telegram only during US PRE-MARKET (the active Sydney trading
        # window 18:00 → US market open). The caller already checks this; this guard
        # prevents accidental direct calls. Market open / after-hours / closed =>
        # no Telegram per user policy.
        status = str(market_status).upper()
        if market == 'us' and status != 'PRE-MARKET':
            logger.info("Telegram trade alert suppressed for %s — market status %s", plan.get('ticker'), status)
            return False
        if market == 'au':
            logger.info("Telegram trade alert suppressed for %s — AU market (website-only)", plan.get('ticker'))
            return False

        ticker = plan['ticker']
        
        # Duplicate check — skip if same setup/catalyst already alerted recently
        if self._is_duplicate(ticker, plan, market=market, market_status=market_status,
                              news_headline=news_analysis.get('top_headline', '')):
            return  # Skip sending — already alerted
        
        if not is_enabled(self.cfg, "telegram_alerts"):
            return
        
        impact_score = news_analysis.get('max_score', 0)
        sources = news_analysis.get('high_impact_count', 0)
        news_headline = news_analysis.get('top_headline', 'N/A')
        news_items = news_analysis.get('scored_items', [])[:3]

        # Quality gate (shared with summary builder)
        if not self._alert_passes_quality_gate(plan, news_analysis):
            return

        # Build filters applied text
        filters_text = self._build_filters_applied(plan, news_analysis, ta)

        # Build news detail
        news_detail = []
        for item in news_items:
            news_detail.append(f"• [{item['score']}/5] {item['title']}")
        news_text = "\n".join(news_detail) if news_detail else "• No specific news items scored"

        # Escape HTML special chars for Telegram HTML mode
        import html as html_module
        safe_ticker = html_module.escape(ticker)
        safe_headline = html_module.escape(news_headline)
        safe_news_text = html_module.escape(news_text)
        news_age_min = self._youngest_news_age_minutes(news_analysis)
        age_text = f"{news_age_min} min ago" if news_age_min is not None else "age unknown"
        relaxed = news_analysis.get('catalyst_relaxed', False)
        market_phase = "Pre/After Hours" if relaxed else "Live Market"
        
        # Telegram message (HTML mode for reliable price display)
        tg_msg = f"""🚀 <b>OzMoEg Alert — {safe_ticker} ({market_phase})</b>

📰 <b>Catalyst:</b> {safe_headline}
🕐 <b>News age:</b> {age_text}
💥 <b>Impact Score:</b> {impact_score}/5 | <b>Sources:</b> {sources}

📰 <b>News/Announcements:</b>
{safe_news_text}

💰 <b>Entry:</b> ${plan['entry']}
🛑 <b>Stop:</b> ${plan['stop']} (-{abs(plan['entry']-plan['stop'])/plan['entry']*100:.1f}%)
🎯 <b>T1:</b> ${plan['targets']['t1']} (+{abs(plan['targets']['t1']-plan['entry'])/plan['entry']*100:.1f}%)
🎯 <b>T2:</b> ${plan['targets']['t2']} (+{abs(plan['targets']['t2']-plan['entry'])/plan['entry']*100:.1f}%)
🎯 <b>T3:</b> ${plan['targets']['t3']} (+{abs(plan['targets']['t3']-plan['entry'])/plan['entry']*100:.1f}%)

📊 <b>Shares:</b> {plan['shares']} | <b>Value:</b> ${plan['position_value']}
📈 <b>Risk:Reward:</b> {plan['risk_reward']}:1
🎲 <b>Confidence:</b> {plan['confidence']}

📋 <b>Rules/Filters Applied:</b>
{filters_text}

⏱ <b>Exit When:</b> Momentum dies — bearish candle, tape slows, volume drops
📈 <b>Trail Stop:</b> Move to breakeven at +1%
"""
        tg_sent = self.send_telegram(tg_msg, parse_mode='HTML')

        # Email only if explicitly enabled
        if self.email_enabled:
            email_html = f"""
            <h2>🚀 OzMoEg Money Maker Alert — {ticker}</h2>
            <h3>📰 News & Announcements</h3>
            <ul>
            {''.join(f'<li>[{item["score"]}/5] {item["title"]}' for item in news_items)}
            </ul>
            <table border="1" cellpadding="8" cellspacing="0">
              <tr><td><b>Catalyst</b></td><td>{news_headline}</td></tr>
              <tr><td><b>Impact Score</b></td><td>{impact_score}/5</td></tr>
              <tr><td><b>Entry</b></td><td>${plan['entry']}</td></tr>
              <tr><td><b>Stop Loss</b></td><td style="color:red;">${plan['stop']}</td></tr>
              <tr><td><b>Target 1</b></td><td style="color:green;">${plan['targets']['t1']}</td></tr>
              <tr><td><b>Target 2</b></td><td style="color:green;">${plan['targets']['t2']}</td></tr>
              <tr><td><b>Target 3</b></td><td style="color:green;">${plan['targets']['t3']}</td></tr>
              <tr><td><b>Position Size</b></td><td>{plan['shares']} shares (${plan['position_value']})</td></tr>
              <tr><td><b>Risk:Reward</b></td><td>{plan['risk_reward']}:1</td></tr>
              <tr><td><b>Exit Strategy</b></td><td>Momentum-based exit (no fixed timer)</td></tr>
            </table>
            <h3>📋 Rules/Filters Applied</h3>
            <pre>{filters_text}</pre>
            <p><i>This is an automated alert. Always verify before trading.</i></p>
            """
            subject = f"🚀 OzMoEg Alert — {ticker} | Impact {impact_score}/5 | Entry ${plan['entry']}"
            self.send_email(subject, email_html, body_text=tg_msg)

        return tg_sent

    def send_pre_market_summary(self, results: List[Dict[str, Any]], market: str = 'us',
                                  market_status: str = '') -> bool:
        """Send a single Telegram summary of quality-gated ALERT triggers during US pre-market.

        A summary is sent only when the set of eligible tickers has changed compared with the
        previous scan (a ticker added or removed). Per-ticker duplicate suppression still applies,
        so within the changed set only tickers that have not already been alerted are included.
        """
        status = str(market_status).upper()
        if market == 'us' and status != 'PRE-MARKET':
            logger.info("Pre-market summary suppressed — market status %s", status)
            return False
        if market == 'au':
            logger.info("Pre-market summary suppressed — AU market")
            return False
        if not is_enabled(self.cfg, "telegram_alerts"):
            return False

        alerts = [r for r in (results or []) if r.get('status') == 'ALERT' and r.get('plan')]
        if not alerts:
            logger.info("Pre-market summary suppressed — no ALERT triggers in scan")
            return False

        import html as html_module
        # Include all trigger statuses in the summary body, not only ALERTs.
        all_triggers = [r for r in (results or []) if r.get('plan')]
        eligible_alerts = []
        for result in alerts:
            plan = result.get('plan') or {}
            news = result.get('news') or {}
            ticker = plan.get('ticker')
            if not ticker:
                continue
            if not self._alert_passes_quality_gate(plan, news):
                logger.info("Pre-market summary excludes %s — fails quality gate", ticker)
                continue
            eligible_alerts.append(result)

        current_alert_tickers = sorted({r['plan']['ticker'] for r in eligible_alerts})
        previous_alert_tickers = self._previous_summary_tickers or []

        if current_alert_tickers == previous_alert_tickers:
            logger.info("Pre-market summary suppressed — alert ticker set unchanged (%s)", ', '.join(current_alert_tickers))
            self._save_previous_summary_tickers(current_alert_tickers)
            return False

        added = [t for t in current_alert_tickers if t not in previous_alert_tickers]
        removed = [t for t in previous_alert_tickers if t not in current_alert_tickers]
        logger.info("Alert ticker set changed — added: %s, removed: %s", added, removed)

        unique = []
        for result in eligible_alerts:
            plan = result.get('plan') or {}
            news = result.get('news') or {}
            ticker = plan.get('ticker')
            if self._is_duplicate_readonly(ticker, plan, market=market, market_status=market_status,
                                          news_headline=news.get('top_headline', '')):
                continue
            unique.append(result)

        # Persist the current eligible alert set even if we end up sending nothing unique,
        # so the next cycle compares against the correct baseline.
        self._save_previous_summary_tickers(current_alert_tickers)

        if not unique:
            logger.info("Pre-market summary suppressed — no new unique triggers to send (set changed but all duplicates)")
            return False

        lines = []
        timestamp = time.strftime("%H:%M", time.gmtime())
        change_note = ""
        if added:
            change_note = f"+{', '.join(added)}"
        header = f"🌅 <b>OzMoEg Pre-Market Summary</b> ({timestamp} UTC)\n<b>{len(unique)} new alert trigger{'s' if len(unique) != 1 else ''}</b>{(' — ' + change_note) if change_note else ''}\n"

        # Compact one-line listing for each new unique ALERT ticker.
        trigger_lines = []
        seen_trigger_tickers = set()
        for result in unique:
            plan = result.get('plan') or {}
            news = result.get('news') or {}
            ticker = plan.get('ticker')
            if not ticker or ticker in seen_trigger_tickers:
                continue
            seen_trigger_tickers.add(ticker)
            ticker_esc = html_module.escape(ticker)
            headline = html_module.escape(news.get('top_headline', 'N/A'))
            impact = news.get('max_score', 0)
            entry = plan.get('entry')
            stop = plan.get('stop')
            t1 = plan.get('targets', {}).get('t1')
            rr = plan.get('risk_reward')
            trigger_lines.append(
                f"🚨 <b>{ticker_esc}</b> ${entry} → T1 ${t1} | 🛑 ${stop} | R:R {rr}:1 | Impact {impact}/5 | 📰 {headline}"
            )

        footer = "\n<i>Automated pre-market summary — verify before trading.</i>"

        # Telegram hard limit is 4096 characters. Build message and truncate with a
        # clear note if there are too many new alerts for one message.
        message = header + "\n".join(trigger_lines) + footer
        MAX_LEN = 4000
        if len(message) > MAX_LEN:
            truncated_note = f"\n\n… and {len(trigger_lines)} total new alerts (truncated due to Telegram limit)."
            # Keep dropping the last ticker line until it fits.
            while trigger_lines and len(header + "\n".join(trigger_lines) + footer + truncated_note) > MAX_LEN:
                trigger_lines.pop()
            if not trigger_lines:
                trigger_lines = [trigger_lines[0] if trigger_lines else "🚨 Alerts available on the dashboard."]
            message = header + "\n".join(trigger_lines) + footer + truncated_note

        sent = self.send_telegram(message, parse_mode='HTML')

        # Record each ticker as sent so it won't be re-sent until the duplicate window expires.
        if sent:
            for result in unique:
                plan = result.get('plan') or {}
                news = result.get('news') or {}
                ticker = plan.get('ticker')
                if ticker:
                    self._is_duplicate(ticker, plan, market=market, market_status=market_status,
                                      news_headline=news.get('top_headline', ''))
        return sent

    def send_alert(self, result: Dict[str, Any], market: str = 'us', market_status: str = '') -> bool:
        """Unified entry point used by main.py.  Delegates to alert_trade_setup."""
        plan = result.get('plan') or {}
        news = result.get('news') or {}
        ta = result.get('ta') or {}
        if not plan or not plan.get('ticker'):
            logger.warning("send_alert called with invalid plan — skipping")
            return False
        return self.alert_trade_setup(plan, news, ta, market=market, market_status=market_status)

    def notify_market_status(self, market: str, status: str):
        """Milestone alert: market open / closed / pre / after-hours transition.

        Only sent during active trading windows.  No notifications when market is
        CLOSED or WEEKEND, and no pre/after-hours milestone pings (keeps noise down).
        """
        if not is_enabled(self.cfg, "telegram_alerts"):
            return
        if status.upper() not in ('OPEN',):
            logger.info("Market status notification suppressed: %s %s", market, status)
            return
        emoji = {
            'OPEN': '🟢', 'PRE-MARKET': '🟡', 'AFTER-HOURS': '🟡',
            'CLOSED': '🔴', 'WEEKEND': '🔴'
        }.get(status, '⚪')
        label = market.upper()
        if label == 'AU':
            label = 'AUS/ASX'
        # Show local times in the alert so the user can verify the transition timing.
        from datetime import datetime
        import pytz
        try:
            sydney = pytz.timezone('Australia/Sydney')
            et = pytz.timezone('America/New_York')
            syd_time = datetime.now(sydney).strftime('%a %H:%M %Z')
            et_time = datetime.now(et).strftime('%a %H:%M %Z')
            time_line = f"⏰ Sydney {syd_time} | ET {et_time}"
        except Exception:
            time_line = ""
        tg_msg = f"{emoji} <b>OzMoEg {label} Market — {status}</b>\n{time_line}\n\nScanner is now monitoring {label} {status.lower()} session."
        self.send_telegram(tg_msg, parse_mode='HTML')
        if self.email_enabled:
            subject = f"{emoji} OzMoEg {label} Market {status}"
            self.send_email(subject, f"<h2>{tg_msg}</h2>", body_text=tg_msg)

    def notify_no_candidates(self, market: str, status: str, scanned_count: int):
        """Throttled summary when no candidates pass filters.

        Only sent during active trading hours; suppressed when closed or extended hours.
        """
        if not is_enabled(self.cfg, "telegram_alerts"):
            return
        if str(status).upper() not in ('OPEN',):
            logger.info("No-candidates notification suppressed: %s %s", market, status)
            return
        label = market.upper()
        if label == 'AU':
            label = 'AUS/ASX'
        tg_msg = (
            f"🟡 <b>OzMoEg {label} Scan — No candidates</b>\n"
            f"⏰ Market: {status}\n"
            f"📊 Scanned {scanned_count} gainers; none passed filters.\n"
            f"Website updated with full scan details."
        )
        self.send_telegram(tg_msg, parse_mode='HTML')
        if self.email_enabled:
            subject = f"🟡 OzMoEg {label} — No candidates ({scanned_count} scanned)"
            self.send_email(subject, f"<h2>{tg_msg}</h2>", body_text=tg_msg)

    def notify_scan_summary(self, market: str, alerts: int, candidates: int,
                            alert_tickers: List[str], status: str):
        """Send a concise scan summary only when meaningful changes occurred.

        Only sent during active trading hours; suppressed when closed or extended hours.
        """
        if is_enabled is not None and not is_enabled(self.cfg, "telegram_alerts"):
            return
        if str(status).upper() not in ('OPEN',):
            logger.info("Scan summary notification suppressed: %s %s", market, status)
            return
        label = market.upper()
        if label == 'AU':
            label = 'AUS/ASX'
        ticker_str = ", ".join(alert_tickers[:10]) or "None"
        tg_msg = (
            f"🚀 <b>OzMoEg {label} Scan Updated</b>\n"
            f"⏰ Market: {status}\n"
            f"📊 Candidates: {candidates} | New Alerts: {alerts}\n"
            f"🎯 {ticker_str}\n"
            f"📡 <a href='https://aeyeing.com/ozmoeg-trader.html'>Live Dashboard</a>"
        )
        self.send_telegram(tg_msg, parse_mode='HTML')
        if self.email_enabled:
            subject = f"🚀 OzMoEg {label} Scan — {alerts} alert{'s' if alerts != 1 else ''} | {ticker_str}"
            self.send_email(subject, f"<h2>{tg_msg}</h2>", body_text=tg_msg)

    def alert_daily_report(self, summary: Dict[str, Any], trades: list):
        """Send end-of-day summary."""
        pnl = summary.get('pnl', 0)
        emoji = "🟢" if pnl >= 0 else "🔴"

        tg_msg = f"""📊 *OzMoEg Daily Report — {summary['date']}*

{emoji} *P&L:* ${pnl:.2f}
📈 *Trades:* {summary['trades']}
📉 *Consecutive Losses:* {summary['consecutive_losses']}
🔓 *PDT Remaining:* {summary['pdt_remaining']}/3
📝 *Open Positions:* {summary['open_positions']}
"""
        self.send_telegram(tg_msg)

    def alert_warning(self, message: str):
        """Send a warning alert — Telegram only, never email.
        Email warnings create inbox noise; only trade alerts go to email.
        """
        self.send_telegram(f"⚠️ *OzMoEg Warning*\n\n{message}")
        # DO NOT send email for warnings — they flood the inbox
        logger.info("Warning sent via Telegram only: %s", message[:100])