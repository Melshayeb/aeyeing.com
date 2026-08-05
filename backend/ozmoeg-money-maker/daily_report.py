#!/usr/bin/env python3
"""
OzMoEg Money Maker — Daily Report
Generates a daily summary: P&L, trades executed, open positions.
Sends via Telegram and Email automatically (if enabled).
"""
import logging
import sys
from pathlib import Path

skill_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(skill_dir))

from kill_switch import load_config, is_enabled, component_enabled
from notifier import Notifier
from risk_manager import RiskManager

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


def main():
    logger.info("=== OzMoEg Money Maker Daily Report Starting ===")

    config = load_config()

    if not is_enabled(config, "master"):
        logger.info("Master kill switch is OFF. Skipping daily report.")
        print("\n⚠️ Daily report skipped: master kill switch is OFF")
        return 0

    if not component_enabled(config, "telegram_alerts"):
        logger.info("Telegram alerts disabled by kill switch — daily report will not be sent.")
        print("\n⚠️ Telegram alerts disabled — daily report will not be sent.")
        return 0

    risk = RiskManager(config.get('strategy', {}))
    summary = risk.daily_summary()
    open_positions = risk.get_open_positions()

    notifier = Notifier(config)
    notifier.alert_daily_report(summary, open_positions)

    if notifier.email_enabled:
        pnl = summary.get('pnl', 0)
        emoji = "🟢" if pnl >= 0 else "🔴"
        body_html = f"""
        <h2>📊 OzMoEg Daily Report — {summary['date']}</h2>
        <p>{emoji} <b>P&L:</b> ${pnl:.2f}</p>
        <p>📈 <b>Trades:</b> {summary['trades']}</p>
        <p>📉 <b>Consecutive Losses:</b> {summary['consecutive_losses']}</p>
        <p>🔓 <b>PDT Remaining:</b> {summary['pdt_remaining']}/3</p>
        <p>📝 <b>Open Positions:</b> {summary['open_positions']}</p>
        """
        subject = f"OzMoEg Money Maker — Daily Report {summary['date']}"
        notifier.send_email(subject, body_html, body_text=f"""
OzMoEg Daily Report — {summary['date']}

{emoji} P&L: ${pnl:.2f}
📈 Trades: {summary['trades']}
📉 Consecutive Losses: {summary['consecutive_losses']}
🔓 PDT Remaining: {summary['pdt_remaining']}/3
📝 Open Positions: {summary['open_positions']}
""")

    logger.info("=== OzMoEg Money Maker Daily Report Completed ===")
    print("\n=== DAILY REPORT SENT ===")
    print(f"🟢 P&L: ${summary['pnl']:.2f}")
    print(f"📈 Trades: {summary['trades']}")
    print(f"📉 Consecutive Losses: {summary['consecutive_losses']}")
    print(f"🔓 PDT Remaining: {summary['pdt_remaining']}/3")
    print(f"📝 Open Positions: {summary['open_positions']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
