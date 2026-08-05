---
name: ozmoeg-money-maker
description: Automated micro-scalp trading skill for US small-cap stocks using news analysis, momentum-based exit strategies, and multi-channel alerts (Telegram channel + website + email). Scanner works with public market data; trading execution requires alternative broker integration.
title: OzMoEg Money Maker - Small Cap Scalp Trading Bot
version: 1.2.0
category: trading
summary: Automated micro-scalp trading skill for US small-cap stocks using news analysis, momentum-based exit strategies, and multi-channel alerts (Telegram channel + website + email). Scanner works with public market data; trading execution requires alternative broker integration.
author: OzMo Shay
---

# OzMoEg Money Maker - Small Cap Scalp Trading Bot

> **Operational notes:** see `references/github-pages-deployment-race.md` for the concurrent-push Pages deployment fix (lock + 120-second cool-down and cadence gating), `references/issuer-region-country-fallback.md` for the unknown `issuerRegionId` fallback logic and country-badge styling.

Automated micro-scalp trading system for US small-cap stocks (market cap $300M–$2B). Monitors news feeds, identifies momentum catalysts, and generates actionable buy/sell plans using supply/demand zone + candlestick confirmation strategies. Integrates with Webull public market data for scanning and delivers alerts via Telegram channel, website, and email.

> **Website maintenance note:** The live dashboard at `ozmoeg-trader.html` is regenerated on every scan by `website_updater.py`. See [`references/website-maintenance.md`](references/website-maintenance.md) for the durable workflow used to fix layout regressions, the forecast tracker, and the refresh timer without losing changes to the next scan.

**⚠️ Webull API Update (June 2026):** The `tedchou12/webull` Python library login is broken — Webull returns `403 Illegal Client` at the server level. The scanner still works for **public data** (gainers, quotes, charts) without authentication. For actual order placement, consider **Alpaca API** as an alternative broker.

## ⚠️ CRITICAL WARNINGS

1. **HIGH RISK**: Small-cap scalping is extremely volatile. Never trade more than 2% of account per trade.
2. **PAPER TRADE FIRST**: Always run in paper mode for minimum 2 weeks before live trading.
3. **NEVER CHASE**: If a stock is already up >20% when news breaks, skip it — the move is over.
4. **HARD STOPS**: Every trade MUST have a stop-loss. No exceptions.
5. **PDT RULE**: US accounts under $25K are limited to 3 day trades per 5 rolling days. Track this.

## Kill Switches & Easy Removal

This skill is designed to be disabled or removed in seconds if it produces too much noise. A layered kill-switch system lets you shut off the whole skill, or just the noisy parts, without deleting files or credentials.

```bash
cd ~/.hermes/skills/ozmoeg-money-maker

# Disable everything immediately
python disable.py all

# Disable only alerts, keep the website dashboard running
python disable.py telegram_alerts
python disable.py email_alerts

# Re-enable everything
python enable.py all

# Read-only status check
python main.py --kill-status
```

Switches: `master`, `scanner`, `news`, `strategy`, `telegram_alerts`, `email_alerts`, `website_updates`, `okx_sentiment`.

If the user decides to remove the skill entirely: `python disable.py all`, delete the three OzMoEg cron jobs (`hermes cron remove <id>`), then `rm -rf ~/.hermes/skills/ozmoeg-money-maker`.

See `references/kill-switches-and-removal.md` for full implementation details and verification checklist.

## Prerequisites

- Webull account (for manual/paper trading via app/website)
- Python 3.9+
- `pip install webull requests pandas pytz beautifulsoup4 email-validator PyYAML`
- Telegram bot token (uses your existing OzMoEg bot @OzMoEgHbot)
- Gmail App Password (16 characters, NOT your Gmail login password)
- Optional: OKX API credentials (for crypto sentiment cross-validation)

**References:**
- `references/getting-started.md` — Config location, first-run, troubleshooting
- `references/credential-discovery.md` — How to find Telegram chat ID, Gmail App Password
- `references/telegram-channel-setup.md` — Step-by-step guide to create a dedicated Telegram channel
- `references/webull-us-api-gotchas.md` — **CRITICAL: Webull API login is broken (June 2026)**
- `references/webull-browser-auth.md` — Playwright browser automation attempt (partially blocked)
| `references/notifier-pitfalls.md` | Telegram HTML mode, token masking, channel ID discovery, **stable ticker-only deduplication** |
| `references/website-no-candidates-flood-regression.md` | Preventing 50 SKIP rows from flooding main table and news ticker |
| `references/website-country-badge-and-tracker-pnl-fix.md` | **Origin-country badge styling (small/light in news stream) + real scan-to-scan tracker P&L via backend `previous_live_quotes`** |
| `references/website-tracker-previous-scan-pnl.md` | **Real scan-to-scan tracker P&L using backend `previous_live_quotes`** |
| `references/website-country-badge-regression.md` | **Origin-country badge styling and client-side placement next to ticker** |
| `references/website-tracker-current-price-fix.md` | Tracker current price + refresh countdown |
| `references/website-tracker-previous-scan-pnl.md` | **Real scan-to-scan tracker P&L using backend `previous_live_quotes`** |
| `references/website-refresh-timer-and-toggle-reload-fix.md` | Refresh countdown anchored to JSON `last_updated`, active-window 5-min cadence |
| `references/production-error-patterns.md` | Live error log and component status |

- `references/webull-rvol-computation.md` — Why RVOL shows 0.0x and how to compute it from avgVol10D
- `templates/config-template.yaml` — Ready-to-fill configuration template

## Notification Architecture: Telegram Channel + Website (Email Disabled)

**User preference (June 2026):**
- **Telegram channel** (`OzMoEg Money Maker`, `-1003734081914`): Sole communication method — trade plans, entry/stop/targets, news catalysts, exit signals, daily summaries, warnings
- **Website** (`aeyeing.com/ozmoeg-trader.html`): Passive monitoring dashboard — all candidates, scanner results, **📰 Latest Catalyst & News section**, forecast vs actual tracker
- **Email** (`elshayeb@gmail.com`): **Disabled by default.** No trade alerts, no daily reports, no warnings. To opt back in, set `email.enabled: true` in `config.yaml`.
- **This Chat** (origin/cron): System status, errors, confirmations

### Routing Rules (Hard Rules)

| Event Type | Telegram Channel | Email | Rationale |
|------------|-----------------|-------|-----------|
| 🚨 **Trade ALERT** | ✅ Yes | ❌ **NO** | Telegram is the only actionable channel |
| 📊 **Daily report** | ✅ Yes | ❌ **NO** | Aggregated summary goes to Telegram channel only |
| ⚠️ **Scanner warning** (no gainers, API error) | ✅ Yes | ❌ **NO** | Creates inbox noise; not actionable |
| 🔔 **Risk limit hit** | ✅ Yes | ❌ **NO** | Routine status; Telegram is sufficient |
| 📝 **Tracker paused / expired** | ✅ Yes | ❌ **NO** | Dashboard handles this visually |

**Critical:** `notifier.send_email()` now returns immediately unless `email.enabled: true` is explicitly set in `config.yaml`. `notifier.alert_warning()` must NEVER call `send_email()`. This ensures `aeyeingserver@gmail.com` receives no OzMoEg alerts unless the user explicitly opts in.

**Key principle:** Telegram channel gets immediate actionable alerts. Website auto-refreshes with every scan and now includes a **📰 Latest Catalyst & News** section showing scored headlines with impact scores. Email is for aggregated end-of-day reports.

### Webull float data availability

The legacy Webull `get_quote()` response provides `outstandingShares` and `totalShares`. In the scanner, `outstandingShares` is used as the free-float proxy; `totalShares` is not required for filters. The ranking payload (`active_gainer_loser`) does **not** contain float data, so per-ticker quote enrichment is required before applying float-based filters.

**Webull also exposes issuer origin country via `issuerRegionId`** (see `references/webull-country-origin-fields.md`). The scanner maps this code to a human-readable country label and passes it through `scan_results` as `country` so the website can show "TC — Token Cat Ltd (China / Cayman-China)" next to each alert.

**Key rule for adding new filter fields:** the scanner's first filter pass runs on the ranking payload (price, change, volume, market cap) before per-ticker quotes are fetched. Any field that exists only in the quote response — such as `outstandingShares`, `avgVol10D`, `avgVol3M`, `issuerRegionId` — must be copied from the quote into the gainer dict during `enrich_gainers_with_quotes()` and then consumed in `_passes_filter_with_reason()` or a second `filter_candidates()` pass. This is exactly how `rvol_min`, `max_float_shares`, `min_volume_float_ratio`, `min_avg_daily_dollar_volume`, and `country` are implemented. If you try to apply these filters in the first pass, they will always be missing and every gainer will be rejected.

### Duplicate prevention

Three layers prevent notification spam:
1. **Cron jobs** deliver to `local` only. Hermes must never wrap scanner stdout as a "Cronjob Response" email. The skill handles its own Telegram + Email delivery.
2. **Skill deduplication:** `notifier.py` tracks sent alerts in `.sent_alerts.json`. Same ticker won't re-alert within `DUPLICATE_WINDOW_SECONDS` (**6 hours** as of June 2026). The 6-hour signature is **ticker-only**, not `ticker:entry:stop:targets`, so plan rebasing between refreshes does not bypass the throttle.
3. **Stateful deduplication:** `state_store.py` tracks market status transitions, scan-summary hashes, and quiet windows for warnings. Repeated identical scans do not produce repeated notifications.
4. **Telegram quality gate (June 2026):** Before sending a trade alert, `notifier.py` filters for fresh, high-conviction setups: impact score ≥ 3 (or score 2 only if news is ≤ 60 min old), R:R ≥ 1.5, news age ≤ 24 h (live) / 6 h (relaxed), and relaxed sessions require impact ≥ 4. Low-impact, stale-news, or repeated setups are logged and skipped.

**Alert Format:** Use `parse_mode='HTML'` for Telegram alerts, NOT Markdown. Trading alerts contain `$`, `.`, and numeric characters that Telegram's Markdown parser misinterprets. HTML `<b>` tags are safe and reliable.

## Quick Start

**Path:** `~/.hermes/skills/ozmoeg-money-maker/config.yaml`

Or on Windows:
```
C:\Users\openclaw\.hermes\skills\ozmoeg-money-maker\config.yaml
```

**This is the single source of truth.** All tunable parameters — stop loss %, profit targets, scanner filters, API keys, Telegram/email credentials — live here. Python modules read from config; they never hardcode values.

**Market Override:** Use the `--market` CLI flag to force the scanner to run in US or AU mode, automatically setting the appropriate `region_code` (US=6, AU=18). Example:
```bash
python ~/.hermes/skills/ozmoeg-money-maker/main.py --mode scan --market us   # US mode (default)
python ~/.hermes/skills/ozmoeg-money-maker/main.py --mode scan --market au   # Australian ASX mode
```
See `references/market-override-cli.md` for details.

```
ozmoeg-money-maker/
├── SKILL.md                          # This file — full strategy guide
├── references/                       # Extra docs (see below)
│   ├── getting-started.md            # Config location, first-run, troubleshooting
│   ├── kill-switches-and-removal.md  # How to disable/remove the skill instantly
│   ├── telegram-channel-setup.md     # Telegram channel setup guide
│   ├── webull-us-api-gotchas.md      # **CRITICAL: Webull login broken (June 2026)**
│   ├── webull-browser-auth.md        # Playwright auth attempt
│   ├── notifier-pitfalls.md          # Telegram/email debugging
│   ├── notification-routing-rules.md # **Milestone/change-based notification rules**
│   ├── cron-delivery-architecture.md # **Cron `deliver: local` architecture**
│   ├── production-error-patterns.md  # Live error log
│   ├── okx-api-integration.md        # OKX crypto sentiment
│   └── webull-rvol-computation.md    # Why RVOL shows 0.0x
├── config.yaml                       # ← YOUR CREDENTIALS AND SETTINGS
├── kill_switch.py                    # Kill-switch guard module
├── disable.py                        # CLI: disable components
├── enable.py                         # CLI: re-enable components
├── state_store.py                    # Persistent notification deduplication state
├── scanner.py                        # Screen for active small-cap movers
├── news_monitor.py                   # Fetch and analyze news
├── analyzer.py                       # Technical analysis engine
├── trade_planner.py                  # Generate entry/exit plans
├── webull_client.py                  # Dual-mode API client
├── notifier.py                       # Telegram + email alerts
├── risk_manager.py                   # Position sizing, PDT tracker
├── main.py                           # Entry point / cron job
├── webull_auth.py                    # Playwright browser auth (experimental)
├── templates/
│   └── config-template.yaml          # Ready-to-fill config template
└── website/
    └── ozmoeg-trader.html            # Live trading monitor (deployed to aeyeing.com)
```

