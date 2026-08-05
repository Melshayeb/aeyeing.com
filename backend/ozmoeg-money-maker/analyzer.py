#!/usr/bin/env python3
"""
OzMoEg Money Maker — Technical Analyzer
Supply/demand zones, candlestick patterns, ATR, and trend analysis.
"""
import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class TechnicalAnalyzer:
    """Technical analysis engine for micro-scalp setups."""

    def __init__(self, config: Dict[str, Any] = None):
        """Accept optional config for compatibility with main.py."""
        self.cfg = config or {}

    def bars_to_dataframe(self, bars) -> pd.DataFrame:
        """Convert Webull bars (list of dicts or DataFrame) to DataFrame."""
        if bars is None:
            return pd.DataFrame()
        if isinstance(bars, pd.DataFrame):
            return bars
        if not isinstance(bars, list) or not bars:
            return pd.DataFrame()
        df = pd.DataFrame(bars)
        # Rename columns to standard OHLCV
        col_map = {
            'open': 'open', 'high': 'high', 'low': 'low',
            'close': 'close', 'volume': 'volume',
            'timestamp': 'timestamp', 'time': 'time'
        }
        for old, new in col_map.items():
            if old in df.columns and new not in df.columns:
                df = df.rename(columns={old: new})
        return df

    def calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range for stop placement."""
        if df.empty or len(df) < period + 1:
            return pd.Series([0])
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        return atr

    def identify_demand_zones(self, df: pd.DataFrame, lookback: int = 30) -> List[Dict]:
        """
        Identify demand zones: areas where price bounced 2+ times.
        Simplified: local lows with clustering.
        """
        if df.empty or len(df) < lookback:
            return []

        df = df.copy().tail(lookback)
        lows = df['low'].values
        zones = []

        # Find local minima
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                zone_price = round(lows[i], 2)
                # Check if close to existing zone (within 1%)
                merged = False
                for zone in zones:
                    if abs(zone['price'] - zone_price) / zone['price'] < 0.01:
                        zone['touches'] += 1
                        zone['price'] = min(zone['price'], zone_price)
                        merged = True
                        break
                if not merged:
                    zones.append({'price': zone_price, 'touches': 1})

        # Filter: require 2+ touches
        zones = [z for z in zones if z['touches'] >= 2]
        zones.sort(key=lambda x: x['price'], reverse=True)  # highest demand first
        return zones

    def identify_supply_zones(self, df: pd.DataFrame, lookback: int = 30) -> List[Dict]:
        """Identify supply zones: areas where price rejected 2+ times."""
        if df.empty or len(df) < lookback:
            return []

        df = df.copy().tail(lookback)
        highs = df['high'].values
        zones = []

        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                zone_price = round(highs[i], 2)
                merged = False
                for zone in zones:
                    if abs(zone['price'] - zone_price) / zone['price'] < 0.01:
                        zone['touches'] += 1
                        zone['price'] = max(zone['price'], zone_price)
                        merged = True
                        break
                if not merged:
                    zones.append({'price': zone_price, 'touches': 1})

        zones = [z for z in zones if z['touches'] >= 2]
        zones.sort(key=lambda x: x['price'])
        return zones

    def is_bullish_engulfing(self, df: pd.DataFrame) -> bool:
        """Check if last two candles form bullish engulfing."""
        if len(df) < 2:
            return False
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        # Prev bearish, curr bullish
        if prev['close'] < prev['open'] and curr['close'] > curr['open']:
            # Current body engulfs previous body
            if curr['open'] < prev['close'] and curr['close'] > prev['open']:
                return True
        return False

    def is_hammer(self, df: pd.DataFrame) -> bool:
        """Check if last candle is a hammer (bullish reversal at lows)."""
        if len(df) < 1:
            return False
        c = df.iloc[-1]
        body = abs(c['close'] - c['open'])
        upper_shadow = c['high'] - max(c['close'], c['open'])
        lower_shadow = min(c['close'], c['open']) - c['low']

        # Hammer: small body, little/no upper shadow, long lower shadow
        if lower_shadow > 2 * body and upper_shadow < body:
            # Hammer must be near recent lows
            if len(df) >= 10:
                recent_low = df['low'].tail(10).min()
                if c['low'] <= recent_low * 1.01:
                    return True
        return False

    def is_shooting_star(self, df: pd.DataFrame) -> bool:
        """Check if last candle is shooting star (bearish reversal at highs)."""
        if len(df) < 1:
            return False
        c = df.iloc[-1]
        body = abs(c['close'] - c['open'])
        upper_shadow = c['high'] - max(c['close'], c['open'])
        lower_shadow = min(c['close'], c['open']) - c['low']

        if upper_shadow > 2 * body and lower_shadow < body:
            if len(df) >= 10:
                recent_high = df['high'].tail(10).max()
                if c['high'] >= recent_high * 0.99:
                    return True
        return False

    def is_bearish_engulfing(self, df: pd.DataFrame) -> bool:
        """Bearish engulfing for exit signals."""
        if len(df) < 2:
            return False
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        if prev['close'] > prev['open'] and curr['close'] < curr['open']:
            if curr['open'] > prev['close'] and curr['close'] < prev['open']:
                return True
        return False

    def get_candlestick_signal(self, df: pd.DataFrame) -> str:
        """Return the most recent candlestick signal."""
        if self.is_bullish_engulfing(df):
            return "BULLISH_ENGULFING"
        if self.is_hammer(df):
            return "HAMMER"
        if self.is_bearish_engulfing(df):
            return "BEARISH_ENGULFING"
        if self.is_shooting_star(df):
            return "SHOOTING_STAR"
        return "NONE"

    def calculate_vwap(self, df: pd.DataFrame) -> float:
        """Calculate Volume Weighted Average Price."""
        if df.empty or 'volume' not in df.columns:
            return 0.0
        tp = (df['high'] + df['low'] + df['close']) / 3
        return (tp * df['volume']).sum() / df['volume'].sum()

    def calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate RSI for overbought/oversold."""
        if len(df) < period + 1:
            return 50.0
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.iloc[-1] if not rsi.empty else 50.0

    def analyze_setup(self, ticker: str, bars: List[Dict], quote: Dict) -> Dict[str, Any]:
        """
        Complete technical analysis for a scalp setup.
        Returns structured analysis with demand zones, signals, and levels.
        """
        df = self.bars_to_dataframe(bars)
        if df.empty:
            return {'valid': False, 'error': 'No bar data'}

        atr = self.calculate_atr(df)
        demand_zones = self.identify_demand_zones(df)
        supply_zones = self.identify_supply_zones(df)
        candle_signal = self.get_candlestick_signal(df)
        vwap = self.calculate_vwap(df)
        rsi = self.calculate_rsi(df)
        current_price = float(quote.get('close') or quote.get('price', 0) or 0)
        if isinstance(current_price, str):
            current_price = float(current_price)

        # Determine if we're near a demand zone
        near_demand = False
        nearest_demand = None
        if demand_zones and current_price > 0:
            for dz in demand_zones:
                if abs(current_price - dz['price']) / current_price < 0.02:
                    near_demand = True
                    nearest_demand = dz
                    break

        # Determine if we're near a supply zone
        near_supply = False
        if supply_zones and current_price > 0:
            for sz in supply_zones:
                if abs(sz['price'] - current_price) / current_price < 0.02:
                    near_supply = True
                    break

        return {
            'valid': True,
            'ticker': ticker,
            'current_price': current_price,
            'atr': round(atr.iloc[-1], 4) if not atr.empty else 0,
            'atr_pct': round((atr.iloc[-1] / current_price) * 100, 2) if current_price > 0 and not atr.empty else 0,
            'demand_zones': demand_zones[:3],
            'supply_zones': supply_zones[:3],
            'nearest_demand': nearest_demand,
            'near_demand': near_demand,
            'near_supply': near_supply,
            'candle_signal': candle_signal,
            'vwap': round(vwap, 2),
            'rsi': round(rsi, 1),
            'trend_above_vwap': current_price > vwap if current_price > 0 else False,
            'recent_volume': int(df['volume'].iloc[-1]) if 'volume' in df.columns else 0,
            'avg_volume': int(df['volume'].tail(20).mean()) if 'volume' in df.columns and len(df) >= 20 else 0
        }

    def analyze(self, stock: Dict[str, Any]) -> Dict[str, Any]:
        """Compatibility wrapper used by main.py.

        Extracts ticker, bars and quote from a Webull-style stock payload and
        delegates to analyze_setup().  No bars are available from the ranking
        endpoint, so the analysis focuses on the current quote.
        """
        ticker = ''
        bars = []
        quote = {}
        if isinstance(stock, dict):
            t = stock.get('ticker', {})
            if isinstance(t, dict):
                ticker = t.get('symbol', '') or t.get('disSymbol', '')
                quote = {
                    'price': float(t.get('pprice', 0) or t.get('close', 0) or 0),
                    'close': float(t.get('close', 0) or 0),
                    'volume': int(t.get('volume', 0) or 0),
                    'marketValue': float(t.get('marketValue', 0) or 0),
                }
            else:
                ticker = str(t)
        return self.analyze_setup(ticker, bars, quote)
