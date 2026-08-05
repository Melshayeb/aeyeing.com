#!/usr/bin/env python3
"""
OzMoEg Money Maker — Trade Plan Generator
Creates entry/exit plans with fixed risk % and ATR-adjusted stops.
"""
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class TradePlanner:
    """Generate complete scalp trade plans with risk management."""

    def __init__(self, config: Dict[str, Any]):
        self.cfg = config

    def plan_trade(self, ticker: str, entry_price: float, atr: float,
                   confidence: str = "MED", account_balance: float = 10000.0) -> Dict[str, Any]:
        """
        Generate a complete trade plan based on Ahmed Khaled CMT momentum scalping.
        Position sizing follows the "golden triangle" from the video:
            daily_risk_budget = account_balance × max_daily_loss_pct
            risk_per_trade (R) = daily_risk_budget / max_trades_per_day
            shares = R / (entry_price - stop)
        NO fixed time stop — exit when momentum dies or candlestick reverses.

        Args:
            ticker: Stock symbol
            entry_price: Planned entry price
            atr: Current ATR value
            confidence: HIGH, MED, or LOW
            account_balance: Current account balance for sizing
        """
        if entry_price <= 0:
            return {'valid': False, 'error': 'Invalid entry price'}

        stop_pct = self.cfg.get('stop_loss_pct', 2.0)
        use_video_sizing = self.cfg.get('video_sizing', True)

        # Initial stop based on percentage; also enforce Webull's documented 0.1% leg-spacing
        # minimum with a tiny safety margin (0.15%) so bracket orders are never rejected on
        # extremely low-priced stocks where rounding could make the stop too tight.
        min_stop_pct = 0.15
        effective_stop_pct = max(stop_pct, min_stop_pct)
        stop = entry_price * (1 - effective_stop_pct / 100)

        # Adjust stop by ATR if ATR-based stop is usable.
        if atr > 0:
            atr_stop = entry_price - (0.5 * atr)
            # Never let ATR widen the stop beyond the configured percentage stop.
            # Picking the tighter (higher) stop preserves R:R. AU limited mode already
            # uses this behaviour; US mode was inverted and let pre-market volatility
            # collapse R:R.
            stop = max(stop, atr_stop)

        # Ensure stop is not too tight (at least 1% away) — but only for non-AU.
        # In AU limited-data mode we rely on a synthetic ATR stop and the 1% floor
        # would collapse R:R, so we skip the floor when atr is provided.
        # NOTE: Webull bracket orders require stop/take-profit legs to be at least 0.1% apart
        # from the stock price; the min_stop_pct guard above already covers that, and the 1% floor
        # here adds a US-only safety margin for volatile small-caps.
        if self.cfg.get('market', '').lower() == 'au' and atr > 0:
            logger.debug("%s AU mode: skipping 1%% stop floor to preserve synthetic ATR stop", ticker)
        else:
            min_stop = entry_price * 0.99
            if stop > min_stop:
                stop = min_stop

        # Round stop to a sensible price precision (Webull minimum tick is $0.0001 for many US stocks)
        stop = round(stop, 4)

        risk_per_share = entry_price - stop
        if risk_per_share <= 0:
            risk_per_share = entry_price * stop_pct / 100
            stop = entry_price - risk_per_share

        # --- Video formula position sizing ---
        # Daily risk budget and per-trade risk unit (R)
        daily_risk_budget = account_balance * (self.cfg.get('max_daily_loss_pct', 3.0) / 100)
        max_trades_per_day = max(1, self.cfg.get('max_trades_per_day', 3))
        risk_amount = daily_risk_budget / max_trades_per_day

        # Cap position value to configured max position % of account
        max_position_value = account_balance * (self.cfg.get('max_position_pct', 25.0) / 100)
        max_shares_by_capital = int(max_position_value / entry_price)

        if use_video_sizing:
            # Golden triangle: shares = R / stop_distance
            raw_shares = risk_amount / risk_per_share if risk_per_share > 0 else 0
            shares = max(1, round(raw_shares))
            # Sanity cap: cannot exceed max position % of account
            shares = min(shares, max(max_shares_by_capital, 1))
            position_value = shares * entry_price

            # Targets based on minimum Risk:Reward ratios from the video (1:2, 1:3, 1:5)
            t1 = entry_price + (2.0 * risk_per_share)
            t2 = entry_price + (3.0 * risk_per_share)
            t3 = entry_price + (5.0 * risk_per_share)
        else:
            # Legacy fixed-$ test position sizing
            test_dollars = self.cfg.get('test_trade_dollars', 100.0)
            shares = max(1, round(test_dollars / entry_price))
            shares = min(shares, max(max_shares_by_capital, 1))
            position_value = shares * entry_price
            target1_pct = self.cfg.get('target_1_pct', 3.0)
            target2_pct = self.cfg.get('target_2_pct', 5.0)
            target3_pct = self.cfg.get('target_3_pct', 8.0)
            t1 = entry_price * (1 + target1_pct / 100)
            t2 = entry_price * (1 + target2_pct / 100)
            t3 = entry_price * (1 + target3_pct / 100)

        # Risk:Reward based on actual risk per share and T1 reward
        reward_t1 = t1 - entry_price
        risk_reward = round(reward_t1 / risk_per_share, 2) if risk_per_share > 0 else 0

        plan = {
            'valid': True,
            'ticker': ticker,
            'entry': round(entry_price, 4),
            'stop': round(stop, 4),
            'targets': {
                't1': round(t1, 4),
                't2': round(t2, 4),
                't3': round(t3, 4)
            },
            'risk_per_share': round(risk_per_share, 4),
            'risk_amount': round(risk_amount, 2),
            'daily_risk_budget': round(daily_risk_budget, 2),
            'risk_unit_label': f"R = ${round(risk_amount, 2)} (3% daily ÷ {max_trades_per_day} trades)",
            'shares': shares,
            'position_value': round(position_value, 2),
            'risk_reward': risk_reward,
            'confidence': confidence,
            'strategy': 'Demand zone + candlestick confirmation scalp',
            'exit_rules': {
                'momentum_based': True,
                'time_based': False,
                'trail_breakeven_at': '+1%',
                'hard_stop': f"${round(stop, 4)}"
            }
        }

        logger.info("Plan generated for %s: entry=%.4f, stop=%.4f, R=%.2f, shares=%d, R:R=%.2f",
                    ticker, plan['entry'], plan['stop'], plan['risk_amount'], plan['shares'], plan['risk_reward'])
        return plan

    def plan_exit_strategy(self, plan: Dict[str, Any]) -> str:
        """Generate human-readable exit strategy text."""
        lines = [
            f"Exit Strategy for {plan['ticker']} (Momentum Scalp Method):",
            f"",
            f"1. Sell 50% ({plan['shares'] // 2} shares) at Target 1: ${plan['targets']['t1']} (+{self.cfg.get('target_1_pct',3)}%)",
            f"2. Sell 25% ({plan['shares'] // 4} shares) at Target 2: ${plan['targets']['t2']} (+{self.cfg.get('target_2_pct',5)}%)",
            f"3. Trail remaining 25% with 2% cushion above Target 3: ${plan['targets']['t3']}",
            f"4. Hard stop: ${plan['stop']} (trigger immediately if hit)",
            f"5. MOMENTUM EXIT: Close position if:",
            f"   - Bearish engulfing or shooting star candle appears",
            f"   - Tape slows down after big green candle (no follow-through)",
            f"   - Volume drops below 1.5x average (buyers exhausted)",
            f"   - Price approaches a supply zone (resistance)",
            f"6. Trail stop to breakeven once up +1%",
            f"7. NEVER hold past your strategy — exit when momentum dies, not on a timer"
        ]
        return "\n".join(lines)