## Core Trading Strategy (Momentum Scalping Methodology)

### 1. Market Context
- Trade during **market open 9:30–11:00 AM ET** and **close 3:00–4:00 PM ET**.
- Avoid trading 11:00 AM–2:00 PM (low volume chop).
- Check SPY/QQQ trend — only trade in direction of market.

### 2. Scanner Criteria (Pre-Market & Live)

Filter for stocks that meet ALL of:

**Default US values as of July 2026 (deployed A+B+C set):**
- Market cap: **$5M–$300M** (with strict liquidity gate for $5M–$10M)
- Price: **$0.50–$30.00**
- Pre-market/active % change: **>5% AND ≤80%** (tiered rules)
  - **5%–40%**: standard filters
  - **40%–80%**: allowed only if float/turnover/RVOL are stronger (`rvol ≥3.0x`, `volume/float ≥2.0x`)
- Free float (Webull `outstandingShares` proxy): **≤50M shares**
- Relative Volume (RVOL): **>2.0x** (computed from `volume / avgVol10D`; fallback `avgVol3M`)
- Volume ÷ Float ratio: **≥0.5x** (≥1.0x strong)
- Average daily dollar volume: **≥$5M** (`avgVol10D × price`, fallback `avgVol3M × price`)
- Tiny-cap gate ($5M–$10M mkt cap): requires `price ≥$1.00`, `volume/float ≥1.0x`, `avg daily $vol ≥$2M`, `RVOL ≥2.0x`
- ATR (14-day): >2% of price
- Avoid: Chinese companies, shells, biotech binary events
- **Bounce scanner (Option C):** separate research-only scan of large down-movers (move ≤-20%) with market cap $5M–$50M; displayed in a collapsible "🔻 Bouncers" section, never auto-alerted

**Historical broad US values (rolled back from backup if needed):**
- Market cap: **$25M–$5B**
- Price: **$0.50–$30.00**
- Pre-market % change: **>5% OR** volume > 1.5x 20-day average
- Float: <100M shares
- Relative Volume (RVOL): >1.5x
- ATR (14-day): >2% of price

**ASX values:** see the `scanner.au` block in `config.yaml`.

**Config/website sync rule:** Whatever range is set in `config.yaml` under `scanner.*` must be identical to the text shown on the website in the **📋 Rules / Filters Applied** section. If they drift apart, micro-caps will either pass silently or be rejected unexpectedly, and the user will lose trust in the filter logic. After changing `config.yaml`, do three things in the same deploy:
1. Patch `scanner.py` if the new field only exists in the quote response (see float/RVOL rule above).
2. Pass the new values to `website_updater.update(..., scan_stats={'us_filters': {...}})` from `main.py`.
3. Update the static fallback list and the dynamic `renderPlanRules()` JavaScript in `ozmoeg-trader.html`.

**Visibility rule:** The scanner must annotate every stock with why it passed or failed (`_scan_passed`, `_scan_reason`), and the website must expose all scanned tickers in a collapsible table so the user can audit the filter logic. Do not display only "No candidates found" — that makes the dashboard look dead.

**Momentum rule fix (June 2026):** The original filter rejected stocks when `change_pct < 5%` AND `rvol < 1.5`. With Webull returning RVOL=0 for many movers, this was killing legitimate +15% runners. The corrected logic requires either strong % change OR strong RVOL:
```python
if abs(change_pct) < premarket_pct_min and rvol < rvol_min:
    fails.append(f'move {change_pct:.1f}% / rvol {rvol:.1f}')
```

### News Catalyst Analysis

Rank news by impact (1–5 scale):
| Score | Catalyst Type |
|-------|---------------|
| 5 | Merger/acquisition, buyout, partnership with major corp |
| 4 | FDA approval, patent win, big contract |
| 3 | Earnings beat + guidance raise, analyst upgrade |
| 2 | Share buyback, insider buying, new product launch |
| 1 | Generic PR, vague "strategic review" |

**Action Rule**: Only trade if news score ≥ 3 AND confirmed by 2+ independent sources.

**News age stamps (June 2026):** Every headline displayed on the website must show its original publication age (e.g. `3d ago · 19 Jun`, `2mo ago · 22 Apr`) so old news does not look like a fresh catalyst. The backend normalizes `newsTime` / `time` / `date` fields and the frontend adds a `news-age` badge; items older than 7 days are highlighted in red with a ⚠️ warning. The badge is a rounded cyan pill with a tooltip showing the exact first-publication ISO timestamp. See `references/asx-tickerid-and-news-timestamps-fix.md`.

### Market-Open Exception (Small-Cap News Blackout)

**User note (June 2026):** "I knew that the catalyst/news usually stops while the market is open because of the market rule especially for small caps, so we may need to remove the filter of catalyst/news during market open and rely on the before/after market catalyst and news for all small caps."

Once the US market is open, many news vendors stop syndicating real-time small-cap headlines because of exchange/vendor rules. Requiring a fresh catalyst score ≥ 3 during regular hours will filter out nearly all legitimate runners and leave the scanner silent. Therefore, during **US regular hours** the catalyst gate is relaxed: a candidate is allowed through if it passed the technical/momentum filters, using the headline from the pre/after-hours scan (or a relaxed placeholder). The alert is tagged `confidence: LOW` and the user is explicitly warned to verify the catalyst independently. Do not apply this relaxation during the strict pre-market/after-hours research phase unless the pre-market relaxation rule below is also triggered.

**Pre/after-hours relaxation:** During US pre-market/after-hours, headline flow is thinner. If the scanner requires the same `min_score: 3` and `confirmation_sources: 2` as regular hours, every candidate fails news scoring. The fix:
- Outside market hours, lower `min_score` to `2` and `confirmation_sources` to `1`.
- Also bypass the demand-zone / candlestick gate when `catalyst_relaxed` is true, because intraday bars are too thin to form demand zones pre-market.
- Set `confidence = "LOW"` (or "MED") for these relaxed setups so the user knows TA confirmation is weaker.

### 4. Supply & Demand Zones
- **Demand Zone**: Previous support where price bounced 2+ times. Wait for price to retest demand on low volume = entry.
- **Supply Zone**: Previous resistance where price rejected. Sell into supply.
- **Confirmation**: Use Japanese candlesticks — hammer, engulfing, morning star at demand; shooting star, bearish engulfing at supply.

### 5. Time & Sales (Tape Reading)
- Watch for blocks >10% of average trade size hitting bid = selling pressure.
- Watch for blocks hitting ask = buying pressure.
- If tape slows down after a big green candle = take profits.

### 6. Entry/Exit Rules (Momentum-Based Scalps — NO Fixed Timer)

#### ENTRY
1. Stock breaks pre-market high on news catalyst.
2. Pulls back to demand zone (previous breakout level).
3. Candlestick confirmation (bullish engulfing, hammer).
4. Volume > 1.5x average on the entry candle.
5. Entry = break of the confirmation candle high.

### 6. Entry/Exit Rules (Momentum-Based Scalps — NO Fixed Timer)

#### ENTRY
1. Stock breaks pre-market high on news catalyst.
2. Pulls back to demand zone (previous breakout level).
3. Candlestick confirmation (bullish engulfing, hammer).
4. Volume > 1.5x average on the entry candle.
5. Entry = break of the confirmation candle high.

#### STOP LOSS
- Hard stop at **-2%** from entry by default. This gives R:R ≈ 1.50 against Target 1 (+3%).
- **Webull bracket-order rule:** stop-loss/take-profit legs must be at least **0.1% apart** from the stock price. To avoid rejection on very low-priced stocks where rounding could make the stop too tight, `trade_planner.py` enforces a tiny **0.15% floor** and rounds the stop to 4 decimals.
- **Pitfall:** Raising the default stop loss to 3% to "be safe" collapses R:R to 1.00 and kills all alerts. Do not do this. Keep `stop_loss_pct: 2.0` and rely on the 0.15% floor for edge cases.
- Trail stop to breakeven once up +1%.
- Use ATR stop: Entry − (0.5 × ATR). ATR must only tighten the stop, never widen it beyond the configured percentage stop.

#### ATR Stop Pitfall (US pre-market / wide-range bars)

`trade_planner.py` originally computed:
```python
if self.cfg.get('market', '').lower() == 'au':
    stop = max(stop, atr_stop)
else:
    stop = min(stop, atr_stop)   # WRONG for US too
```
The `min()` branch picked the wider (lower) stop for US mode. On a volatile pre-market bar with a wide ATR, this stretched the stop far below the 2% default and collapsed R:R. Example: GDHG @ $1.60 — default 2% stop = $1.568 (R:R 1.50), but ATR stop = $1.556 (R:R 1.10). The fix is to always pick the tighter stop:
```python
stop = max(stop, atr_stop)
```
Now both US and AU modes preserve the configured R:R unless ATR provides a tighter, safer stop.

#### PROFIT TARGETS (Momentum-Based Exits — No Fixed Timer)
- Target 1: +3% (sell 50% position).
- Target 2: +5% (sell 25% position).
- Target 3: +8% (trail stop with 2% cushion, let it run).
- **EXIT WHEN MOMENTUM DIES** — not on a timer:
  - Bearish engulfing or shooting-star candle appears.
  - Tape (time & sales) slows after a big green candle.
  - Volume drops >50% from entry candle.
  - Price approaches a known supply zone.
- **No fixed max-hold time.** Stay in as long as momentum persists; get out immediately when it stalls.

#### PROFIT TARGETS (Momentum-Based Exits — No Fixed Timer)

**Default (video formula enabled):** minimum Risk:Reward ratios derived from the stop distance.
- Target 1: **1:2** R:R (entry + 2 × stop_distance) — sell 50%.
- Target 2: **1:3** R:R (entry + 3 × stop_distance) — sell 25%.
- Target 3: **1:5** R:R (entry + 5 × stop_distance) — trail remaining 25%.

**Legacy (video formula disabled):** fixed percentage targets.
- Target 1: +3% (sell 50%).
- Target 2: +5% (sell 25%).
- Target 3: +8% (trail stop with 2% cushion, let it run).

**EXIT WHEN MOMENTUM DIES** — not on a timer:
- Bearish engulfing or shooting-star candle appears.
- Tape (time & sales) slows after a big green candle.
- Volume drops >50% from entry candle.
- Price approaches a known supply zone.
- **No fixed max-hold time.** Stay in as long as momentum persists; get out immediately when it stalls.

### 7. Position Sizing Formula (Ahmed Khaled CMT "Golden Triangle")

Based on the video formula: **fix the dollar risk per trade (R), not the dollar position; then size by the stop distance.**

```python
def position_size(account_balance, max_daily_loss_pct, max_trades_per_day,
                    entry_price, stop_price, max_position_pct=25.0):
    """
    Video-formula position sizing.
    """
    daily_risk_budget = account_balance * (max_daily_loss_pct / 100)
    risk_amount = daily_risk_budget / max_trades_per_day        # R
    risk_per_share = abs(entry_price - stop_price)
    if risk_per_share == 0:
        return 0
    shares = max(1, round(risk_amount / risk_per_share))
    # Cap at max position % of account
    max_shares = int((account_balance * (max_position_pct / 100)) / entry_price)
    return min(shares, max_shares)
```

**Example (video):** $1,000 account, 3% daily risk = $30, ÷ 3 trades = **$10 risk per trade (R)**.
- $10 ÷ $0.10 stop distance = 100 shares
- $10 ÷ $0.50 stop distance = 20 shares

**Current config default:** $2,000 account, 3% daily risk = $60, ÷ 3 trades = **$20 R**. With a 15% position cap the maximum position value is $300.

