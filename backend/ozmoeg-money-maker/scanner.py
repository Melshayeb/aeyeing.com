#!/usr/bin/env python3
"""
OzMoEg Money Maker — Small Cap Scalp Scanner
Fetches active small-cap gainers from Webull and filters by Ahmed Khaled criteria.
Supports US (region_code 5/6) and AU/ASX (region_code 18) market modes.
"""
import logging
from datetime import datetime
from functools import lru_cache
from typing import List, Dict, Any

# Optional yfinance fallback for average daily volume when Webull public data lacks it.
try:
    import yfinance as yf
    _YFINANCE_AVAILABLE = True
except Exception:
    _YFINANCE_AVAILABLE = False
    yf = None  # type: ignore

# Best-effort Webull issuerRegionId → origin country mapping.
# Webull does not expose a plain-text country field on the public quote endpoint,
# but `issuerRegionId` is reliable enough to label China/Cayman, US, Canada, UK, etc.
ISSUER_REGION_TO_COUNTRY = {
    1: 'China / Cayman-China',
    2: 'China / Hong Kong',
    3: 'Canada',
    4: 'United Kingdom',
    5: 'Japan',
    6: 'United States',
    12: 'India',
    13: 'Singapore',
    14: 'Germany',
    16: 'France',
    18: 'Australia',
    32: 'Brazil',
    50: 'Denmark',
    79: 'Indonesia',
    82: 'China',
    92: 'South Korea',
    105: 'Malaysia',
    106: 'Israel',
    112: 'Mexico',
    123: 'Netherlands',
    137: 'Italy',
    138: 'Sweden',
    147: 'Thailand',
    148: 'Philippines',
    159: 'Turkey',
    171: 'United Arab Emirates',
    189: 'Vietnam',
    195: 'South Africa',
    160: 'Spain',
    167: 'Switzerland',
    169: 'Taiwan',
    205: 'Bermuda / Other',
}

def _country_from_quote(q: dict) -> str:
    """Extract a human-readable origin country from a Webull quote payload."""
    if not q:
        return ''
    issuer_region = q.get('issuerRegionId')
    if issuer_region is not None:
        country = ISSUER_REGION_TO_COUNTRY.get(int(issuer_region))
        if country:
            return country
        # Known issuer region but not in our map — label generically instead of
        # falsely defaulting to the trading region (which is usually US for NASDAQ/NYSE).
        return f'International (region {int(issuer_region)})'
    if q.get('isAdr'):
        return 'International (ADR)'
    # Fallback: use the trading/market region when the issuer region is unknown.
    # This ensures US-listed tickers (e.g. USDE on NASDAQ) always carry an origin label.
    region_id = q.get('regionId')
    if region_id is not None:
        if int(region_id) == 6:
            return 'United States'
        if int(region_id) == 18:
            return 'Australia'
    return ''


@lru_cache(maxsize=256)
def _yfinance_avg_volume(ticker: str, days: int = 10) -> int:
    """Fetch average daily volume from Yahoo Finance history.

    Returns 0 if the ticker is not found, history is empty, or yfinance is unavailable.
    Cached per-process to avoid repeated API calls for the same ticker within one scan.
    """
    if not _YFINANCE_AVAILABLE or not yf or not ticker:
        return 0
    try:
        hist = yf.Ticker(ticker).history(period=f"{days + 5}d", interval="1d")
        if hist is None or hist.empty or "Volume" not in hist.columns:
            return 0
        avg = int(hist["Volume"].dropna().tail(days).mean())
        return avg if avg > 0 else 0
    except Exception as e:
        logger.debug("yfinance volume fallback failed for %s: %s", ticker, e)
        return 0


logger = logging.getLogger(__name__)

