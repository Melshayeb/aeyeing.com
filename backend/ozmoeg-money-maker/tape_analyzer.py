#!/usr/bin/env python3
"""
OzMoEg Money Maker — Tape Analyzer (15-second bar time-and-sales proxy)

Real tick-by-tick time-and-sales from Webull public endpoints is disabled
(`API_DISABLED`). This module uses 15-second OHLCV bars as a high-resolution
proxy to derive tape-like signals:

  - volume acceleration (recent vs prior bars)
  - price velocity / momentum
  - buy/sell pressure from close position within the bar
  - large-bar count (bars with range > 2x average)
  - VWAP distance

The output is a `tape_score` (0-10) that can be used for ranking and alert
gating.
"""
import logging
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class TapeAnalyzer:
    """High-resolution tape-style analysis from sub-minute bars."""

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        self.cfg = cfg or {}

    def _to_dataframe(self, bars) -> pd.DataFrame:
        """Normalize bars to a DataFrame with standard OHLCV columns."""
        if bars is None:
            return pd.DataFrame()
        if isinstance(bars, pd.DataFrame):
            df = bars.copy()
        elif isinstance(bars, (list, tuple)) and len(bars) > 0:
            df = pd.DataFrame(bars)
        else:
            return pd.DataFrame()
        if df.empty:
            return df
        # Standardise column names
        rename = {}
        for col in df.columns:
            low = str(col).lower()
            if low in ('open', 'high', 'low', 'close', 'volume'):
                rename[col] = low
        df = df.rename(columns=rename)
        needed = {'open', 'high', 'low', 'close', 'volume'}
        if not needed.issubset(df.columns):
            return pd.DataFrame()
        numeric = {'open': float, 'high': float, 'low': float, 'close': float, 'volume': float}
        for col, typ in numeric.items():
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna(subset=list(needed))
        return df

    def _bar_metrics(self, df: pd.DataFrame, end_price: float) -> Dict[str, Any]:
        """Compute tape-style momentum metrics from the most recent bars."""
        empty = {
            'volume_acceleration': 0.0,
            'price_velocity_pct': 0.0,
            'buy_pressure_pct': 0.0,
            'large_bar_count': 0,
            'vwap_distance_pct': 0.0,
            'median_range': 0.0,
        }
        if df.empty or len(df) < 4:
            return empty

        df = df.copy().reset_index(drop=True)
        ranges = df['high'] - df['low']
        median_range = float(ranges.median())

        # Volume acceleration: last half of bars vs prior half
        half = max(1, len(df) // 2)
        recent_volume = float(df['volume'].iloc[-half:].sum())
        prior_volume = float(df['volume'].iloc[:max(1, len(df) - half)].sum())
        volume_acceleration = 0.0
        if prior_volume > 0:
            volume_acceleration = round((recent_volume / prior_volume) - 1.0, 3)

        # Price velocity over the most recent window (last 25% of bars, min 5).
        # Use absolute velocity so breakouts AND sharp pullbacks both register as tape momentum.
        recent_window = max(5, len(df) // 4)
        start_price = float(df.iloc[-recent_window]['open'])
        if start_price > 0:
            price_velocity_pct = round(abs((end_price - start_price) / start_price) * 100, 3)
        else:
            price_velocity_pct = 0.0

        # Buy pressure: close position within each bar
        denom = (df['high'] - df['low']).replace(0, np.nan)
        close_pos = (df['close'] - df['low']) / denom
        buy_pressure_pct = round(float(close_pos.mean()) * 100, 2) if not close_pos.empty and not close_pos.isna().all() else 50.0

        # Large bars: range > 2x median range
        large_bar_count = int((ranges > 2.0 * median_range).sum())

        # VWAP distance also as absolute deviation (magnitude, not direction)
        vwap = self._calculate_vwap(df)
        vwap_distance_pct = 0.0
        if vwap and vwap > 0 and end_price > 0:
            vwap_distance_pct = round(abs((end_price - vwap) / vwap) * 100, 3)

        return {
            'volume_acceleration': volume_acceleration,
            'price_velocity_pct': price_velocity_pct,
            'buy_pressure_pct': buy_pressure_pct,
            'large_bar_count': large_bar_count,
            'vwap_distance_pct': vwap_distance_pct,
            'median_range': round(median_range, 4),
        }

    def _latest_bar_age_seconds(self, df: pd.DataFrame, now_epoch: float) -> Optional[float]:
        """Return age in seconds of the latest bar timestamp, if available."""
        latest_ts = None
        for col in ('timestamp', 'time', 'ts', 'tradeTime', 'trade_time'):
            if col in df.columns:
                try:
                    val = df[col].max()
                    latest_ts = float(pd.to_numeric(val, errors='coerce'))
                    if pd.isna(latest_ts):
                        latest_ts = self._parse_timestamp(val)
                    if latest_ts and latest_ts > 1_000_000_000_000:
                        latest_ts = latest_ts / 1000.0
                    break
                except Exception:
                    continue
        if latest_ts and latest_ts > 1_000_000_000:
            return max(0.0, now_epoch - latest_ts)
        # Try index if DatetimeIndex
        if hasattr(df.index, 'max'):
            try:
                ts = pd.to_datetime(df.index.max())
                if pd.notna(ts):
                    return max(0.0, now_epoch - ts.timestamp())
            except Exception:
                pass
        return None

    def analyze_ticker(self, ticker: str, bars_15s, quote: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Volume-based activity indicator.

        The old 15s-bar composite score produced false aggressive labels on stale
        after-hours bars (e.g., VEEE looked busy because the last bars contained a
        closing-volume spike). We now derive the signal from the quote's current
        volume versus its average daily volume — a much harder to fake measure of
        whether the stock is actually trading today.

        Labels:
            🔥 high volume   : rvol >= 2.0
            ⚡ moderate volume: rvol 1.0 – 1.99
            🌱 low volume    : rvol < 1.0
            — N/A            : ASX / no data
        """
        import pandas as pd
        from datetime import datetime, timezone

        empty_result = {
            'ticker': ticker,
            'valid': False,
            'stale': True,
            'no_move': False,
            'tape_score': 0,
            'reason': 'insufficient_volume_data',
            'volume_acceleration': 0.0,
            'price_velocity_pct': 0.0,
            'buy_pressure_pct': 0.0,
            'large_bar_count': 0,
            'vwap_distance_pct': 0.0,
            'last_trade_time': None,
            'rvol': 0.0,
            'volume_indicator': 'missing',
        }

        quote = quote or {}
        if not isinstance(quote, dict):
            quote = {}

        # Pull volume and ADV from quote
        volume = None
        for key in ('volume', 'totalVolume', 'vol', 'tradeVolume'):
            val = quote.get(key)
            if val:
                try:
                    v = float(pd.to_numeric(val, errors='coerce'))
                    if v and v > 0:
                        volume = v
                        break
                except Exception:
                    continue

        adv = None
        for key in ('avgVol3M', 'avgVol10D', 'averageVolume', 'avgVolume'):
            val = quote.get(key)
            if val:
                try:
                    a = float(pd.to_numeric(val, errors='coerce'))
                    if a and a > 0:
                        adv = a
                        break
                except Exception:
                    continue

        # Timestamp freshness
        quote_ts = None
        for key in ('trade_time', 'mkTradeTime', 'timestamp', 'last_trade_time', 'tradeTime', 'ts', 'time'):
            val = quote.get(key)
            if val:
                quote_ts = self._parse_timestamp(val)
                if quote_ts:
                    break

        last_trade_time = None
        stale_age_seconds = None
        now_epoch = datetime.now(timezone.utc).timestamp()
        if quote_ts and quote_ts > 1_000_000_000:
            last_trade_time = datetime.fromtimestamp(quote_ts, tz=timezone.utc).isoformat()
            stale_age_seconds = max(0, int(now_epoch - quote_ts))

        # If we have real volume + ADV, use it directly.
        if volume and adv and adv > 0:
            rvol = volume / adv
            # Classify
            if rvol >= 2.0:
                volume_indicator = 'high'
                tape_score = 8.0
            elif rvol >= 1.0:
                volume_indicator = 'moderate'
                tape_score = 5.0
            elif volume > 0:
                volume_indicator = 'low'
                tape_score = 2.0
            else:
                volume_indicator = 'missing'
                tape_score = 0.0

            # Merge live bar momentum when fresh bars are available (1m fallback is ok).
            last_price = float(quote.get('price', quote.get('close', quote.get('pprice', 0))) or 0)
            bar_df = self._to_dataframe(bars_15s)
            metrics = {
                'volume_acceleration': 0.0,
                'price_velocity_pct': 0.0,
                'buy_pressure_pct': 0.0,
                'large_bar_count': 0,
                'vwap_distance_pct': 0.0,
                'median_range': 0.0,
            }
            if not bar_df.empty:
                bar_age = self._latest_bar_age_seconds(bar_df, now_epoch)
                if bar_age is not None:
                    stale_age_seconds = max(stale_age_seconds or 0, int(bar_age))
                # Suppress stale/after-hours bar momentum to avoid gap-and-fade false positives.
                if bar_age is None or bar_age <= 300:
                    metrics = self._bar_metrics(bar_df, last_price or float(bar_df.iloc[-1]['close']))
                    source = 'unknown'
                    if 'source' in bar_df.columns:
                        try:
                            source = str(bar_df['source'].iloc[-1])
                        except Exception:
                            pass
                    logger.debug("Tape metrics for %s (source=%s, bar_age=%s): %s", ticker, source, bar_age, metrics)
                    # Boost tape score if bars show real intraday momentum.
                    if metrics.get('large_bar_count', 0) > 0 or metrics.get('price_velocity_pct', 0) != 0:
                        tape_score = max(tape_score, 4.0)

            return {
                'ticker': ticker,
                'valid': True,
                'stale': bool(stale_age_seconds and stale_age_seconds > 300),
                'no_move': volume <= 0,
                'tape_score': tape_score,
                'rvol': round(rvol, 2),
                'volume_indicator': volume_indicator,
                'volume': int(volume),
                'adv': int(adv),
                'recent_pct_of_adv': round((volume / adv) * 100, 2),
                'volume_acceleration': metrics['volume_acceleration'],
                'price_velocity_pct': metrics['price_velocity_pct'],
                'buy_pressure_pct': metrics['buy_pressure_pct'],
                'large_bar_count': metrics['large_bar_count'],
                'vwap_distance_pct': metrics['vwap_distance_pct'],
                'recent_volume': int(volume),
                'prior_volume': 0,
                'median_range': metrics['median_range'],
                'last_price': last_price,
                'vwap': self._calculate_vwap(bar_df) if not bar_df.empty else None,
                'last_trade_time': last_trade_time,
                'stale_age_seconds': stale_age_seconds,
            }

        # Fallback: try to use 15s bars, but only for live/stale diagnostics.
        # We deliberately do NOT score from bars to avoid after-hours false positives.
        df = self._to_dataframe(bars_15s)
        if df.empty or len(df) < 4:
            return empty_result

        # Check bar timestamp freshness
        latest_ts = None
        for col in ('timestamp', 'time', 'ts', 'tradeTime', 'trade_time'):
            if col in df.columns:
                try:
                    val = df[col].max()
                    latest_ts = float(pd.to_numeric(val, errors='coerce'))
                    if pd.isna(latest_ts):
                        latest_ts = self._parse_timestamp(val)
                    if latest_ts and latest_ts > 1_000_000_000_000:
                        latest_ts = latest_ts / 1000.0
                    break
                except Exception:
                    continue

        if latest_ts and latest_ts > 1_000_000_000:
            bar_age = max(0, int(now_epoch - latest_ts))
            if stale_age_seconds is None or bar_age > stale_age_seconds:
                stale_age_seconds = bar_age
            if not last_trade_time:
                last_trade_time = datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat()

        total_bar_volume = float(df['volume'].sum())
        # If we don't have ADV, we can't classify reliably — mark as low/quiet
        volume_indicator = 'low'
        tape_score = 2.0
        rvol = 0.0
        if adv and adv > 0:
            rvol = total_bar_volume / adv
            if rvol >= 2.0:
                volume_indicator = 'high'
                tape_score = 8.0
            elif rvol >= 1.0:
                volume_indicator = 'moderate'
                tape_score = 5.0

        end_price = float(df.iloc[-1]['close']) if len(df) else 0.0

        return {
            'ticker': ticker,
            'valid': True,
            'stale': bool(stale_age_seconds and stale_age_seconds > 300),
            'no_move': total_bar_volume <= 0,
            'tape_score': tape_score,
            'rvol': round(rvol, 2),
            'volume_indicator': volume_indicator,
            'volume': int(total_bar_volume),
            'adv': int(adv) if adv else None,
            'recent_pct_of_adv': round((total_bar_volume / adv) * 100, 2) if adv else 0.0,
            'volume_acceleration': 0.0,
            'price_velocity_pct': 0.0,
            'buy_pressure_pct': 0.0,
            'large_bar_count': 0,
            'vwap_distance_pct': 0.0,
            'recent_volume': int(total_bar_volume),
            'prior_volume': 0,
            'median_range': 0.0,
            'last_price': round(end_price, 4),
            'vwap': None,
            'last_trade_time': last_trade_time,
            'stale_age_seconds': stale_age_seconds,
        }

    @staticmethod
    def _calculate_vwap(df: pd.DataFrame) -> Optional[float]:
        """Compute VWAP from OHLCV bars using typical price."""
        if df.empty or df['volume'].sum() == 0:
            return None
        typical = (df['high'] + df['low'] + df['close']) / 3
        vwap = (typical * df['volume']).sum() / df['volume'].sum()
        return float(vwap)

    @staticmethod
    def _parse_timestamp(val) -> Optional[float]:
        """Parse a timestamp value (epoch int/float or ISO string) to epoch seconds."""
        if val is None:
            return None
        try:
            num = float(pd.to_numeric(val, errors='coerce'))
            if not pd.isna(num):
                if num > 1_000_000_000_000:
                    return num / 1000.0
                return num
        except Exception:
            pass
        try:
            from dateutil import parser as _parser
            dt = _parser.parse(str(val))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
        return None


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    # Quick self-test with synthetic 15s bars
    np.random.seed(0)
    bars = []
    price = 10.0
    for i in range(40):
        o = price
        c = price + np.random.uniform(-0.05, 0.08)
        h = max(o, c) + np.random.uniform(0, 0.03)
        l = min(o, c) - np.random.uniform(0, 0.03)
        v = np.random.randint(1000, 5000)
        bars.append({'open': o, 'high': h, 'low': l, 'close': c, 'volume': v})
        price = c
    ta = TapeAnalyzer()
    print(ta.analyze_ticker('TEST', bars))