Set `strategy.video_sizing: true` (default) to use this formula. Set `false` to revert to the legacy fixed `$100` test position sizing.

## Webull API Integration — CRITICAL UPDATE (June 2026)

⚠️ **The `tedchou12/webull` library login is BROKEN.** Webull returns `403 Illegal Client` for all login attempts regardless of credentials or region. This is a server-side block of the library's client identifier.

**What still works:**
- ✅ Top gainers list (public data)
- ✅ Stock quotes and charts (public data)
- ✅ Technical indicators (computed from public data)
- ✅ News scraping (via alternative sources)

**What is broken:**
- ❌ Login/authentication
- ❌ Account balance/positions
- ❌ Paper trading via API
- ❌ Order placement (paper or live)

**Official OpenAPI** (`openapi.webull.com.au`) only resolves in AU region. From US/non-AU environments, all documented official endpoints return DNS failures or 404s. The legacy library and the desktop app use separate internal API endpoints.

### Scanner Mode (Current Default)
The skill runs in **unauthenticated scanner mode** — finding candidates, analyzing them, and generating trade plans. You execute trades manually via Webull app/website.

```python
# The client auto-detects that login is broken and falls back
from webull_client import WebullClient
wb = WebullClient(config['webull'])
# → "Legacy Webull login failed: Expecting value... — continuing in unauthenticated mode"
# → Scanner still works: wb.active_gainer_loser() returns data
```

### Backup US Stock Data Sources (June 2026)

To reduce dependence on Webull public data, a backup data client is now integrated:

- **Primary source:** Webull public gainers/quotes (still works unauthenticated)
- **Backup provider 1:** **Alpaca Markets** — best redundancy, requires API key/secret
- **Backup provider 2:** **Yahoo Finance** — zero-config, always available, used when Alpaca is not keyed

The backup client is used for **per-ticker quote enrichment** when Webull fails to return a quote for a specific symbol. It also provides market-cap verification and premarket price data.

**Config:**
```yaml
backup_data:
  enabled: true
  alpaca:
    api_key: ''      # paste Alpaca key here
    secret_key: ''   # paste Alpaca secret here
    paper: true      # set false for live trading
  yfinance:
    enabled: true
```

**Fallback chain in `backup_data_client.py`:**
1. If Alpaca key/secret are present, try Alpaca first.
2. If Alpaca fails or is not configured, fall back to Yahoo Finance via `yfinance`.
3. Quotes merged into the gainer payload are tagged with `_backup_quote: true` and `_backup_source` for website transparency.

**Limitations:**
- Yahoo Finance does not expose a "top gainers" API, so it cannot fully replace Webull's gainer list. It only provides quote/history redundancy.
- Alpaca can provide snapshots and historical bars; with a key it can also serve as a full gainer-list replacement via `StockSnapshotRequest`.

See `references/backup-data-sources.md` for architecture, testing, and Alpaca signup steps.

### Extracting Webull Desktop Session Tokens

If you are actively logged into the Webull Desktop app and want to reuse that session for API calls:

- The desktop app is a **Qt/Chromium hybrid** (`Webull Desktop.exe` + `gpu-process`), not a plain Electron app.
- It does **not** store plaintext API keys or session tokens in logs, `settings.json`, or the SQLite `settings.db`.
- The app is configured for **region 18 (Australia)** in `AppData/Roaming/Webull Desktop/Webull Desktop/config/region.ini`, even when trading US stocks.
- The most practical extraction options are:
  1. **Semi-manual browser login** — log into `https://app.webull.com` in a regular browser, then use CDP/Playwright to extract `accessToken`, `refreshToken`, `uuid` from cookies/localStorage.
  2. **MITM the desktop app traffic** — install a local proxy/root CA to capture HTTPS calls and extract tokens. Invasive and may trigger security checks.
  3. **Memory scrape the running process** — fragile and not recommended.

See `references/webull-desktop-token-extraction.md` for full investigation details and extraction options.

### Alternatives for Order Execution

| Broker | API Quality | Cost | Recommendation |
|--------|-------------|------|----------------|
| **Alpaca** | Excellent | Free | **Best alternative** — built for bots; also doubles as backup data source |
| **Interactive Brokers** | Robust | Commission | Good for advanced traders |
| **Webull (manual)** | N/A | Free | Use app/website for execution |

**To add Alpaca:** Update `config.yaml` with Alpaca API key/secret under `backup_data.alpaca`. Modify `webull_client.py` to support Alpaca as a third mode.

## AU / ASX scanning — use tickerId, not symbol (June 2026)

The official `openapi.webull.com.au` only resolves in AU region. From non-AU environments, use the public `quotes-gw.webullfintech.com` ranking endpoint with `regionId=18`. **Do not use `paper_webull()` for ASX** — it ignores `region_code` and returns US gainers. Use `webull(region_code=18)`.

Per-symbol quote, bars, and news endpoints return `API_DISABLED` from non-AU networks **when looked up by symbol**. However, the ranking payload already contains the Webull `tickerId` for each ASX ticker. Isolated tests confirm that passing `tId=...` to `get_quote`, `get_bars`, and `get_news` returns real data. The AU pipeline therefore builds a `{symbol: tickerId}` map from the gainer list and threads `tId` through every per-symbol call.

The TA demand-zone / candlestick gate is relaxed for AU micro-caps because intraday bars are often thin and textbook demand zones rarely form on sub-penny announcements. AU results remain `CANDIDATE` status (not live `ALERT`) because the non-AU network position is research-only.

AU result text no longer hardcodes `(data limited)` in every row:
- With a price-sensitive ASX announcement: `AU candidate (ASX announcement): Entry $...`
- Without one: `AU candidate: Entry $...`
- Detail text: `ASX data from non-AU network. Verify quote/price on ASX broker before trading.`

See `references/asx-tickerid-and-news-timestamps-fix.md`.

### Alternatives for Order Execution

| Broker | API Quality | Cost | Recommendation |
|--------|-------------|------|----------------|
| **Alpaca** | Excellent | Free | **Best alternative** — built for bots |
| **Interactive Brokers** | Robust | Commission | Good for advanced traders |
| **Webull (manual)** | N/A | Free | Use app/website for execution |

**To add Alpaca:** Update `config.yaml` with Alpaca API key/secret. Modify `webull_client.py` to support Alpaca as a third mode.

## Notification Templates

### Telegram Alert Format (HTML Mode)
```
🚀 OzMoEg Alert — [TICKER]
📰 Catalyst: [News headline]
💥 Impact Score: [1–5]/5
💰 Entry Zone: $X.XX – $X.XX
🛑 Stop Loss: $X.XX (-2%)
🎯 T1: $X.XX (+3%) | T2: $X.XX (+5%) | T3: $X.XX (+8%)
⏱ Exit When: Momentum dies — bearish candle, tape slows, volume drops
📊 Shares: XXX | Value: $X,XXX
📈 Risk:Reward: 1:X
📋 Rules/Filters Applied:
  ✅ Price range: $X.XX–$X.XX
  ✅ Market cap: $X.XXM–$X.XXB
  ✅ RVOL > X.Xx
  ✅ Demand zone retest
  ✅ Candlestick confirmation
  ✅ VWAP confirmation
  ✅ News score X/5 (≥3)
  ✅ R:R ≥ 1.25
  ✅ Position sizing: XXX shares
📰 News/Announcements:
  • [5/5] [Headline 1]
  • [4/5] [Headline 2]
  • [3/5] [Headline 3]
```

### Email Daily Report Format
- **Disabled by default.** When enabled (`email.enabled: true`):
  - Trade alert subject: `🚀 OzMoEg Alert — {TICKER} | Impact {score}/5 | Entry ${entry}`
  - Market status subject: `🟢 OzMoEg {US|AU} Market {OPEN|CLOSED}`
  - Scan summary subject: `🚀 OzMoEg {US|AU} Scan — {N} alert(s) | TICK1, TICK2`
  - Daily report subject: `OzMoEg Money Maker — Daily Report [DATE]`
  - Delivered to: `elshayeb@gmail.com`
  - Sent from: `aeyeingserver@gmail.com`
- Subjects must never be generic "Hermes agent" or "Cronjob Response: ...". The skill builds the subject from the alert data.

## Cron Job Setup (Deployed Jobs)

**Critical delivery rule:** All OzMoEg cron jobs must use `deliver: "local"`. Never use `deliver: "origin"` or `deliver: "telegram:..."` for scanner jobs, because Hermes will wrap the skill's stdout as a "Cronjob Response" email/Telegram message and bypass the skill's deduplication. See `references/cron-delivery-architecture.md`.

```yaml
# 1. ASX Scanner — every 15 min during Sydney market hours
#    Name: OzMoEg Money Maker - ASX Scanner (15min)
#    ID: ca205d338268
#    deliver: local

### 2. Active market-hours scanner
#    Schedule: every 15 minutes, Mon-Fri (US market hours in Sydney time)
#    Name: OzMoEg Money Maker - Market Scanner
#    ID: ee2455159797
#    deliver: local

### 3. Pre-market hourly scan
#    Schedule: every 30 minutes during pre-market window (5-9 PM Sydney, Mon-Fri)
#    Name: OzMoEg - Pre-Market Hourly Scan
#    ID: 4a678d99c403
#    deliver: local

# 4. Daily report
#    Schedule: 06:00 Sydney time, Mon-Fri
#    Name: OzMoEg - Daily Report
#    ID: a54f7ddf3a1e
#    deliver: local
```

## Workflow (Step-by-Step)

### Phase 1: Pre-Market Scan (9:00–9:30 AM ET)
1. Fetch top gainers from Webull (public data — no login needed).
2. Filter by market cap, price, float, volume.
3. Fetch news for each candidate.
4. Score news catalysts (1–5).
5. Build watchlist of 3–5 stocks with score ≥ 3.
6. Pre-market highs, demand zones, ATR calculation.
7. Send pre-market watchlist alert to Telegram channel.

### Phase 2: Live Market Monitoring (9:30 AM–4:00 PM ET)
1. Every 15 minutes: refresh scanner for new momentum.
2. For each watchlist stock:
   - Pull 1-minute candles.
   - Check for demand-zone retest + candlestick confirmation.
3. When setup triggers:
   - Calculate position size.
   - Log planned entry, stop, targets.
   - Send Telegram alert to channel.
   - **Execute trade manually** via Webull app/website (API order placement is broken).
4. Every 1 minute while in trade: monitor P&L, adjust trailing stop.

### Phase 3: End-of-Day (4:00 PM ET)
1. Close any open positions.
2. Calculate daily P&L.
3. Log all trades with screenshots/notes.
4. Send daily report email.

### Phase 4: Weekend Review
1. Review all trades — what worked, what failed.
2. Update scanner filters if needed.
3. Plan for next week.

## Risk Management Rules

1. **Max Risk Per Trade**: 1% of account balance.
2. **Max Risk Per Day**: 3% of account balance.
3. **Max Open Positions**: 2 at any time.
4. **Max Loss Streak**: Stop trading after 3 consecutive losses.
5. **Gap Down Rule**: If stock gaps down >5% against you at open, sell immediately (do not hope).
6. **Halts**: If stock is halted (LUDP), cancel any pending orders and wait for reopen. Do NOT enter new positions within 5 minutes of reopen.
7. **Earnings Avoidance**: Do not hold through earnings. Close before close on earnings day.

## Configuration File (config.yaml)

**File location:** `~/.hermes/skills/ozmoeg-money-maker/config.yaml`
(Windows: `C:\Users\openclaw\.hermes\skills\ozmoeg-money-maker\config.yaml`)

