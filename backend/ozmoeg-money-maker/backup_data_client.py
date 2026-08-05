#!/usr/bin/env python3
"""
OzMoEg Money Maker — Backup US Stock Data Client
Provides redundancy when the primary Webull public-data endpoints are
unavailable, rate-limited, or return incomplete data.

Fallback chain:
  1. Alpaca Markets (if API key/secret configured) — best for US stocks,
     includes premarket/after-hours, and can later be used for order execution.
  2. Yahoo Finance via yfinance (zero-config) — quotes, market cap, premarket
     price, and intraday history.

The backup client is used primarily for per-ticker quote enrichment and
price verification. It does NOT replace Webull's gainers ranking (Yahoo has
no equivalent free endpoint); instead it makes the scanner more resilient
when Webull quote enrichment fails.
"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Optional Alpaca SDK
ALPACA_AVAILABLE = False
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockQuotesRequest, StockBarsRequest, StockLatestQuoteRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    ALPACA_AVAILABLE = True
except Exception as e:
    logger.debug("alpaca-py not available: %s", e)

# Optional yfinance
YFINANCE_AVAILABLE = False
try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except Exception as e:
    logger.debug("yfinance not available: %s", e)


class YahooFinanceProvider:
    """Zero-config provider using yfinance. Best-effort; Yahoo blocks some IPs."""

    def get_quote(self, ticker: str) -> Optional[Dict[str, Any]]:
        if not YFINANCE_AVAILABLE:
            return None
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            hist = t.history(period='1d', interval='1m', prepost=True)
            last_price = None
            if hist is not None and len(hist) > 0:
                last_price = float(hist['Close'].iloc[-1])

            premarket = info.get('preMarketPrice')
            regular_price = info.get('regularMarketPrice')
            previous_close = info.get('regularMarketPreviousClose') or info.get('previousClose')
            market_cap = info.get('marketCap')
            volume_24h = info.get('regularMarketVolume') or info.get('volume')

            price = premarket or last_price or regular_price or previous_close
            if price is None:
                return None

            # Compute change % vs previous close
            change_pct = 0.0
            if previous_close and price:
                change_pct = (float(price) - float(previous_close)) / float(previous_close) * 100

            return {
                'ticker': ticker,
                'name': info.get('longName') or info.get('shortName') or ticker,
                'price': float(price),
                'close': float(previous_close) if previous_close else float(price),
                'preMarketPrice': float(premarket) if premarket else None,
                'regularMarketPrice': float(regular_price) if regular_price else None,
                'changeRatio': 1 + (change_pct / 100),
                'change': float(price) - float(previous_close) if previous_close else 0.0,
                'volume': int(volume_24h) if volume_24h else 0,
                'marketValue': float(market_cap) if market_cap else 0.0,
                'avgVol10D': None,
                'avgVol3M': None,
                'source': 'yfinance',
                '_synthetic': False,
            }
        except Exception as e:
            logger.warning("Yahoo Finance quote failed for %s: %s", ticker, e)
            return None

    def get_bars(self, ticker: str, interval: str = '1m', count: int = 100) -> Optional[List[Dict]]:
        if not YFINANCE_AVAILABLE:
            return None
        try:
            t = yf.Ticker(ticker)
            # Map interval to yfinance period
            period = '5d' if interval in ('1m', '2m', '5m') else '1mo'
            hist = t.history(period=period, interval=interval, prepost=True)
            if hist is None or hist.empty:
                return None
            bars = []
            for idx, row in hist.iterrows():
                bars.append({
                    'timestamp': idx.isoformat(),
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                    'volume': int(row['Volume']),
                })
            return bars[-count:]
        except Exception as e:
            logger.warning("Yahoo Finance bars failed for %s: %s", ticker, e)
            return None


class AlpacaProvider:
    """Alpaca Markets provider. Requires API key + secret."""

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        if not ALPACA_AVAILABLE:
            raise RuntimeError("alpaca-py is not installed")
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.client = StockHistoricalDataClient(api_key, secret_key)

    def get_quote(self, ticker: str) -> Optional[Dict[str, Any]]:
        try:
            req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
            resp = self.client.get_stock_latest_quote(req)
            quote = resp.get(ticker)
            if quote is None:
                return None
            price = float(quote.ask_price) if quote.ask_price else float(quote.bid_price)
            if not price:
                return None
            return {
                'ticker': ticker,
                'name': ticker,
                'price': price,
                'close': price,  # Alpaca quote doesn't carry prior close; caller must merge
                'preMarketPrice': None,
                'regularMarketPrice': None,
                'changeRatio': 1.0,
                'change': 0.0,
                'volume': 0,
                'marketValue': 0.0,
                'avgVol10D': None,
                'avgVol3M': None,
                'source': 'alpaca',
                '_synthetic': False,
            }
        except Exception as e:
            logger.warning("Alpaca quote failed for %s: %s", ticker, e)
            return None

    def get_bars(self, ticker: str, interval: str = '1m', count: int = 100) -> Optional[List[Dict]]:
        try:
            tf = self._parse_interval(interval)
            end = datetime.utcnow()
            start = end - self._lookback_for_interval(interval, count)
            req = StockBarsRequest(
                symbol_or_symbols=ticker,
                timeframe=tf,
                start=start,
                end=end,
                feed='sip'  # 'sip' includes OTC; 'iex' is free-tier but US-only
            )
            resp = self.client.get_stock_bars(req)
            bars_data = resp.get(ticker, [])
            bars = []
            for bar in bars_data:
                bars.append({
                    'timestamp': bar.timestamp.isoformat(),
                    'open': float(bar.open),
                    'high': float(bar.high),
                    'low': float(bar.low),
                    'close': float(bar.close),
                    'volume': int(bar.volume),
                })
            return bars[-count:]
        except Exception as e:
            logger.warning("Alpaca bars failed for %s: %s", ticker, e)
            return None

    @staticmethod
    def _parse_interval(interval: str) -> Any:
        mapping = {
            '1m': TimeFrame(1, TimeFrameUnit.Minute),
            '5m': TimeFrame(5, TimeFrameUnit.Minute),
            '15m': TimeFrame(15, TimeFrameUnit.Minute),
            '1h': TimeFrame(1, TimeFrameUnit.Hour),
            '1d': TimeFrame(1, TimeFrameUnit.Day),
        }
        return mapping.get(interval, TimeFrame(1, TimeFrameUnit.Minute))

    @staticmethod
    def _lookback_for_interval(interval: str, count: int) -> timedelta:
        minutes = {'1m': 1, '5m': 5, '15m': 15, '1h': 60}.get(interval, 1)
        return timedelta(minutes=minutes * count * 2)


class BackupDataClient:
    """Unified fallback client. Alpaca first if configured, then Yahoo Finance."""

    def __init__(self, config: Dict[str, Any]):
        self.cfg = config.get('backup_data', {})
        self.providers = []

        alpaca_cfg = self.cfg.get('alpaca', {})
        if alpaca_cfg.get('api_key') and alpaca_cfg.get('secret_key'):
            try:
                self.providers.append(AlpacaProvider(
                    api_key=alpaca_cfg['api_key'],
                    secret_key=alpaca_cfg['secret_key'],
                    paper=alpaca_cfg.get('paper', True)
                ))
                logger.info("Backup data: Alpaca provider enabled")
            except Exception as e:
                logger.warning("Failed to initialize Alpaca backup provider: %s", e)

        # Yahoo Finance is always enabled as a zero-config fallback
        if YFINANCE_AVAILABLE:
            self.providers.append(YahooFinanceProvider())
            logger.info("Backup data: Yahoo Finance provider enabled")
        else:
            logger.warning("Backup data: yfinance not installed; no zero-config fallback available")

    def get_quote(self, ticker: str) -> Dict[str, Any]:
        for provider in self.providers:
            try:
                quote = provider.get_quote(ticker)
                if quote:
                    logger.info("Backup quote for %s from %s", ticker, quote.get('source'))
                    return quote
            except Exception as e:
                logger.debug("Backup provider %s failed for %s: %s", type(provider).__name__, ticker, e)
        return {}

    def get_bars(self, ticker: str, interval: str = '1m', count: int = 100) -> Optional[List[Dict]]:
        for provider in self.providers:
            try:
                bars = provider.get_bars(ticker, interval=interval, count=count)
                if bars:
                    return bars
            except Exception as e:
                logger.debug("Backup provider %s bars failed for %s: %s", type(provider).__name__, ticker, e)
        return None

    def status(self) -> Dict[str, Any]:
        return {
            'providers_configured': [type(p).__name__ for p in self.providers],
            'alpaca_available': ALPACA_AVAILABLE,
            'yfinance_available': YFINANCE_AVAILABLE,
        }


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    client = BackupDataClient({})
    print('Status:', client.status())
    for sym in ['AAPL', 'RDGT', 'INFQ']:
        q = client.get_quote(sym)
        print(sym, q)
