# OzMoEg — Backup US Stock Data Sources

## Why

The primary scanner uses the public Webull community API for US gainer lists and per-ticker quotes. Webull can:

- Rate-limit or block unauthenticated clients (`403 Illegal Client`).
- Return incomplete quote payloads for some tickers.
- Have region-specific DNS failures (e.g. `openapi.webull.com.au` does not resolve from non-AU IPs).

A backup data source gives the scanner redundancy for quote enrichment and, eventually, a fully redundant gainer source.

## Implemented providers

### 1. Yahoo Finance (`yfinance`) — zero-config fallback

- **Used for**: per-ticker quotes, market cap, premarket price, daily change, recent bars.
- **Pros**: no API key required.
- **Cons**: Yahoo blocks aggressive scraping; rate limits can be hit; no official "top gainers" API, so it cannot fully replace Webull's gainer list.
- **Enabled by default** in `config.yaml` under `backup_data.yfinance.enabled: true`.

### 2. Alpaca Markets (`alpaca-py`) — key-configured best option

- **Used for**: quotes, snapshots, historical bars, and (with keys) paper/live trading.
- **Pros**: official API, generous free tier (200 req/min), includes premarket/after-hours data, supports order placement.
- **Cons**: requires an API key/secret.
- **Config** in `config.yaml`:
  ```yaml
  backup_data:
    enabled: true
    alpaca:
      api_key: ''      # paste your Alpaca key here
      secret_key: ''   # paste your Alpaca secret here
      paper: true      # set false for live trading
  ```

### 3. Polygon.io / Finnhub / IEX — not yet implemented

- These can be added as additional providers if you obtain keys.
- Polygon has a free `v2/snapshot` endpoint that can serve as a full gainer-list replacement.

## How it works in the scanner

1. `main.py` creates a `BackupDataClient` from `config.yaml` and passes it to `SmallCapScanner`.
2. When `enrich_gainers_with_quotes()` runs, Webull is queried first for all tickers.
3. Any ticker that Webull fails to return a quote for is then sent to the backup provider(s).
4. Missing fields (market cap, volume) are merged from the backup quote and the result is tagged with `_backup_quote = true` and `_backup_source`.

## Current status

- `backup_data_client.py` implemented and tested.
- Yahoo Finance provider active and returning real premarket quotes.
- Full `python main.py --mode scan --market us` pipeline runs successfully with backup client enabled.
- No Alpaca keys are stored yet; add them to `config.yaml` to enable Alpaca redundancy.

## Getting an Alpaca key (recommended next step)

1. Sign up at https://alpaca.markets/ (paper trading is free).
2. Generate API key + secret from the dashboard.
3. Insert them into `config.yaml` under `backup_data.alpaca`.
4. The scanner will automatically use Alpaca as the first backup provider; Yahoo Finance remains the zero-config safety net.