```yaml
webull:
  email: "your_webull_email@example.com"
  password: "your_password"
  paper_mode: true  # MUST be true until fully tested
  region_code: 6    # US = 6 (verified June 2026). AU = 18.
  device_name: "OzMoEgBot"
  use_official_api: false  # US: must be false. AU: must be false from non-AU networks; use public quotes-gw endpoint
  app_key: "YOUR_APP_KEY"       # Official API only (AU, often fails from non-AU IP)
  app_secret: "YOUR_APP_SECRET" # Official API only (AU)
  access_token: "YOUR_ACCESS_TOKEN"  # Optional: from browser or app
  account_id: "YOUR_ACCOUNT_ID"      # Optional

  # OKX API (cryptocurrency cross-market sentiment)
  okx:
    enabled: true
    api_key: "YOUR_OKX_API_KEY"
    api_secret: "YOUR_OKX_API_SECRET"
    passphrase: "YOUR_OKX_PASSPHRASE"
    base_url: "https://www.okx.com"
    paper_mode: true
    use_for_sentiment: true
    watch_symbols: ["BTC-USD", "ETH-USD", "SOL-USD"]
```yaml
scanner:
  enabled: true
  market: us          # 'us' or 'au' — drives region_code, rank_type, filters
  region_code: 6
  # US filters (default)
  market_cap_min: 25000000    # US small-cap floor: $25M (matches displayed rule)
  market_cap_max: 5000000000   # US small-cap ceiling: $5B (matches displayed rule)
  price_min: 0.50
  price_max: 30.00
  rvol_min: 1.5            # US: require >1.5x RVOL when change is weak; ignored when change is strong
  premarket_pct_min: 5.0     # US pre-market: any gapper >= 5% (or high RVOL)
  volume_min: 100000
  # AU/ASX overrides (applied in scanner.py when market == 'au')
  au:
    market_cap_min: 1_000_000     # ASX micro-cap floor: $1M AUD
    market_cap_max: 500_000_000   # ASX small-cap ceiling: $500M AUD
    price_min: 0.001              # ASX sub-cent stocks are common
    price_max: 5.00               # Upper ASX small-cap price bound
    premarket_pct_min: 8.0        # ASX gapper threshold: >= 8% (or high relative volume)
    volume_min: 200_000           # ASX: meaningful intraday dollar volume (~$50k+ face value)
    rvol_min: 1.0                 # ASX: require >1.0x RVOL when change is weak
    volume_value_aud_min: 50000   # ASX extra: approximate dollar-volume filter (price * volume)
  top_n: 50
### RVOL computation note
Webull ranking payloads do NOT include a pre-computed `rvol` field. The scanner must compute approximate RVOL from `volume / avgVol10D` (or `avgVol3M` as fallback). Without this, every candidate shows `0.0x` RVOL and the filter becomes meaningless. See `references/webull-rvol-computation.md`.
```

```yaml
strategy:
  account_balance: 2000.0    # Realistic test-account size; video formula sizes from this
  risk_per_trade_pct: 1.0    # Legacy risk-per-trade % (kept for compatibility)
  max_daily_loss_pct: 3.0    # 3% of account = max daily loss budget
  max_position_pct: 15.0     # Hard ceiling: positions cannot exceed 15% of account
  max_trades_per_day: 3      # splits daily risk budget into per-trade R
  test_trade_dollars: 100.0  # Legacy fixed-$ test position (used when video_sizing=false)
  stop_loss_pct: 2.0         # Default stop-loss distance (keep 2%; 3% collapses R:R to ~1:1)
  target_1_pct: 3.0        # Legacy fixed-% targets (used when video_sizing=false)
  target_2_pct: 5.0
  target_3_pct: 8.0
  trading_hours_start: "09:30"
  trading_hours_end: "16:00"
  timezone: "America/New_York"
  video_sizing: true         # Use Ahmed Khaled CMT formula: R = 3% daily ÷ 3 trades; shares = R / stop_distance
```

### Position sizing rule (video formula)

The tracker and trade plan display use the video formula by default:
- `daily_risk_budget = account_balance × max_daily_loss_pct / 100`
- `risk_amount (R) = daily_risk_budget / max_trades_per_day`
- `shares = max(1, round(R / (entry − stop)))`
- Position value is capped at `account_balance × max_position_pct / 100`.

With the current defaults ($2,000 account, 3% daily loss, 3 trades, 15% cap):
- Daily risk budget = $60
- Per-trade R = $20
- Typical position value ≈ $300

Set `video_sizing: false` to revert to the legacy behavior:
- `shares = max(1, round(test_trade_dollars / entry_price))`
- `position_value = shares × entry_price`
- Targets use fixed percentages (`target_1_pct`, `target_2_pct`, `target_3_pct`).

Re-run the scanner after changing `video_sizing`, `account_balance`, `max_position_pct`, or any strategy numbers so the website JSON is regenerated with the new plans.

  min_score: 3
  confirmation_sources: 2

telegram:
  bot_token: "YOUR_BOT_TOKEN"  # @OzMoEgHbot token
  chat_id: "YOUR_CHAT_ID"      # Channel ID starts with -100
```yaml
email:
  enabled: false              # User preference: Telegram channel only. Set true to opt back in.
  smtp_server: "smtp.gmail.com"
  smtp_port: 587
  username: "aeyeingserver@gmail.com"
  password: "YOUR_APP_PASSWORD"  # 16-char Gmail App Password, NOT login password
  from_address: "aeyeingserver@gmail.com"
  to_address: "elshayeb@gmail.com"
```yaml
logging:
  level: "INFO"
  file: "ozmoeg.log"
```

### AU mode alert policy

AU mode from non-AU networks must **not** send live Telegram/email trade alerts. The pipeline cannot verify a real catalyst or intraday demand zone. Instead:
- Mark candidates as `status: CANDIDATE`.
- Log the synthetic trade plan for research.
- Surface a clear warning on the website.
- Result text should **not** blanket-label every AU row as `(data limited)`. Use `AU candidate:` or `AU candidate (ASX announcement):` and explain the verify-first caveat in the detail text.

Only enable AU trade alerts after adding a real AU data source (broker API, IRESS, TradingView webhook) that can supply intraday bars and news.

## Python Scripts Reference

| File | Purpose | Key Method |
|------|---------|-----------|
| `kill_switch.py` | Kill-switch guard | `is_enabled()`, `component_enabled()` |
| `disable.py` | CLI helper to turn off switches | `disable.py all` / `disable.py scanner` |
| `enable.py` | CLI helper to turn on switches | `enable.py all` |
| `scanner.py` | Small cap screener | `filter_candidates()` |
| `news_monitor.py` | News analysis | `analyze_ticker()` — scores catalysts 1–5 |
| `analyzer.py` | Technical analysis | `identify_demand_zones()`, `is_bullish_engulfing()`, `calculate_atr()` |
| `trade_planner.py` | Trade plan generator | `plan_trade()` — momentum-based exits, no fixed timer |
| `webull_client.py` | Webull wrapper | Dual-mode: official (AU, often broken) + legacy (US, login broken) |
| `notifier.py` | Alert system | Telegram HTML mode + email. Sends to channel + email. **2-hour deduplication** via `.sent_alerts.json`. **alert_warning() = Telegram only** |
| `risk_manager.py` | Position sizing, PDT tracker, daily loss limits |
| `main.py` | Entry point | Orchestrates scan → analyze → plan → alert pipeline. Respects kill switches. Uses `state_store.py` for milestone/change-based notifications. |
| `website_updater.py` | **Website auto-update** | `update()` — writes JSON, regenerates HTML (news ticker + scanner table + badge + **📰 news-catalyst-card** with ticker attribution, timestamps, clickable links), git push |

### website_updater.py — Key Implementation Notes

The `website_updater.py` is the most fragile component. It modifies HTML by string replacement, not DOM manipulation. Here are the hard-earned rules:

See `references/website-alert-driven-plan-tracker-news.md` for the exact selectors, skeleton IDs, backend JSON contract, and the GitHub Pages cache-bypass verification recipe.

### 0. Keep the dynamic skeleton intact
The **Active Trade Plan**, **Forecast vs Actual Tracker**, and **Latest Catalyst & News** sections are populated by JavaScript from JSON. The HTML template must keep the skeleton elements (e.g. `id="alert-selector"`, `id="plan-grid"`, `id="perf-grid"`, `id="news-list"`) and the updater must **never** replace them. Only update the static sections listed in rule 1.

**Tracker basis rule:** the tracker must compare the previous scan's live quote to the current scan's live quote. Do not use the rebased live entry price (used by the Active Trade Plan in extended hours) as the tracker basis, or P&L will be zero on every fresh load. The backend should ship `previous_live_quotes` in the JSON; the client should prefer it and fall back to browser `localStorage` only when absent. See `references/website-country-badge-and-tracker-pnl-fix.md`.

**⚠️ Static Content Pitfall (June 2026):** Never hard-code market-specific ticker data in the HTML template. The scanner table body and scanned gainers table must use placeholder text so JavaScript loads the correct market data from `ozmoeg-latest.json` (US) or `ozmoeg-latest-au.json` (AUS). Hard-coded US tickers will appear on both US and AUS pages regardless of which button is clicked. See `references/static-content-fix-market-toggle.md`.

Use separate JSON files per market so the US/AUS toggle shows distinct data:
- US scan → `ozmoeg-latest.json`
- AU scan → `ozmoeg-latest-au.json`

See `references/website-dynamic-sections-architecture.md` for the full contract and common failure modes.

### 1. Badge Must Derive from Live Data
Never hardcode candidate/alert counts in the HTML template. The updater must:
```python
alert_results = [r for r in scan_results if r.get('status') == 'ALERT']
total_candidates = len(scan_results)
alert_count = len(alert_results)
badge_text = f'{total_candidates} candidates | {alert_count} alerts'
```

### 2. Do NOT Auto-Switch the Market Toggle from Live Data
The frontend toggle state (`currentMarket`) is a **user preference** stored in `localStorage`. The live JSON's `scan_stats.market` tells you where the backend scanned, but calling `switchMarket(marketFromData)` inside `loadLiveData()` whenever it differs from `currentMarket` will snap the toggle back against the user's choice. Only update the **badge label** to reflect the data source; never overwrite the toggle.

See `references/website-market-toggle-aus.md`.

### 3. Table Body Must Rebuild from scan_results
The `<tbody>` must be completely regenerated every scan:
```python
table_rows = []
for result in scan_results:
    # Build <tr> from result dict
```
If `scan_results` is empty, show: `"No candidates found in latest scan"`.

### 11. Verify GitHub Pages cache before declaring the website fixed
After pushing, GitHub Pages + Fastly may serve stale HTML/JSON for several minutes even with `Cache-Control: no-cache` headers. Always verify the deployed source with a cache-busting query string, e.g.:
```bash
curl -H 'Cache-Control: no-cache' 'https://aeyeing.com/ozmoeg-trader.html?nocache='$(date +%s) | grep -oE 'candidates-card table tbody|Auto-refresh: [0-9]+ min|ozmoeg-latest-au'
curl -sL "https://aeyeing.com/ozmoeg-latest.json?nocache=$(date +%s)" | python3 -c "
import json,sys
from datetime import datetime
d=json.load(sys.stdin)
print('last_updated:', d.get('last_updated'))
for r in d.get('scan_results', []):
    if r.get('status') == 'ALERT':
        p=r['plan']
        print(r['ticker'], 'R=', p['risk_amount'], 'shares=', p['shares'], 'pos=', p['position_value'])
"
```
If the new code/JSON is absent, wait and retest with a fresh query string before assuming the fix failed. The `website_updater.py` pushes immediately, but GitHub Pages + Fastly can take 2–10 minutes to invalidate and serve the new files.

### 12. Alert Plan / Tracker / News Must Be Dropdown-Driven, Not Hardcoded
The **Active Trade Plan**, **Forecast vs Actual Tracker**, and **Latest Catalyst & News** cards must be populated from the selected alert, not from a hardcoded ticker. Build a `<select id="alert-selector">` from `scan_results` entries that have a `plan` (status `ALERT` or `CANDIDATE`). Selecting an entry re-renders all three sections from that entry's `plan` and `news` fields.

See `references/website-multi-alert-selector.md` for the full pattern, HTML skeleton, JS helpers, backend JSON contract, and mobile CSS notes.

### 5. News Ticker Must Rebuild from scan_results AND Loop Seamlessly
Same pattern as table — the scrolling news ticker is NOT a separate feed; it mirrors `scan_results`. Because the CSS animation scrolls the container from `translateY(0)` to `translateY(-50%)`, the HTML must contain the news items **twice** (duplicated) so the animation resets to an identical frame and appears to loop forever. Do not insert only one copy — the loop will jump.

```python
news_content = '\n'.join(news_items)
looped_content = news_content + '\n' + news_content  # Required for seamless CSS loop
```

