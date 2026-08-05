# OzMoEg Money Maker — Kill Switch & Removal Guide

Everything is now designed so you can turn the trading skill off or remove it in seconds.

## Quick-disable commands

Run from the skill directory `~/.hermes/skills/ozmoeg-money-maker`:

```bash
# Disable everything (master switch)
python disable.py all

# Disable only noisy alerts, keep scanning + website
python disable.py telegram_alerts
python disable.py email_alerts

# Disable only website updates
python disable.py website_updates

# Re-enable everything
python enable.py all

# Check status
python main.py --kill-status
python disable.py status
```

## What each switch does

| Switch | Effect when OFF |
|--------|-----------------|
| `master` | Entire skill stops. `main.py` exits immediately. |
| `scanner` | Webull gainers fetch is skipped. |
| `news` | News scoring is skipped (existing main.py uses `news` flag). |
| `strategy` | Trade planning is skipped. |
| `telegram_alerts` | No Telegram channel alerts. |
| `email_alerts` | No email alerts or daily reports. |
| `website_updates` | `website_updater.update()` is skipped. |
| `okx_sentiment` | OKX crypto sentiment is skipped. |

## Removing the cron jobs entirely

If you decide the skill is not worth it, delete the three OzMoEg cron jobs:

```bash
hermes cron list
hermes cron remove ee2455159797
hermes cron remove 4a678d99c403
hermes cron remove a54f7ddf3a1e
```

Replace the IDs above with whatever `hermes cron list` shows for:
- `OzMoEg Money Maker - Market Scanner (15min)`
- `OzMoEg - Pre-Market Hourly Scan`
- `OzMoEg - Daily Report`

## Removing the skill files

If you want to delete the skill completely:

```bash
rm -rf ~/.hermes/skills/ozmoeg-money-maker
```

Your credentials were in `config.yaml`; removing the directory removes them too. No system-level changes were made.

## Rollback

The original config was backed up before any edits:

```bash
ls ~/.hermes/skills/ozmoeg-money-maker/config.yaml.bak.*
```

Copy the newest backup over `config.yaml` to revert to the pre-kill-switch configuration.