class SmallCapScanner:
    """Screen for active small-cap movers using Webull API."""

    def __init__(self, wb_client, config: Dict[str, Any], region_code: int = 6, market: str = 'us', backup_client=None):
        self.wb = wb_client
        self.cfg = config
        self.region_code = int(config.get('region_code', region_code))
        self.market = str(config.get('market', market)).lower()
        self.is_au = self.market == 'au' or self.region_code == 18
        self.backup = backup_client
        logger.info("Scanner initialised: market=%s region=%d is_au=%s backup=%s", self.market, self.region_code, self.is_au, backup_client is not None)

    def get_gainers(self, count: int = 50) -> List[Dict]:
        """Fetch top gainers for the configured market."""
        try:
            # US pre-market uses the preMarket rank type; 1d otherwise (AU already uses 1d)
            rank_type = '1d' if self.is_au else ('preMarket' if self.cfg.get('us_premarket_mode', True) else '1d')
            raw = self.wb.active_gainer_loser(direction='gainer', rank_type=rank_type, num=count)
            if raw is None:
                return []
            # Normalize: the library returns a dict with 'data' list
            if isinstance(raw, dict) and 'data' in raw:
                return raw['data']
            return raw if isinstance(raw, list) else []
        except Exception as e:
            logger.error(f"Failed to fetch gainers: {e}")
            return []

    def get_losers(self, count: int = 50) -> List[Dict]:
        """Fetch top losers for the configured market (used for bounce/mean-reversion watchlist)."""
        try:
            rank_type = '1d' if self.is_au else ('preMarket' if self.cfg.get('us_premarket_mode', True) else '1d')
            raw = self.wb.active_gainer_loser(direction='loser', rank_type=rank_type, num=count)
            if raw is None:
                return []
            if isinstance(raw, dict) and 'data' in raw:
                return raw['data']
            return raw if isinstance(raw, list) else []
        except Exception as e:
            logger.error(f"Failed to fetch losers: {e}")
            return []

    def enrich_stocks_with_quotes(self, stocks: List[Dict], ticker_ids: Dict[str, int] = None) -> List[Dict]:
        """Fetch per-ticker quotes in parallel and merge avgVol/RVOL/float/country into each stock.
        Alias for enrich_gainers_with_quotes that works for any list (gainers or losers)."""
        return self.enrich_gainers_with_quotes(stocks, ticker_ids=ticker_ids)

    def get_active(self, count: int = 50) -> List[Dict]:
        """Fetch most active stocks."""
        try:
            rank_type = '1d' if self.is_au else 'preMarket'
            raw = self.wb.active_gainer_loser(direction='active', rank_type=rank_type, num=count)
            if isinstance(raw, dict) and 'data' in raw:
                return raw['data']
            return raw if isinstance(raw, list) else []
        except Exception as e:
            logger.error(f"Failed to fetch active: {e}")
            return []

    def enrich_gainers_with_quotes(self, gainers, ticker_ids: Dict[str, int] = None) -> List[Dict]:
        """Fetch per-ticker quotes in parallel and merge avgVol/RVOL into each gainer.
        Accepts either a single gainer dict or a list of gainers for backwards compatibility.
        Falls back to the backup data provider when Webull returns no quote for a ticker."""
        # Normalise single-dict calls to a list
        single_mode = isinstance(gainers, dict)
        gainers_list = [gainers] if single_mode else (gainers or [])
        if not gainers_list:
            return gainers
        tickers = []
        for g in gainers_list:
            t = g.get('ticker', g) if isinstance(g, dict) else g
            sym = t.get('symbol', '') if isinstance(t, dict) else (g if isinstance(g, str) else '')
            if sym:
                tickers.append(sym)
        if not tickers:
            return gainers
        quotes = self.wb.get_quotes(tickers, max_workers=10, ticker_ids=ticker_ids)
        backup_symbols = []
        for g in gainers_list:
            t = g.get('ticker', g) if isinstance(g, dict) else g
            sym = t.get('symbol', '') if isinstance(t, dict) else (g if isinstance(g, str) else '')
            q = quotes.get(sym, {})
            if not q and self.backup:
                backup_symbols.append(sym)
                continue
            # Merge average volume fields into the ticker dict so downstream code sees them
            for key in ('avgVol10D', 'avgVol3M', 'avgVol5D', 'avgVolume', 'volumeRatio', 'turnoverRate'):
                if key in q and key not in t:
                    t[key] = q[key]
            # Also copy marketValue if quote has a more precise value
            if 'marketValue' in q:
                t['marketValue'] = q['marketValue']
            # Copy float / total shares from quote for low-float momentum filters
            for key in ('outstandingShares', 'totalShares'):
                if key in q and key not in t:
                    t[key] = q[key]
            # Capture origin country from Webull quote payload
            country = _country_from_quote(q)
            if country:
                t['_country'] = country

        # Fetch backup quotes only for symbols Webull missed
        if backup_symbols and self.backup:
            logger.info("Fetching backup quotes for %d symbols: %s", len(backup_symbols), backup_symbols[:10])
            backup_quotes = {}
            for sym in backup_symbols:
                try:
                    bq = self.backup.get_quote(sym)
                    if bq:
                        backup_quotes[sym] = bq
                except Exception as e:
                    logger.debug("Backup quote failed for %s: %s", sym, e)
            for g in gainers:
                t = g.get('ticker', g)
                sym = t.get('symbol', '') if isinstance(t, dict) else (g if isinstance(g, str) else '')
                if sym not in backup_quotes:
                    continue
                bq = backup_quotes[sym]
                # Merge only fields that are missing or zero in the ranking payload
                if not t.get('marketValue') and bq.get('marketValue'):
                    t['marketValue'] = bq['marketValue']
                if not t.get('volume') and bq.get('volume'):
                    t['volume'] = bq['volume']
                # Backup does not provide avgVol10D/avgVol3M, so RVOL remains unavailable
                # Mark the quote source for website display
                g['_backup_quote'] = True
                g['_backup_source'] = bq.get('source', 'unknown')
        return gainers

    def filter_candidates(self, stocks: List[Dict], mode: str = 'momentum') -> List[Dict]:
        """Apply scanner criteria. Mode can be 'momentum' (gainers, A+B) or 'bounce' (losers, C)."""
        annotated = []
        for stock in stocks:
            try:
                passed, reason = self._passes_filter_with_reason(stock, mode=mode)
                # Attach reason and basic metrics to stock dict for website display
                stock['_scan_reason'] = reason
                stock['_scan_passed'] = passed
                stock['_scan_mode'] = mode
                annotated.append(stock)
            except Exception as e:
                logger.debug(f"Filter error for {stock.get('symbol','?')}: {e}")
                stock['_scan_reason'] = f'error: {e}'
                stock['_scan_passed'] = False
                stock['_scan_mode'] = mode
                annotated.append(stock)
        candidates = [s for s in annotated if s['_scan_passed']]
        # Sort by absolute move percentage (descending) for bounce; RVOL for momentum
        if mode == 'bounce':
            candidates.sort(key=lambda x: abs(self._change_pct(x)), reverse=True)
        else:
            candidates.sort(key=lambda x: float(x.get('ticker', x).get('rvol', 0) or x.get('volume', 0)), reverse=True)
        return candidates[:20]

    def _change_pct(self, stock: Dict) -> float:
        """Compute change percentage for a stock (used for sorting and bounce logic)."""
        t = stock.get('ticker', stock)
        v = stock.get('values', {})
        close = float(t.get('close', 0) or 0)
        pre_close = float(t.get('preClose', 0) or 0)
        price = float(v.get('price', 0) or t.get('pprice', 0) or t.get('close', 0) or 0)
        change_ratio = float(v.get('changeRatio', 0) or t.get('changeRatio', 0) or 0)
        if self.is_au and pre_close > 0 and close != pre_close:
            return (close - pre_close) / pre_close * 100
        if self.is_au and change_ratio:
            return change_ratio * 100
        if close > 0 and price > 0:
            return (price - close) / close * 100
        return (change_ratio - 1) * 100 if change_ratio > 1 else (change_ratio * 100)

    def _passes_filter_with_reason(self, stock: Dict, mode: str = 'momentum') -> tuple:
        """Check if stock meets criteria and return reason.
        Mode 'momentum' = gainers with A+B tiered rules.
        Mode 'bounce' = losers / large pullbacks with C rules.
        """
        t = stock.get('ticker', stock)
        v = stock.get('values', {})
        price = float(v.get('price', 0) or t.get('pprice', 0) or t.get('close', 0) or 0)
        close = float(t.get('close', 0) or 0)
        pre_close = float(t.get('preClose', 0) or 0)
        # ASX: changeRatio is in values dict; US: may be in ticker dict
        change_ratio = float(v.get('changeRatio', 0) or t.get('changeRatio', 0) or 0)

        if self.is_au:
            if pre_close > 0 and close != pre_close:
                change_pct = (close - pre_close) / pre_close * 100
            else:
                change_pct = change_ratio * 100
        else:
            # Webull payloads report session change as changeRatio (0.848 = +84.8%).
            # Trust it when it is present and non-zero; derive from price/close only
            # when it is missing or implausibly small/flat.
            if abs(change_ratio) >= 0.0001:
                # changeRatio can be either a decimal fraction (0.848) or already a
                # percentage (84.8). Treat values <= ~10 as decimal fractions.
                if abs(change_ratio) <= 10:
                    change_pct = change_ratio * 100
                else:
                    change_pct = change_ratio
            elif close > 0 and price > 0 and abs(price - close) > 1e-9:
                change_pct = (price - close) / close * 100
            else:
                change_pct = (change_ratio - 1) * 100 if change_ratio > 1 else (change_ratio * 100)

        volume = int(t.get('volume', 0) or t.get('amount', 0) or 0)
        market_cap_raw = float(t.get('marketValue', 0) or 0)
        outstanding_shares = int(t.get('outstandingShares', 0) or 0)
        avg_vol_10d = float(t.get('avgVol10D', 0) or 0)
        avg_vol_3m = float(t.get('avgVol3M', 0) or 0)

        # yfinance fallback: when Webull public quotes don't include average volume,
        # fetch the real 10-day average from Yahoo Finance so RVOL and avg $vol
        # filters are based on actual history instead of falling back to zero.
        symbol = t.get('symbol', '') if isinstance(t, dict) else ''
        if not self.is_au and symbol:
            # yfinance fallback/replacement: Webull unauthenticated public quotes sometimes
            # return stale/implausibly-low 10-day average volume for recent runners.
            # If the Webull avg daily dollar volume looks suspiciously thin, override it
            # with Yahoo Finance's real 10-day average before computing RVOL and filters.
            webull_avg_dollar = 0.0
            if avg_vol_10d > 0:
                webull_avg_dollar = avg_vol_10d * price
            elif avg_vol_3m > 0:
                webull_avg_dollar = avg_vol_3m * price

            needs_yf = False
            if avg_vol_10d == 0 and avg_vol_3m == 0:
                needs_yf = True
            else:
                # Use a safe default threshold if config hasn't loaded min_avg_daily_dollar_volume yet.
                threshold = float(self.cfg.get('extended_hours_min_avg_daily_dollar_volume', self.cfg.get('min_avg_daily_dollar_volume', 500_000)))
                if webull_avg_dollar > 0 and webull_avg_dollar < threshold * 0.5:
                    needs_yf = True

            if needs_yf:
                yf_avg = _yfinance_avg_volume(symbol, days=10)
                if yf_avg > 0:
                    avg_vol_10d = float(yf_avg)
                    t['avgVol10D'] = yf_avg
                    t['_avg_vol_source'] = 'yfinance'
                    # Clear the 3-month value so RVOL definitely uses the yfinance 10-day average
                    if 'avgVol3M' in t:
                        del t['avgVol3M']

        if avg_vol_10d > 0:
            rvol = volume / avg_vol_10d
        elif avg_vol_3m > 0:
            rvol = volume / avg_vol_3m
        else:
            rvol = float(t.get('rvol') or 0)

        # ── BOUNCE MODE (Option C): large losers / pullbacks ─────────────────
        if mode == 'bounce':
            bc = self.cfg.get('bounce_scanner', {})
            if not bc.get('enabled', False):
                return False, 'Bounce scanner disabled'
            price_min = float(bc.get('price_min', 0.50))
            price_max = float(bc.get('price_max', 10.0))
            mkt_min = float(bc.get('market_cap_min', 5_000_000))
            mkt_max = float(bc.get('market_cap_max', 50_000_000))
            move_min = float(bc.get('move_min_pct', -50.0))   # e.g. down 50%
            move_max = float(bc.get('move_max_pct', -10.0))   # e.g. down 10%
            rvol_min = float(bc.get('rvol_min', 2.0))
            volume_min = int(bc.get('volume_min', 100_000))
            max_float = int(bc.get('max_float_shares', 50_000_000))
            min_vfr = float(bc.get('min_volume_float_ratio', 0.5))
            fails = []
            if not (price_min <= price <= price_max):
                fails.append(f'price ${price:.3f}')
            if not (mkt_min <= market_cap_raw <= mkt_max):
                fails.append(f'mktcap ${market_cap_raw/1e6:.1f}M')
            if not (move_min <= change_pct <= move_max):
                fails.append(f'move {change_pct:.1f}%')
            if rvol < rvol_min:
                fails.append(f'rvol {rvol:.1f}x')
            if volume < volume_min:
                fails.append(f'vol {volume:,}')
            if max_float > 0 and outstanding_shares > 0 and outstanding_shares > max_float:
                fails.append(f'float {outstanding_shares/1e6:.1f}M')
            if outstanding_shares > 0 and min_vfr > 0:
                vfr = volume / outstanding_shares
                if vfr < min_vfr:
                    fails.append(f'vol/float {vfr:.2f}x')
            if fails:
                return False, 'Filtered: ' + ', '.join(fails)
            return True, 'Bounce candidate'

        # Scanner thresholds are now intentionally the same in every US market phase
        # (pre-market, open, after-hours) so the website rules panel never contradicts
        # the backend.  Keep using the extended_hours_* keys as the canonical values
        # because they already represent the unified rule set, and only fall back to
        # base keys if the extended-hours keys are missing.
        market_status = str(self.cfg.get('market_status', '') or self._detect_market_status()).upper()
        # is_extended_hours is kept for legacy code paths but no longer changes thresholds.
        is_extended_hours = not self.is_au

        # ── MOMENTUM MODE (Options A+B) ─────────────────────────────────────
        au_cfg = self.cfg.get('au', {})
        if self.is_au:
            price_min = float(au_cfg.get('price_min', 0.001))
            price_max = float(au_cfg.get('price_max', 5.0))
            mkt_min = float(au_cfg.get('market_cap_min', 1_000_000))
            mkt_max = float(au_cfg.get('market_cap_max', 500_000_000))
            move_min = float(au_cfg.get('premarket_pct_min', 8.0))
            rvol_min = float(au_cfg.get('rvol_min', 1.0))
            volume_min = int(au_cfg.get('volume_min', 200_000))
            volume_value_aud_min = float(au_cfg.get('volume_value_aud_min', 50_000))
            move_max = None
            max_float_shares = 0
            min_volume_float_ratio = 0
            min_avg_daily_dollar_volume = 0
        else:
            # Unified thresholds: extended_hours_* keys are canonical, fall back to base keys.
            price_min = float(self.cfg.get('extended_hours_price_min', self.cfg.get('price_min', 0.20)))
            price_max = float(self.cfg.get('extended_hours_price_max', self.cfg.get('price_max', 50.0)))
            mkt_min = float(self.cfg.get('extended_hours_market_cap_min', self.cfg.get('market_cap_min', 1_000_000)))
            mkt_max = float(self.cfg.get('extended_hours_market_cap_max', self.cfg.get('market_cap_max', 5_000_000_000)))
            move_min = float(self.cfg.get('extended_hours_premarket_pct_min', self.cfg.get('premarket_pct_min', 5.0)))
            rvol_min = float(self.cfg.get('extended_hours_rvol_min', self.cfg.get('rvol_min', 1.0)))
            volume_min = int(self.cfg.get('extended_hours_volume_min', self.cfg.get('volume_min', 50_000)))
            max_float_shares = int(self.cfg.get('extended_hours_max_float_shares', self.cfg.get('max_float_shares', 100_000_000)))
            min_volume_float_ratio = float(self.cfg.get('extended_hours_min_volume_float_ratio', self.cfg.get('min_volume_float_ratio', 0.5)))
            strong_volume_float_ratio = float(self.cfg.get('extended_hours_strong_volume_float_ratio', self.cfg.get('strong_volume_float_ratio', 1.0)))
            min_avg_daily_dollar_volume = float(self.cfg.get('extended_hours_min_avg_daily_dollar_volume', self.cfg.get('min_avg_daily_dollar_volume', 500_000)))
            volume_value_aud_min = 0
            move_max = float(self.cfg.get('extended_hours_move_max_pct', self.cfg.get('move_max_pct', 800.0)))
            move_tier_2_max = float(self.cfg.get('extended_hours_move_tier_2_max', self.cfg.get('move_tier_2_max', 1500.0)))
            move_tier_2_min_rvol = float(self.cfg.get('extended_hours_move_tier_2_min_rvol', self.cfg.get('move_tier_2_min_rvol', 1.5)))
            move_tier_2_min_vfr = float(self.cfg.get('extended_hours_move_tier_2_min_float_ratio', self.cfg.get('move_tier_2_min_float_ratio', 0.5)))

        # Tiny-cap ($5M-$10M) overrides: keep the 150% hard cap + looser tier-2 gate.
        if not self.is_au and market_cap_raw < 10_000_000 and market_cap_raw >= mkt_min:
            move_max = float(self.cfg.get('tiny_cap_move_max_pct', move_max))
            move_tier_2_max = float(self.cfg.get('tiny_cap_move_tier_2_max', move_tier_2_max))
            move_tier_2_min_rvol = float(self.cfg.get('tiny_cap_move_tier_2_min_rvol', move_tier_2_min_rvol))
            move_tier_2_min_vfr = float(self.cfg.get('tiny_cap_move_tier_2_min_float_ratio', move_tier_2_min_vfr))

        fails = []
        if not (price_min <= price <= price_max):
            fails.append(f'price ${price:.3f}')
        if not (mkt_min <= market_cap_raw <= mkt_max):
            fails.append(f'mktcap ${market_cap_raw/1e6:.1f}M')

        # Tiny-cap ($5M-$10M) liquidity gate uses the same unified thresholds.
        if not self.is_au and market_cap_raw < 10_000_000 and market_cap_raw >= mkt_min:
            tiny_price_min = self.cfg.get('tiny_cap_min_price', price_min)
            tiny_vfr_min = self.cfg.get('tiny_cap_min_volume_float_ratio', min_volume_float_ratio)
            tiny_avg_dv_min = self.cfg.get('tiny_cap_min_avg_daily_dollar_volume', min_avg_daily_dollar_volume)
            tiny_rvol_min = self.cfg.get('tiny_cap_min_rvol', rvol_min)
            if price < tiny_price_min:
                fails.append(f'tiny price ${price:.3f}')
            if rvol < tiny_rvol_min:
                fails.append(f'tiny rvol {rvol:.1f}x')
            if avg_vol_10d > 0 and (avg_vol_10d * price) < tiny_avg_dv_min:
                fails.append(f'tiny avg $vol')
            if outstanding_shares > 0 and min_volume_float_ratio > 0 and tiny_vfr_min > 0:
                vfr = volume / outstanding_shares
                if vfr < tiny_vfr_min:
                    fails.append(f'tiny vol/float {vfr:.2f}x')

        # Momentum: accept if change >= min OR rvol >= min (relaxed for sub-$10M tiny-caps).
        if not self.is_au and market_cap_raw < 10_000_000 and market_cap_raw >= mkt_min:
            # Tiny-cap momentum: strong move alone is enough; RVOL can be missing/very low.
            if abs(change_pct) < move_min:
                fails.append(f'move {change_pct:.1f}%')
        elif abs(change_pct) < move_min and rvol < rvol_min:
            fails.append(f'move {change_pct:.1f}% / rvol {rvol:.1f}')
        if volume < volume_min:
            fails.append(f'vol {volume:,}')

        # Upper move cap with tiered exception
        if not self.is_au and move_max is not None and abs(change_pct) > move_max:
            if move_tier_2_max and abs(change_pct) <= move_tier_2_max:
                # Allow if strong turnover and RVOL
                tier_ok = rvol >= move_tier_2_min_rvol
                if outstanding_shares > 0 and min_volume_float_ratio > 0:
                    vfr = volume / outstanding_shares
                    tier_ok = tier_ok and vfr >= move_tier_2_min_vfr
                if not tier_ok:
                    fails.append(f'move {change_pct:.1f}% tier-2 failed')
            else:
                fails.append(f'move too large {change_pct:.1f}% > {move_tier_2_max or move_max:.0f}%')

        # Low-float and volume/float filters
        if not self.is_au and max_float_shares > 0 and outstanding_shares > 0 and outstanding_shares > max_float_shares:
            fails.append(f'float {outstanding_shares/1e6:.1f}M > {max_float_shares/1e6:.0f}M')
        if not self.is_au and outstanding_shares > 0 and min_volume_float_ratio > 0:
            vfr = volume / outstanding_shares
            if vfr < min_volume_float_ratio:
                fails.append(f'vol/float {vfr:.2f}x < {min_volume_float_ratio:.1f}x')
        if not self.is_au and min_avg_daily_dollar_volume > 0:
            avg_daily_dollar = 0
            if avg_vol_10d > 0:
                avg_daily_dollar = avg_vol_10d * price
            elif avg_vol_3m > 0:
                avg_daily_dollar = avg_vol_3m * price
            if avg_daily_dollar > 0:
                # Hyper-scalp exception only rescues avg dollar volume floor, not tiny-cap gate.
                # If a nano/micro-cap has zero/very-low RVOL but is moving hard with live turnover,
                # allow it through.  Criteria: +30%+ move, RVOL ≥0.0x (relaxed), current dollar volume ≥$100K,
                # avg daily dollar volume < $500K.  Applied in every US market phase.
                hyper_enabled = self.cfg.get('hyper_scalp_enabled', False)
                if hyper_enabled:
                    hs_change_min = float(self.cfg.get('hyper_scalp_min_change_pct', 30.0))
                    hs_rvol_min = float(self.cfg.get('hyper_scalp_min_rvol', 0.0))
                    hs_min_dv = float(self.cfg.get('hyper_scalp_min_current_dollar_volume', 100_000))
                    hs_max_avg_dv = float(self.cfg.get('hyper_scalp_max_avg_daily_dollar_volume', 500_000))
                    hs_floor = float(self.cfg.get('hyper_scalp_avg_dollar_volume_floor', 100_000))
                    current_dollar_volume = price * volume
                    is_hyper_scalp = (
                        avg_daily_dollar < hs_max_avg_dv
                        and abs(change_pct) >= hs_change_min
                        and rvol >= hs_rvol_min
                        and current_dollar_volume >= hs_min_dv
                    )
                else:
                    is_hyper_scalp = False

                effective_min = min_avg_daily_dollar_volume
                if market_cap_raw < 10_000_000 and market_cap_raw >= mkt_min:
                    effective_min = float(self.cfg.get('tiny_cap_min_avg_daily_dollar_volume', min_avg_daily_dollar_volume))

                if is_hyper_scalp:
                    # Keep a minimum floor so we never accept completely dead names
                    effective_min = max(hs_floor, min(effective_min, hs_floor))

                if avg_daily_dollar < effective_min:
                    fails.append(f'avg $vol ${avg_daily_dollar/1e6:.1f}M < ${effective_min/1e6:.1f}M')
        if self.is_au and volume_value_aud_min > 0 and (price * volume) < volume_value_aud_min:
            fails.append(f'dollar vol ${price*volume:,.0f}')

        if fails:
            return False, 'Filtered: ' + ', '.join(fails)
        return True, 'Passed filters'

    def _passes_filter(self, stock: Dict) -> bool:
        """Backward-compatible boolean filter check."""
        passed, _ = self._passes_filter_with_reason(stock)
        return passed

    def _detect_market_status(self) -> str:
        """Infer US market status from current ET time when not explicitly set."""
        try:
            import pytz
            et = pytz.timezone('America/New_York')
            now = datetime.now(et)
            weekday = now.weekday()
            if weekday >= 5:
                return 'WEEKEND'
            hour, minute = now.hour, now.minute
            minutes = hour * 60 + minute
            # Pre-market 04:00-09:30 ET, regular 09:30-16:00, after-hours 16:00-20:00
            if minutes < 240 or minutes >= 1200:
                return 'CLOSED'
            if minutes < 570:
                return 'PRE-MARKET'
            if minutes < 960:
                return 'OPEN'
            return 'AFTER-HOURS'
        except Exception as e:
            logger.warning("Market status detection failed: %s", e)
            return 'PRE-MARKET'  # safest default for scanner

    def _is_sydney_active_window(self) -> bool:
        """Return True during the Sydney active OzMoEg window (17:00-23:59, Mon-Fri)."""
        try:
            import pytz
            sydney = pytz.timezone('Australia/Sydney')
            now = datetime.now(sydney)
            if now.weekday() >= 5:
                return False
            return 17 <= now.hour <= 23
        except Exception as e:
            logger.warning("Sydney active window detection failed: %s", e)
            return False

    def _asx_change_pct(self, stock: Dict) -> float:
        """Return ASX-aware change percentage for display."""
        t = stock.get('ticker', stock)
        v = stock.get('values', {})
        close = float(t.get('close', 0) or 0)
        pre_close = float(t.get('preClose', 0) or 0)
        price = float(v.get('price', 0) or t.get('pprice', 0) or 0)
        # ASX: changeRatio is in values dict; US: may be in ticker dict
        change_ratio = float(v.get('changeRatio', 0) or t.get('changeRatio', 0) or 0)
        if self.is_au and pre_close > 0 and close != pre_close:
            return (close - pre_close) / pre_close * 100
        if self.is_au and change_ratio:
            return change_ratio * 100
        if close > 0 and price > 0:
            return (price - close) / close * 100
        return (change_ratio - 1) * 100 if change_ratio > 1 else (change_ratio * 100)

    def enrich_with_quote(self, ticker: str, stock: Dict = None, ticker_id: int = None) -> Dict:
        """Fetch detailed quote for deeper analysis. Fallback to ranking payload in AU mode."""
        quote = {}
        try:
            quote = self.wb.get_quote(ticker, tId=ticker_id)
        except Exception as e:
            logger.warning(f"Quote fetch failed for {ticker}: {e}")
        if not quote and self.is_au and stock:
            t = stock.get('ticker', stock)
            v = stock.get('values', {})
            quote = {
                'ticker': ticker,
                'name': t.get('name', ticker),
                'close': float(t.get('close', 0) or v.get('close', 0) or 0),
                'price': float(v.get('price', 0) or t.get('pprice', 0) or t.get('close', 0) or 0),
                'open': float(t.get('open', 0) or 0),
                'high': float(t.get('high', 0) or 0),
                'low': float(t.get('low', 0) or 0),
                'volume': int(t.get('volume', 0) or 0),
                'changeRatio': float(t.get('changeRatio', 0) or 0),
                'preClose': float(t.get('preClose', 0) or 0),
                'marketValue': float(t.get('marketValue', 0) or 0),
                '_synthetic': True
            }
            logger.info("Using synthetic ranking-payload quote for %s (AU mode)", ticker)
        return quote if quote else {}