CSS:
```css
.news-ticker-scroll {
    animation: ticker-scroll 40s linear infinite;
}
.news-ticker-scroll:hover { animation-play-state: paused; }
@keyframes ticker-scroll {
    0% { transform: translateY(0); }
    100% { transform: translateY(-50%); }
}
```

### 6. Section-Scoped Regex (Never Global Class Search)
See `references/duplicate-content-prevention.md`.

### 7. Scan Stats in Badge (Market Context)
When no candidates pass filters, show WHY:
```python
badge_text = f'🟡 PRE-MARKET 07:15 AM ET | Scanned: 50 | 0 candidates | 0 alerts'
```
This tells the user the scanner is working, just found nothing actionable.

### 8. Always Pass `all_gainers` and `all_losers` to the Updater, and Mirror Them in JSON `scan_stats`

When zero candidates pass, still send the full list of 50 scanned gainers to the website so the dashboard can render a collapsible "Show all 50 scanned tickers with filter reasons" table.

For the A+B+C architecture, also pass the full annotated loser list (`all_losers`) and any bounce candidates (`bounce_results`). `website_updater.py` must:
1. Write top-level `all_gainers` / `all_losers` / `bounce_results` to the JSON.
2. Also write `all_gainers` and `all_losers` into the JSON `scan_stats` sub-dict. The HTML renderer (`_update_html`) reads from `scan_stats`, not from the top-level JSON, so if `scan_stats` lacks these keys the server-rendered sections will be empty even though the JSON contains the data.
3. Always emit the HTML marker containers for bouncers, scanned gainers, and scanned losers — never omit a section just because the current list is empty. Client-side `loadLiveData()` repopulates from JSON and needs a container to target.

The tables should display: ticker, name, price, change %, volume, RVOL, market cap, PASS/SKIP (or BOUNCE/SKIP) badge, and the exact filter reason.

See `references/website-scanned-losers-bounce-sections.md` for the full contract, marker order, label cleanup, and verification commands.

### 9. Red-Flag Text Must Be Full-Length
Do not truncate red-flag news headlines when building the `result` field. A truncated headline like `Red flags: offering:FREECAST INC FILES FOR OFFERING OF UP TO` is useless. Remove any `[:40]` slicing and store the full title.

```python
# WRONG
red_flag_strs = [f"{r.get('flag','')}:{r.get('title','')[:40]}" for r in red_flags]

# RIGHT
red_flag_strs = [f"{r.get('flag','')}:{r.get('title','')}" for r in red_flags]
```

### 10. Alert Date/Time Storage
Every `scan_results` entry must include `'date'` and `'time'` fields at creation time. The tracker reads these to show "when the alert triggered" instead of "when the page rendered." See `references/tracker-date-time-fix.md`.

## Reference Files

| File | Content |
|------|---------|
| `references/ahmed-khaled-cmt-strategy.md` | Original strategy notes |
| `references/ahmed-khaled-strategy.md` | Strategy reference |
| `references/asx-market-scan.md` | **ASX/Australian market scanning — verified endpoints, regionId=18, ASX-specific thresholds, data quirks** |
| `references/asx-tickerid-and-news-timestamps-fix.md` | **ASX per-symbol data via Webull `tickerId` + news age stamps on the website (June 2026)** |
| `references/au-filter-and-announcements-feed.md` | **AU scanner filter rules + reliable ASX announcements feed (June 2026)** |
| `references/au-limited-data-pipeline.md` | **ASX limited-data pipeline — synthetic quotes, single-bar TA, no live alerts** |
| `references/au-impact-label-and-website-sync-fix.md` | **AU scanner impact-label and rules-section sync fix (June 2026)** |
| `references/getting-started.md` | Config location, first-run, troubleshooting |
| `references/telegram-channel-setup.md` | Telegram channel setup guide |
| `references/cron-delivery-architecture.md` | How cron jobs and skill notifier interact — prevents duplicate emails |
| `references/duplicate-content-prevention.md` | **Website updater string replacement — section-scoped regex, never global class search** |
| `references/expired-state-last-data.md` | **Show last alert data dimmed instead of blank placeholders** |
| `references/getting-started.md` | Config location, first-run, troubleshooting |
| `references/javascript-countdown-performance.md` | **Countdown timer: never search inside setInterval, cache targets, Intl.formatToParts(), GitHub Pages cache gotchas** |
| `references/kill-switches-and-removal.md` | **Instant disable/remove recipe + Windows skill-path pitfall** |
| `references/multi-alert-card-design.md` | **Multi-alert card design with ticker badges** |
| `references/notification-routing-rules.md` | **Milestone/change-based notification routing — prevents Telegram/email spam from repeated scans** |
| `references/notifier-pitfalls.md` | Telegram HTML mode, token masking, channel ID `-100` prefix, Gmail App Password, duplicate alert prevention |
| `references/okx-api-integration.md` | OKX crypto sentiment configuration |
| `references/pre-market-health-check.md` | Pre-market / live trial health check checklist |
| `references/production-error-patterns.md` | Live error log, component status, fix timeline |
| `references/scanner-badge-table-fix.md` | Badge/table early fixes |
| `references/scanner-visibility-no-candidates.md` | **Showing all 50 scanned tickers + filter reasons when zero candidates pass; relaxed scanner defaults for Webull RVOL outage** |
| `references/stop-loss-rr-pitfall.md` | **Why raising `stop_loss_pct` to 3% collapses R:R to 1.00 and kills all alerts** |
| `references/atr-stop-rr-pitfall.md` | **Why ATR `min()` for US mode widened the stop and collapsed R:R (GDHG 1.10 case)** |
| `references/telegram-channel-setup.md` | Telegram channel setup guide |
| `references/tracker-date-time-fix.md` | **Alert date/time storage for tracker** |
- `references/website-alert-driven-plan-tracker-news.md` | **Full June 2026 fix: market-aware JSON, alert selector, no toggle auto-sync, scanner-table selector, GitHub Pages cache verification**
- `references/website-dynamic-sections-architecture.md` | **Dynamic sections: plan, tracker, news rendered from JSON by JS**
| `references/website-impact-labels-and-sorting.md` | **Impact badges, High→Low sorting, and GitHub Pages cache-bypass verification** |
| `references/website-live-json-refresh.md` | JSON refresh behavior |
| `references/website-market-countdown.md` | Market countdown timer implementation |
| `references/website-market-status-tracker-premarket.md` | **AU market status staleness, $100 tracker investment, nearest whole-share qty, T1/T2/T3 executed P&L, persistent pre-market watchlist** |
| `references/website-market-toggle-aus.md` | **US/AUS market toggle on the website, ASX hours, user-choice persistence, no forced backend sync, market-aware JSON fetch regression, scanned-details id pitfall** |
- `references/website-aus-scanned-tickers-us-fix.md` | **Session fix: AUS scanned tickers showing US list because of hardcoded JSON fetch + missing details id** |
| `references/ozmoeg-website-emergency-rollback.md` | **How to roll back the deployed trader HTML to the last truly good commit when a "fix" breaks the live site** |
| `references/website-defensive-patterns-and-source-recovery.md` | **Front-end safety nets (leaked red-flag sanitizer, view mutual exclusion, JSON-anchored countdown, alert-selector consistency, tracker basis) and how to recover when scanner Python source is missing** |
| `references/cron-delivery-architecture.md` | **Cron job `deliver: local` architecture — stops Hermes "Cronjob Response" emails** |
| `references/sidu-dict-join-error-debug.md` | **SIDU "sequence item 0: expected str instance, dict found" — stale-data trap after rollback + defensive NewsMonitor market fix** |
| `references/website-mobile-responsive.md` | **Mobile-responsive breakpoints: desktop preserved, mobile stacked. Includes CSS specificity pitfall with `!important` fix** |
| `references/website-multi-alert-selector.md` | **Multi-alert trade plan/tracker/news dropdown pattern — replaces hardcoded single ticker** |
| `references/website-pre-market-toggle.md` | **Pre-market/after-hours watchlist as a toggle inside the scanner card, with timestamp** |
| `references/website-refresh-timer-and-toggle-reload-fix.md` | **Refresh countdown must anchor to JSON `last_updated`, and Live/Pre/After toggle must not trigger a network reload** |
| `references/website-scanner-data-freshness.md` | **Prevent "stuck with old values" — refresh behavior, toggle state, badge timestamp, ASX cron window, absolute JSON URL** |
| `references/website-scanner-json-fetch-absolute-url.md` | **Use absolute JSON fetch URL to avoid silent 404s on GitHub Pages with query strings** |
| `references/website-trading-monitor.md` | Trading monitor design |
| `references/website-updater-markers.md` | **Marker-based HTML replacement system — no regex, no layout breakage** |
| `references/zero-trigger-premarket-diagnosis.md` | **Diagnosing why the US pre-market scan returns 0 candidates / 0 alerts** |
| `references/website-updater-markers.md` | **Marker-based HTML replacement system — no regex, no layout breakage** |
| `references/webull-api-quickref.md` | Webull API quick reference |
| `references/webull-browser-auth.md` | Playwright browser automation attempt — blocked by geo popups and click interception |
| `references/webull-desktop-token-extraction.md` | Webull Desktop app inspection — Qt/Chromium hybrid, no plaintext API keys, practical extraction options |
| `references/webull-openapi.md` | Webull official OpenAPI details |
| `references/webull-rvol-computation.md` | **Why RVOL shows 0.0x and how to compute it from avgVol10D** |
| `references/webull-stop-loss-bracket-rules.md` | **Webull bracket-order 0.1% rule, why -2% can still fail, and OzMoEg guardrails** |
| `references/webull-us-api-gotchas.md` | **CRITICAL: Webull login broken (June 2026). 403 Illegal Client. Public data still works. Official OpenAPI DNS-fails from non-AU IPs.** |
| `references/webull-float-fields.md` | **Webull `outstandingShares` as free-float proxy, float-based filter implementation notes** |
| `references/webull-country-origin-fields.md` | **Webull `issuerRegionId` → origin country mapping, surfaced as a badge next to ticker name** |
| `references/proposed-us-hyper-scalp-filters.md` | **Deployed US scanner filter values and rationale (A+B+C era)** |
- `references/abc-filter-architecture.md` | **A+B+C filter architecture: momentum tiers, tiny-cap gate, bounce scanner, website layout order, updater-driven HTML rules, and cache-bypass verification**
- `references/github-pages-cache-staleness.md` | **GitHub Pages / Fastly CDN stale-cache verification after website pushes**
- `references/backup-data-sources.md` | **Backup US stock data sources: Yahoo Finance zero-config + Alpaca key-configured redundancy**
- `references/video-position-sizing-formula.md` | **Ahmed Khaled CMT "golden triangle": fixed $R risk, shares = R / stop distance, R:R-based targets (June 2026)**
| `templates/config-template.yaml` | Ready-to-fill config template |

## Pre-Market / Live Trial Health Check
Before the first live market trial or whenever the user says "market opens soon — health check everything," follow the checklist in `references/pre-market-health-check.md`.

Key points:
1. **Gateway must be running** — `hermes gateway start` if needed. Cron jobs won't fire without it.
2. **The 15-minute market scanner cron must exist** — recreate it if missing (`*/15 * * * 1-5`).
3. **Run one manual scan** via `python main.py` to verify Webull data + website update + git push.
4. **Verify live website** shows the latest scan timestamp (use `?v=<timestamp>` to bypass GitHub Pages cache).
5. **Send a Telegram test message** to confirm bot + channel ID.
6. **Confirm paper mode is still true** and risk settings are safe before market open.
The **Duplicate prevention** section now mentions the 6-hour window and the Telegram quality gate. The **Live News Stream** section points to the new reference. The **Latest Catalyst & News section** also uses recomputed ages; see `references/website-weekend-toggle-and-news-catalyst.md` and `references/news-age-recompute-from-raw-timestamp.md`.

## Latest Catalyst & News — Consistent Age Recomputation

The **📰 Latest Catalyst & News** card lists the top scored headlines for the selected alert. Like the scanner table and live ticker, each headline's age badge must be recomputed from its `raw_time` timestamp, not the saved `time` string. If the age is rendered from the stored `time` field, a headline from 26 Jun can still read "57m ago" three days later.

