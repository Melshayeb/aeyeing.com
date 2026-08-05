# OzMoEg Money Maker - Small Cap Scalp Trading Bot

Automated micro-scalp trading system for US small-cap stocks (market cap $300M–2B). Monitors news feeds, identifies momentum catalysts, and generates actionable buy/sell plans using supply/demand zone + candlestick confirmation strategies.

## Overview

This skill provides a complete automated trading system that scans for small-cap stocks, analyzes news and technical indicators, plans trades with strict risk management, and sends alerts via Telegram. It includes kill switches and easy removal mechanisms.

## Core Features

- **Scanner**: Fetches top gainers, filters by market cap, price, volume, RVOL, float ratios
- **News Monitor**: Analyzes catalysts with 1-5 impact scoring
- **Technical Analyzer**: Identifies demand zones, candlestick patterns, ATR stops
- **Trade Planner**: Generates entry/exit plans with Ahmed Khaled CMT position sizing
- **Risk Manager**: Implements PDT rules, position sizing, daily loss limits
- **Notifier**: Sends Telegram alerts (email disabled by default)
- **Website Dashboard**: Live monitoring with auto-refresh
- **Kill Switches**: Instant enable/disable for any component

## Quick Start

```bash
# Configure with your credentials
nano ~/.hermes/skills/ozmoeg-money-maker/config.yaml

# Enable all components
python ~/.hermes/skills/ozmoeg-money-maker/enable.py all

# Run scanner during market hours
python ~/.hermes/skills/ozmoeg-money-maker/main.py --mode scan
```

## Configuration

Edit `config.yaml` to set:
- Telegram bot token and chat ID
- Gmail app password (for email alerts)
- OKX API credentials (optional crypto sentiment)
- Scanner filter values
- Trading strategy parameters

See `templates/config-template.yaml` for a ready-to-fill template.

## Market Hours

Typically trade between **9:30–11:00 AM ET** and **3:00–4:00 PM ET**. Avoid 11:00 AM–2:00 PM (low volume chop).

## Risk Management

- **Max Risk Per Trade**: 1% of account balance
- **Max Risk Per Day**: 3% of account balance  
- **Max Open Positions**: 2 at any time
- **PDT Rule**: US accounts under $25K tracked for 3 day trades per 5 rolling days

## Kill Switches

Disable components instantly:

```bash
# Disable everything
cd ~/.hermes/skills/ozmoeg-money-maker
python disable.py all

# Disable only alerts, keep dashboard
python disable.py telegram_alerts
python disable.py email_alerts

# Re-enable everything
python enable.py all

# Check status
python main.py --kill-status
```

Available switches: `master`, `scanner`, `news`, `strategy`, `telegram_alerts`, `email_alerts`, `website_updates`, `okx_sentiment`.

## Testing

1. Run scanner in paper mode first
2. Verify website updates at `aeyeing.com/ozmoeg-trader.html`
3. Send test Telegram message
4. Check logs for errors (`~./hermes/skills/ozmoeg-money-maker/logs/ozmoeg.log`)

## Troubleshooting

### Common Issues

1. **Webull login issues**: The `tedchou12/webull` library is broken (June 2026). Scanner works with public data only. For trading, consider Alpaca API.

2. **GitHub Pages cache**: After fixes, wait 2-10 minutes for CDN cache to clear.

3. **No candidates found**: Check if market hours match scanner times and ensure filters are compatible with current data.

4. **Telegram alerts not arriving**: Verify bot token, chat ID, and ensure bot is added to channel.

## References

- `references/getting-started.md` - Config location and first-run
- `references/kill-switches-and-removal.md` - Instant disable/remove
- `references/telegram-channel-setup.md` - Telegram channel setup
- `references/website-maintenance.md` - Dashboard maintenance
- `references/production-error-patterns.md` - Error troubleshooting

## Files Modified by This Commit

This commit adds the complete OzMoEg trading system with all core functionality:

- `config.yaml` - Core configuration
- `SKILL.md` - Full documentation  
- `main.py` - Entry point and orchestrator
- `scanner.py` - Small-cap scanner with Webull integration
- `news_monitor.py` - News catalyst analysis
- `analyzer.py` - Technical analysis engine
- `trade_planner.py` - Trade planning with CMT position sizing
- `risk_manager.py` - Risk management and PDT tracker
- `notifier.py` - Telegram + email notifications
- `webull_client.py` - Webull API integration (dual-mode)
- `website_updater.py` - Website dashboard updates
- `kill_switch.py` - Component kill switches
- `disable.py` - Disable CLI utility
- `enable.py` - Enable CLI utility
- `templates/config-template.yaml` - Configuration template
- `references/` - Additional documentation
- `website/` - HTML/CSS/JS frontend