Implementation in `ozmoeg-trader.html`:

```javascript
list.innerHTML = headlines.map(h => {
    const s = h.score || 0;
    const scoreClass = s >= 4 ? 'impact-high' : (s >= 2 ? 'impact-medium' : 'impact-low');
    // Recompute age from raw timestamp so saved snapshots stay accurate.
    const age = computeNewsAge(h.raw_time) || (h.time || '');
    const isVeryStale = /^(\d+mo|\d+y|\d+d)\s+ago/.test(age) && (
        /^(\d+mo|\d+y)\s+ago/.test(age) ||
        (age.match(/^(\d+)d\s+ago/) && parseInt(age.match(/^(\d+)d\s+ago/)[1]) > 7)
    );
    const staleClass = isVeryStale ? 'news-age stale' : 'news-age';
    const staleEmoji = isVeryStale ? '⚠️ ' : '';
    const rawIso = h.raw_time || '';
    const titleTip = rawIso ? ` title="First published: ${escapeHtml(rawIso)}"` : '';
    const timeHtml = age ? `<span class="${staleClass}"${titleTip}>${staleEmoji}${escapeHtml(age)}</span> ` : '';
    return `<li>${timeHtml}<span class="score ${scoreClass}">[${s}]</span> <a href="${escapeHtml(h.url)}" target="_blank" rel="noopener">${escapeHtml(h.title)}</a> <em>${escapeHtml(h.source || '')}</em></li>`;
}).join('');
```

See `references/news-age-recompute-from-raw-timestamp.md` for the full backend/frontend recipe and verification commands.

## Website Features

### Market‑Toggle Persistence Pitfall
- The OzMoEg Trader page stores the selected market (`US` or `AUS`) in the browser's `localStorage` under the key **`ozmoeg-market`**. If a user previously selected **US** and then leaves the page, the next visit will automatically load the US JSON (`ozmoeg‑latest.json`) even when the ASX is closed. This leads to the confusing situation where the header reads *“ASX Small‑Cap Monitor — Off‑Market”* but the scanner badge still shows *“🟢 US … Scanned: 50 candidates”*.
- The JavaScript deliberately does **not** auto‑switch the toggle based on backend data (`scan_stats.market`) because the toggle is a user preference. However, when the market changes (e.g. after hours) users often expect the UI to reflect the current market without manually clicking the button.

**Resolution steps**
1. **Manual fix** – Click the 🇦🇺 AUS button in the top‑right corner. The badge and table will reload using `ozmoeg‑latest‑au.json` and display the correct 15 AU entries.
2. **Automatic suggestion** – Add the following tiny script block just before the closing `</script>` tag (or inject via the console) to auto‑select AUS during ASX trading hours while still respecting a manual override:
   ```html
   <script>
   (function(){
       const now = new Date();
       const sydney = new Intl.DateTimeFormat('en-AU',{timeZone:'Australia/Sydney',hour:'numeric',weekday:'short'}).formatToParts(now);
       const hour = parseInt(sydney.find(p=>p.type==='hour').value);
       const weekday = sydney.find(p=>p.type==='weekday').value;
       const isWeekday = !['Sat','Sun'].includes(weekday);
       const isOpen = isWeekday && hour>=10 && hour<16;
       if(isOpen && localStorage.getItem('ozmoeg-market')!=='AUS'){
           localStorage.setItem('ozmoeg-market','AUS');
           location.reload();
       }
   })();
   </script>
   ```
   *What it does*: Detects Sydney time; if the ASX is currently open and the stored market is not AUS, it forces the toggle to AUS and reloads the page so the correct JSON is fetched.
3. **Long‑term fix** – Update `ozmoeg-trader.html` to include the script permanently (see `references/website-market-toggle-bug.md`). This eliminates the mismatch for all future sessions.

### Why this matters
- Prevents the misleading *“US 50‑ticker”* list from appearing on an off‑market AUS page.
- Guarantees that the scanner badge always matches the displayed market, preserving user trust.
- Aligns the UI with the user‑experience expectations described in the skill’s *Website Features* section.

**Reference added** – `references/website-market-toggle-bug.md` documents the bug, the script, and the steps for permanent integration.

---
## Website Features
...

### Market Countdown Timer
A live countdown card on the website (under Session card) shows:
- **Region label:** **🇺🇸 US Market** or **🇦🇺 AUS / ASX Market** depending on the selected market mode
- **Status text:** 🟢 Market OPEN / 🟡 After Hours / 🟡 Pre-Market / 🔴 Weekend (US) or 🟢 ASX Open / 🔴 ASX Closed (AUS)
- **Large countdown timer:** Live updating every second (e.g., `2d 10:00:03`)
- **Next open time:** Converted to AEST for Melbourne users

**JavaScript logic:** `updateCountdown()` checks the selected market (`currentMarket`, persisted in `localStorage` under `ozmoeg-market`). For US mode it uses ET timezone via `toLocaleString("en-US", {timeZone: "America/New_York"})`. For AUS mode it uses Sydney timezone and ASX hours (10:00–16:00 Mon–Fri). It handles weekend skipping (Sat→Mon, Sun→Mon), after-hours weekday skipping, and pre-market countdown.

See `references/website-aus-scanned-tickers-us-fix.md` for the session fix that added the market-aware JSON fetch and the `id="scanned-all-details"` attribute.

### Emergency Rollback to a Known-Good HTML Commit

Sometimes a deployed "fix" makes the live site worse than the original. When that happens, the fastest safe recovery is to reset `main` to the last commit that was **verified working**, force-push, and then re-verify the live source after the CDN cache clears.

**Critical pitfall:** routine data-update commits (e.g., "Update OzMoEg scan results") can stack on top of a broken refactor and inherit the broken structure. Do not assume the most recent non-fix commit is clean. Inspect the file for structural markers. Also, a commit that the user *thinks* was good (e.g., `6cb6ecd`) may already contain the rejected layout — always verify markers, not memory.

**Two breakage patterns to avoid:**
1. The static `scanned-details` filter table ("filter next to the scanner results") appears around 2023 lines starting at `6cb6ecd`.
2. The client-side JSON live-refresh refactor appears later with `id="scanned-all-details"` and `fetch('ozmoeg-latest.json...')`.

**Known-good rollback target in this repo:** `96d4f8b Restore clean HTML base before updater rewrite` (879 lines, no filter table, no JSON fetch).

**Commands:**
```bash
cd /c/Users/openclaw/Desktop/aeyeing.com

# Find the truly clean commit before both breakage patterns
git log --oneline --all --reverse | grep -i "restore clean html base"
git show 96d4f8b:ozmoeg-trader.html | grep -nE 'scanned-all-details|ozmoeg-latest\.json|fetch\(|scanned-details|filter reasons'

# Roll back and force-push
git reset --hard 96d4f8b
git push --force origin main
```

Verify the live source with a cache-busting URL after the push:
```bash
curl -sL "https://aeyeing.com/ozmoeg-trader.html?nocache=$(date +%s)" | grep -cE 'scanned-all-details|ozmoeg-latest\.json|fetch\('
# Expected: 0
```

If the user asks to revert "today and yesterday" and there are no commits in that window, explain the gap in the history and fall back to the last verified clean commit.

See `references/ozmoeg-website-emergency-rollback.md` for the full recipe, corrected commit map, and pitfall notes.

### Website Market Toggle (US / AUS)
The website header contains a segmented toggle that lets the user switch between US and AUS market views. The toggle:
- Persists the selection in `localStorage` (`ozmoeg-market`).
- Updates the subtitle, countdown label, market status, countdown target, scanner badge, scanner table, and news ticker immediately.
- **Does NOT auto-sync to `scan_stats.market`.** The badge/table reflect the backend data source, but the user's toggle choice is respected even when the live JSON's `stats.market` differs.
- **Renders live backend data for both markets.** AU mode shows `CANDIDATE`-status rows with 3-decimal prices and a clear data-limited warning; it no longer shows a hardcoded "ASX feed not connected" placeholder.

**Selector pitfall (June 2026):** The refresh code that rebuilds the "Show all 50 scanned tickers" details table must use a selector that matches the deployed HTML. Some bases use `id="scanned-all-details"`; the rolled-back `d6a51cc` base uses only `class="scanned-details"`. If the selector returns `null`, the table stays stale and the AUS toggle continues to display the US scanned list. Use `document.querySelector('details.scanned-details')` when the id is absent.

### Live/Pre/After toggle

The scanner card contains a second toggle for **📊 Live** vs **🌅 Pre/After** views. Like the market toggle, it must:
- Persist the user’s chosen view in `localStorage` (e.g., `ozmoeg-scanner-view`).
- Update only the displayed dataset and badge; it must **not** force a `location.reload()` on every click (that breaks the current-price countdown and forces a full CDN refetch).
- Auto-default to **🌅 Pre/After** when the US market is in PRE-MARKET / AFTER-HOURS / CLOSED-WEEKEND and a saved watchlist exists.
- Auto-default to **📊 Live** during US regular hours or when AUS is selected.
- Keep `displayedResults` in sync with the active view so the alert selector, trade plan, tracker, and catalyst/news sections all render the same ticker context.

### JavaScript syntax integrity in the generated template

`website_updater.py` regenerates `ozmoeg-trader.html` on every scan from an inline HTML template. If the template contains a duplicate `const`/`let` declaration or other JS syntax error, the entire main `<script>` block fails to parse. The symptom is a "broken" page: market toggles, Live/Pre/After toggle, countdown timer, alert selector, and tracker all become unresponsive. The server-rendered HTML still displays stale rows, so the user may see AU tickers under the US button, missing bouncers/losers sections, or empty P&L boxes.

**Always verify JS syntax after editing the template and before running the scanner.** A broken template will be pushed live on the next scan. Use the Node.js probe:

```bash
cd ~/Desktop/aeyeing.com
node -e "try { const src = require('fs').readFileSync('ozmoeg-trader.html','utf8').match(/\u003cscript\u003e([\\s\\S]*?)\u003c\\/script\u003e/)[1]; new Function(src); console.log('JS OK'); } catch(e){ console.log('JS ERROR:', e.message); }"
```

Common mistakes:
- Duplicate `const allGainers` / `const allLosers` declarations after merging two code blocks.
- Mismatched template-literal backticks or unescaped `$` in generated text.
- Overly deep indentation from copy-pasted patches (e.g., 24-space indented statements inside a 12-space function body).

See `references/website-js-syntax-error-breaks-toggles.md` for the duplicate-`allGainers` incident and the fix.

**Reference added 2026-07-02** — `references/website-no-candidates-flood-regression.md` documents why the main table and news ticker can flood with 50 SKIP rows when no candidates pass, and the multi-layer fix in `main.py`, `website_updater.py`, and the client script.

See `references/website-pre-market-toggle.md` for toggling between Live / Pre-After views and preserving selected alerts.

See `references/website-multi-alert-selector.md` for the alert dropdown pattern that drives the trade plan, tracker, and catalyst/news sections.

See `references/website-alert-driven-plan-tracker-news.md` for the full June 2026 fix pattern — market-aware JSON fetch, no toggle auto-sync, scanner-table selector, refresh label, and honest current-price placeholder.

See `references/website-aus-scanned-tickers-us-fix.md` for the session fix that corrected the market-aware JSON fetch and the scanned-details selector mismatch.
When no alert is active, the trade plan and tracker cards show:
- Last alert ticker, name, trigger date/time at 40% opacity (from JSON history)
- Entry, stop, targets, shares, position value dimmed — NOT blank `—`
- **📋 Rules / Filters Applied** section always visible (dimmed, with checkmarks)
- **⏱ Exit Strategy** section always visible (dimmed, with bullet points)
- Dimmed via `opacity: 0.4` on the grid + rules sections

See `references/expired-state-last-data.md` for full implementation.
### Forecast vs Actual Tracker

- **Proposed Entry** must be the **previous scan's live quote price**, not the current scan price or the plan entry.
- **Current Price** must be the **current scan's live quote price**.
- Implement this by having `website_updater.py` preserve the prior scan's `live_quotes` and ship them in the JSON as `previous_live_quotes`. The client should prefer `data.previous_live_quotes`; browser `localStorage` is only a fallback.
- Tracker P&L = (current price − previous price) × share quantity. Display a waiting state when both timestamps are identical (first cycle after fix / no prior quote).
- Refresh cadence: 15 minutes default, 5 minutes during the user's active trading window (Sydney/Melbourne 18:00–22:30, US pre-market). Show a red glow / `⚡` indicator during active mode.

## Country Badge Bubbles

- Render country as a small CSS pill/badge next to the ticker/Name field in:
  - main scanner table (`ticker-cell`)
  - news ticker/stream (`.news-item` / `.news-ticker-symbol`)
  - tracker header and catalyst header
- The base `.country-badge` rule can be standard size/color; the **news stream** badge should be smaller and lighter (`font-size: 0.5rem`, translucent blue background, soft blue text). Use `!important` if CDN cache or selector ordering causes the override to be ignored.

## Common Pitfalls

1.  **Duplicate `const` declaration in inline script:** once caused a `SyntaxError` that broke the entire page (toggles, tracker, etc.). Always run a Node.js parse check on the inline `<script>` after editing.
2.  **News ticker flooded with SKIP rows:** the no-candidates path in `main.py` used to pass all 50 annotated gainers as `scan_results`. Patched to pass empty results; both server and client now filter to `status in ('ALERT', 'CANDIDATE', 'BOUNCE')`.
3.  **50 scanned losers/gainers section disappears:** ensure `website_updater.py` echoes `all_gainers` and `all_losers` into `scan_stats` and always emits the `<details>` containers even when empty.
4.  **GitHub Pages CDN cache:** verify with `?_nocache=N`; stale HTML can persist several minutes after push. Use `!important` on critical CSS overrides when cache propagation is unreliable.
5.  **Impact labels out of sync:** `website_updater.py` and client `getAlertMaxScore()` should use `result['news']['max_score']`; recompute from headline scores only when missing.
6.  **Tracker shows identical previous/current prices:** the browser cannot know the prior scan's price from `localStorage` until one full refresh cycle passes. Fix at the source: ship `previous_live_quotes` from the backend JSON.

## Verification Checklist

- [ ] Run US scan and confirm `ozmoeg-latest.json` has `scan_results`, `all_gainers`, `all_losers`, `bounce_results`, `live_quotes`, **and `previous_live_quotes`**.
- [ ] Open `https://aeyeing.com/ozmoeg-trader.html?_nocache=<N>` and confirm sections render.
- [ ] Toggle Live / Pre/After and confirm no console errors.
- [ ] Check Telegram channel did not receive duplicate alerts for the same ticker within 6 hours.
- [ ] Commit/push `ozmoeg-trader.html` and `website_updater.py` after any HTML/JS/layout fix that must survive regeneration.
- [ ] Inspect the news-stream country badge in the browser; verify it is smaller and lighter than the main table badge.
- [ ] Confirm tracker Proposed Entry timestamp differs from Current Price timestamp and P&L is non-zero when price moved.

## Testing Checklist

Before going live, verify:
- [ ] Paper trade 20+ setups with >60% win rate
- [ ] Stop losses trigger automatically
- [ ] Telegram alerts arrive in channel within 5 seconds
- [ ] Email reports send correctly
- [ ] PDT tracker works accurately
- [ ] Position sizing never exceeds 25% of account
- [ ] No trades during 11 AM–2 PM chop
- [ ] News confirmation from 2+ sources works
- [ ] Demand zone detection is accurate on historical charts
- [ ] Website monitor at aeyeing.com/ozmoeg-trader.html loads correctly

## Current Status (June 2026)

| Component | Status |
|-----------|--------|
| Scanner (public data) | ✅ Working |
| Trade plan generation | ✅ Working |
| Telegram channel alerts | ✅ Working (sole communication method) |
| Email daily reports | ❌ Disabled by default |
| Website monitor | ✅ Deployed |
| OKX sentiment | ✅ Enabled |
| Webull login | ❌ Broken (403 Illegal Client) |
| Webull order placement | ❌ Unavailable (login broken) |
| Webull official OpenAPI | ❌ Non-AU networks cannot resolve endpoints |
| Cron jobs | ✅ 3 active |
| AU mode | ⚠️ Research-only from non-AU networks — synthetic quotes, no live alerts |
| Backup US data source | ✅ Yahoo Finance active; Alpaca ready when keyed |

## Post-June-2026 Fixes and Pitfalls

This section captures hard-won corrections discovered during live AU/US toggle work. Read before modifying `trade_planner.py`, `main.py`, `config.yaml`, or the website JS.

### AU Scanner Filter Rules & ASX Announcements Feed (June 2026)

The original AU pipeline inherited US scanner thresholds (`price_min: 0.50`, `market_cap_min: $25M`), which caused every genuine ASX micro-cap to be filtered out with reasons like "price $0.022" or "mktcap $3.2M". The fix was to add a dedicated `scanner.au` block and load those overrides only when `market == 'au'`.

A reliable ASX catalyst source was also added: the **ASX Research API** at `https://asx.api.markitdigital.com/asx-research/1.0/markets/announcements`. It accepts `symbols=A,B,C` and returns today's ASX announcements, including the `isPriceSensitive` flag. The pipeline batch-fetches all 50 scanned tickers, merges announcements into news scoring, and confirms the catalyst when a price-sensitive item exists. AU candidates remain `CANDIDATE` status because intraday bars are still unavailable.

See `references/au-filter-and-announcements-feed.md` for the exact config block, code pointers, and verification recipe.

### AU Scanner Filter Rules & ASX Announcements Feed (June 2026)

The original AU pipeline inherited US scanner thresholds (`price_min: 0.50`, `market_cap_min: $25M`), causing every genuine ASX micro-cap to be filtered out. A dedicated `scanner.au` block was added with ASX-specific thresholds (`price_min: 0.001`, `market_cap_min: $1M`, `premarket_pct_min: 8%`, etc.).

A reliable ASX catalyst source was also integrated: the **ASX Research API** at `https://asx.api.markitdigital.com/asx-research/1.0/markets/announcements` returns today's announcements with an `isPriceSensitive` flag, allowing real catalyst confirmation without blocked Webull news endpoints.

See `references/au-filter-and-announcements-feed.md`.

### AU Scanner Impact Label & Website Rules Sync (June 2026)

After the ASX filter fix, the website still showed:
- `CANDIDATE` rows with a **Medium** impact badge because the backend inflated `max_score` to 3 for every limited-catalyst row.
- The **📋 Rules / Filters Applied** section stuck on US values when AUS was selected.
- "data limited" on every result, even when a real ASX announcement existed.

The fix:
- Backend distinguishes `au_state: 'AU-LIMITED'` vs `'AU-ANNOUNCEMENT'`, stops inflating `max_score`, and exposes `scan_stats.au_filters`.
- Frontend `impactLabel(score, r)` returns a **🇦🇺 AU-LIMITED** amber badge for limited-catalyst rows.
- `renderPlanRules(r)` dynamically populates `#plan-rules-list` from `window._lastScanStats.au_filters` in AUS mode.

See `references/au-impact-label-and-website-sync-fix.md`.

### NewsMonitor Must Receive the Active Market

`main.py` constructs `NewsMonitor(wb, config.get('news', {}))` before running the scanner. If the `news:` block does not contain `market`, `news_monitor.py` may default to US behavior even when `--market au` was passed. This can cause the ASX announcements fetch to be skipped, or worse, cause US-shaped headline objects to flow into code paths that expect strings, producing errors such as:

```
TypeError: sequence item 0: expected str instance, dict found
```

The exception is then surfaced on the website as the literal text `Error: sequence item 0: expected str instance, dict found`.

Always inject the active market:

```python
news_cfg = dict(config.get('news', {}))
news_cfg['market'] = market
news_mon = NewsMonitor(wb, news_cfg)
```

And do the same for the CLI `--market` override path:

```python
if args.market:
    config['scanner']['market'] = args.market
    config['scanner']['region_code'] = 18 if args.market == 'au' else 6
    config['webull']['region_code'] = config['scanner']['region_code']
    config['webull']['market'] = args.market
    config.setdefault('news', {})['market'] = args.market
```

After any rollback, verify the deployed JSON no longer contains the literal error string and run a targeted single-ticker scan with website updates disabled to prove the code path is clean.

See `references/sidu-dict-join-error-debug.md` for the full incident and verification recipe.

### Webull Region Codes (Verified)

| Market | `region_code` | How verified |
|--------|---------------|--------------|
| US | **6** | Raw `webull(region_code=6).active_gainer_loser()` returns US tickers |
| AU / ASX | **18** | Raw `webull(region_code=18).active_gainer_loser()` returns ASX tickers |
| 5 | Japan/TSE | Mistakenly documented as US; returns TSE-style tickers |

**Config rule:** `scanner.region_code` is the source of truth. `main.py` copies it into `config['webull']['region_code']` before instantiating `WebullClient`. Do NOT rely on the `webull:` block `region_code` alone.

### AU Trade Planner — Synthetic ATR Stop Pitfall

`trade_planner.py` originally computed:
```python
min_stop = entry_price * 0.99
stop = max(synthetic_atr_stop, min_stop)
```
For sub-$1 ASX prices, `min_stop` is only 1% below entry while T1 is 3% above, so R:R collapses to exactly 1.50 for every candidate regardless of ATR.

**Fix:** In AU mode, skip the 1% floor and use the ATR-derived stop directly. With a synthetic ATR of ~1.3% of price, AU candidates produced R:R ≈ 4.62 in testing.

### US Off-Market Relaxation (Pre-Market / After-Hours)

When the US market is closed, headline flow is thin. If the scanner requires the same `min_score: 3` and `confirmation_sources: 2` as regular hours, every candidate fails news scoring. The fix:
- Outside market hours, lower `min_score` to `2` and `confirmation_sources` to `1`.
- Also bypass the demand-zone / candlestick gate when `catalyst_relaxed` is true, because intraday bars are too thin to form demand zones pre-market.
- Set `confidence = "LOW"` (or "MED") for these relaxed setups so the user knows TA confirmation is weaker.

This is intentionally scoped to off-market hours — do NOT weaken the rules during regular hours.

### US Regular-Hours Catalyst Gate (Small-Cap News Blackout)

During **US regular hours**, real-time small-cap catalyst headlines are often blocked or stale because of exchange/news-vendor rules. Requiring a fresh catalyst score ≥ 3 during market open will filter out nearly all legitimate runners and leave the scanner silent. The fix:
- During US market hours, relax the catalyst gate so the technical/momentum filters can still produce research setups.
- Use the pre/after-hours headline from `pre_market_results` as the reference catalyst.
- Set `confidence = "LOW"` and add a clear warning label: the user must verify the catalyst independently before acting.
- Keep hard red-flag detection active (dilution, offering, bankruptcy, etc.) — these still skip the ticker.

This relaxation is separate from the off-market relaxation above; both are needed because the available data differs by market phase.

### Extended-Hours Trade Plan Rebase and Sizing (June 2026)

When the US market is in **PRE-MARKET** or **AFTER-HOURS**, the scanner's stored trade plan is usually built from the prior regular-session close price (e.g., GETY $0.6051). That price is not fillable in extended hours because the live quote has already gapped (e.g., GETY $1.34). Displaying the stale close plan as the "Active Trade Plan" misleads the user into placing an order that will never execute at the quoted entry.

**Fix:** rebase the plan in the website frontend to the live pre/after-hours price whenever `currentMarketStatus` is `PRE-MARKET` or `AFTER-HOURS` and a live quote is available.

Rules:
1. **Entry basis:** use `live_quotes[ticker].price` (Webull `pprice`) when present; otherwise fall back to a public quote; otherwise keep the original close entry.
2. **Preserve geometry:** compute stop, T1, T2, T3 as the same percentage distances from the new live entry as the original plan had from the close entry.
   ```javascript
   const stopPct = (rawStop - rawEntry) / rawEntry;
   stop = liveEntry * (1 + stopPct);
   // repeat for t1Pct, t2Pct, t3Pct
   ```
3. **Sizing depends on `video_sizing`.**
   - **Video formula enabled (default):** `shares = max(1, round(R / stop_distance))` where `R = plan.risk_amount`. This keeps risk fixed, so the position value scales with the tighter/looser stop.
   - **Legacy mode:** `shares = max(1, Math.round(test_trade_dollars / liveEntry))` and `position = shares * liveEntry`. This keeps the position value near the configured test amount.
4. **Label the rebase clearly.** Add an exit-rule bullet in amber: *"⚠️ Live pre/after-market rebase: original close plan was $0.6051 → $1.34"*.
5. **Track live basis honestly.** The tracker subtitle should read *"Live pre/after-hours basis"* so the user knows the entry, P&L targets, and current-price comparison all use the live extended-hours quote.
6. **Tracker basis must be the scan basis, not the live entry.** If the tracker uses the rebased live entry as "Proposed Entry," P&L is zero on every fresh load. Use the original close price as the tracker basis so P&L reflects movement since the alert was generated.
7. **Tracker basis must be the last-refresh live price, not the original close.** If the tracker uses the prior regular-hours close ($0.6051) as the basis, the P&L becomes a static gap-up number that never changes between refreshes. Use `live_quotes[ticker].price` from the last JSON refresh as the tracker basis so P&L tracks live pre/after-market drift between refreshes.
8. **Regular-hours fallback.** Outside extended hours, render the original close-based plan unchanged.

See `references/website-extended-hours-trade-plan-rebase.md` for the full JavaScript implementation (`resolveLiveEntryPrice`, `isExtendedHoursSession`, `renderSelectedAlert` changes) and the GitHub Pages cache-bypass verification recipe.

### Telegram Token Validation

The skill masks the bot token in `config.yaml` as `8985575808:***`. If the real token is missing or invalid, Telegram API returns `404 Not Found` (not a clearer auth error). Always verify with:
```bash
curl https://api.telegram.org/bot<TOKEN>/getMe
```
If `getMe` returns `{"ok":false,"error_code":404}`, the token is bad. Email alerts may still work, but Telegram will silently fail in the logs.

### Website Market Sync

The website header subtitle and market toggle must follow **the user's choice**, not just whatever `scan_stats.market` says in `ozmoeg-latest.json`. The badge and scanner table can (and should) derive labels from the backend market, but calling `switchMarket(marketFromData)` inside `loadLiveData()` whenever it differs from `currentMarket` will snap the toggle back against the user's selection. Only update the badge label; never overwrite `currentMarket` from live data. Persist the user's choice in `localStorage` under `ozmoeg-market`.

If the user wants the toggle to track the backend market automatically, make that a separate opt-in setting (e.g., `auto-market-sync: true`) and clearly label it; do not make it default.

### Pre-Market / After-Hours Watchlist Toggle

Do **not** add a full separate "Pre-Market Watchlist" section above or below the live scanner table. The user experience is cleaner as a toggle inside the scanner card header:
- Add a toggle group next to the "📊 Scanner Results" heading with two buttons: **📊 Live** and **🌅 Pre/After**.
- Both views render into the **same scanner table**. Live shows the current market scan; Pre/After shows the saved `pre_market_results` array from the JSON.
- Display a **timestamp** next to the toggle, e.g. "15 saved rows from 17 June, 04:20 pm", so the user knows when the saved watchlist was captured.
- **Show the Pre/After button only when it offers a different dataset.** Hide it during US PRE-MARKET (the current pre-market scan *is* the live scan, so the two views would be identical and appear "stuck"). Show it during US AFTER-HOURS (Live is empty, Pre/After shows the after-hours watchlist) and during US OPEN when a saved pre-market watchlist exists (Live = regular-hours scan, Pre/After = pre-market snapshot). For AUS, hide Pre/After entirely — ASX has no extended session.
- Auto-switch the toggle to match market state: **🌅 Pre/After** for US PRE-MARKET/AFTER-HOURS, **📊 Live** for US OPEN or AUS. Respect the user's manual toggle choice across auto-refreshes; only auto-switch on the first load or when the saved preference is invalid.
- Reset the toggle back to **Live** whenever the user switches market (US ↔ AUS), then let the live-data refresh auto-select the correct view.
- Save the watchlist in the JSON via `website_updater.py` by preserving `pre_market_results` across regular-hours scans. Overwrite it when the current scan status is `PRE-MARKET` **or** `AFTER-HOURS`, so both pre-market and after-hours snapshots are captured. Do NOT overwrite it with an empty array during a regular-hours scan.
- **Critical consistency rule:** the alert selector, active trade plan, Forecast vs Actual tracker, and Latest Catalyst & News sections must all read from the same data source as the currently displayed scanner table. Use a `displayedResults` variable that follows the active toggle view; do not let `renderSelectedAlert()` keep reading `liveResults` when the table is toggled to Pre/After. If you skip this, the plan/tracker will show dashes or the wrong ticker when Pre/After is selected.
- **Critical distinct-view rule:** during US PRE-MARKET / AFTER-HOURS, **📊 Live** must show an empty-state message explaining that regular-hours data is not available, not the same rows as **🌅 Pre/After**. If the current scan is PRE-MARKET, `scan_results` and `pre_market_results` may be identical, so the **📊 Live** view must explicitly display the "market is pre-market/after-hours" empty state and direct the user to **🌅 Pre/After**. Otherwise the two views look identical and the toggle appears broken.
- **Implementation pitfall:** `renderScannerView()` must branch with `if (isPre) { ... } else { ... }`. If the pre-market block is followed by the live-view block without an `else`, the live-view code will always execute and overwrite the pre-market table with the empty-state message, making the Pre/After toggle appear blank.
- **Data-freshness rule:** the "⟳ Refresh Now" button must call `loadLiveData()` (fetch fresh JSON) instead of `location.reload()`. Auto-refresh interval must match the displayed label (use 1 minute and label it "Auto-refresh: 1 min"; do not claim 15 min while refreshing every 60 seconds or vice-versa). Add the last-scan timestamp to the scanner badge so users can verify freshness at a glance, e.g. `... | 12 alerts · updated 17 June, 05:18 pm`.
- **JSON fetch URL rule:** use an absolute base URL derived from `window.location` for the JSON fetch, not a bare relative filename. Relative URLs can break when the page is loaded with query strings and silently return 404 HTML, which leaves `_lastPreMarketResults` empty and the Pre/After view blank.
- **ASX cron window:** extend the AU scanner cron to run until 16:30 Sydney time (`*/15 10-16 * * 1-5`) so the market CLOSED status is captured after the 16:00 ASX close. Stopping at 15:45 leaves the JSON showing `OPEN` after close.
- **Position sizing rule:** the trade plan and tracker must target the user's configured `test_trade_dollars` amount (e.g., $100) by computing `shares = max(1, round(test_trade_dollars / entry_price))`. Do not size off `account_balance × max_position_pct` unless the user explicitly asks for larger test allocations.
- **Market-cap config rule:** ensure `scanner.market_cap_min` in `config.yaml` matches what the website claims. If the page says "$300M–$2B" but `config.yaml` has `market_cap_min: 1000000`, micro-caps such as OBAI ($27.2M) will pass the filter and confuse the user. Keep displayed text and config in sync.

See `references/website-pre-market-toggle.md` for the complete implementation, including `displayedResults`, `setScannerToggleActive()`, and the alert-selector change listener.

### Weekend / Closed Session — Default to Pre/After Watchlist

On weekends or when the US market is `CLOSED`, the saved pre-market/after-hours watchlist is the only actionable dataset. The scanner page should **not** boot into **📊 Live** and show an empty "market closed" table. Instead, it should default the toggle to **🌅 Pre/After** when a saved watchlist exists.

Implementation in `loadLiveData()`:

```javascript
const isUsExtendedHours = currentMarket !== 'AUS' && (marketStatus === 'PRE-MARKET' || marketStatus === 'AFTER-HOURS');
const isUsClosedWithWatchlist = currentMarket !== 'AUS' 
    && (marketStatus === 'WEEKEND' || marketStatus === 'CLOSED')
    && preMarketResults.length > 0;
if (isUsExtendedHours || isUsClosedWithWatchlist) {
    setScannerToggleActive('premarket');
} else {
    setScannerToggleActive('live');
}
```

This only affects the **initial** toggle state; the user can still switch manually. AUS is unaffected.

See `references/website-weekend-toggle-and-news-catalyst.md`.

### Live News Stream — Show Catalyst Headline Prefix + News Age

The scrolling **📡 Live News Stream** mirrors `scan_results`. To give users an immediate reason why an alert is generated, prefix each alert/candidate row with the top catalyst headline stored in `r.news.catalyst` and a compact inline age badge:

```javascript
const catalyst = (r.news && r.news.catalyst) ? r.news.catalyst : '';
const catalystPrefix = catalyst ? `<span style="color:var(--accent-amber)">📰 ${escapeHtml(catalyst)}</span> — ` : '';
const newsAge = formatNewsAgeInline(r.news);  // e.g. ' <span class="news-age">2d ago</span>'
const country = (r.country || '').trim();
const countryBadge = country ? ` <span class="country-badge">${escapeHtml(country)}</span>` : '';
return `<div class="news-item ...">
    <span class="score">${r.status}</span>
    ${impactTag}${newsAge}
    <span class="date">${date}</span> <span class="time">${time}</span>
    — ${r.ticker}${countryBadge} (${r.name}) — ${catalystPrefix}${r.result || ''}
</div>`;
```

**Country badge in news stream:** add `countryBadge` next to the ticker. The base `.country-badge` is large/dark; the news stream needs a smaller, lighter override via `.news-item .country-badge` (and `.news-ticker-symbol .country-badge` for cached HTML), using `!important` because GitHub Pages CDN can serve stale CSS. See `references/website-country-badge-and-tracker-pnl-fix.md` for the exact rule.

**Age must be recomputed from `raw_time`, not the saved `time` string.** Headlines are stored as `{title, time: "57m ago · 26 Jun", raw_time: "2026-06-26T12:21:03.000+0000"}`. The `time` string is frozen at fetch time, so saved `pre_market_results` will show stale ages like "57m ago" on a weekend unless the badge is calculated fresh. Use a `computeNewsAge(rawIso)` helper that derives minutes/hours/days from the ISO timestamp relative to `Date.now()`. The scanner table and the ticker must share the same recomputation logic so a ticker never contradicts the table.

Apply the same prefix and recomputed age badge in `website_updater.py` so the static fallback HTML (visible before JS overwrites it / for no-JS crawlers) also contains both pieces of context.

See `references/website-weekend-toggle-and-news-catalyst.md` for the full code, CSS, the `computeNewsAge` helper, the Python `datetime` recomputation, and Telegram quality-gate details.

### JavaScript Syntax Errors in Generated Website Template

`website_updater.py` regenerates `ozmoeg-trader.html` on every scan from an inline HTML template. If the template contains a duplicate `const`/`let` declaration or other JS syntax error, the entire main `<script>` block fails to parse. The result is a "broken" page: US/AUS and Live/Pre/After toggles do nothing, market auto-detection never runs, and the user sees stale server-rendered rows (e.g. AU tickers under the US button or vice versa).

**Always verify JS syntax after editing the template and before running the scanner.** A broken template will be pushed live on the next scan. See `references/website-js-syntax-error-breaks-toggles.md` for the detection probe, the duplicate-`allGainers` incident, and the fix.

### website_updater.py — `html` variable shadow pitfall

`_update_html()` uses a local variable named `html` for the HTML string. Adding `html.escape(...)` inside that scope fails because the name `html` now refers to the string, not the module. Use a module-level alias instead:

```python
import html
_html_escape = html.escape
```

Then call `_html_escape(...)` inside `_update_html()`. Also consider renaming the local variable to `html_text`.

**Reference:** `references/website-weekend-toggle-and-news-catalyst.md`.

3. **AI Sentiment** — Use LLM to score news sentiment
4. **Backtesting Engine** — Test strategy on historical data
5. **Auto-Execution** — Fully automated order entry/exit (requires working broker API)

## Support & Updates

- Webull library status: https://github.com/tedchou12/webull/issues
- Skill location: `~/.hermes/skills/ozmoeg-money-maker/`
- Website: https://aeyeing.com/ozmoeg-trader.html

## Disclaimer

This skill is for educational and research purposes only. Trading involves substantial risk of loss. Past performance does not guarantee future results. Always consult a licensed financial advisor before making investment decisions.
