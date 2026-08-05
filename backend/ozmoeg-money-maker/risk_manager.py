#!/usr/bin/env python3
"""
OzMoEg Money Maker — Risk Manager
Position sizing, PDT tracking, daily loss limits, and trading halts.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Tuple, List

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Risk management per Ahmed Khaled discipline rules.
    - Max 1% risk per trade
    - Max 3% loss per day
    - Max 2 open positions
    - Stop after 3 consecutive losses
    - PDT rule tracking (3 day trades per 5 rolling days)
    """

    PDT_LIMIT = 3

    def __init__(self, config: Dict[str, Any], state_dir: str = None):
        self.cfg = config
        self.state_dir = Path(state_dir or Path.home() / ".hermes/skills/ozmoeg-money-maker/state")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.state_dir / "risk_state.json"
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to load risk state: %s", e)
        return {
            'day_trades': [],
            'daily_pnl': {},
            'consecutive_losses': 0,
            'open_positions': [],
            'last_reset': datetime.now().isoformat()
        }

    def _save_state(self):
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def can_trade(self) -> Tuple[bool, str]:
        """Check if trading is currently allowed."""
        # Check PDT
        recent_trades = [
            d for d in self.state.get('day_trades', [])
            if datetime.fromisoformat(d) > datetime.now() - timedelta(days=5)
        ]
        if len(recent_trades) >= self.PDT_LIMIT:
            return False, f"PDT limit reached: {len(recent_trades)}/3 day trades in last 5 days"

        # Check daily loss limit
        today = datetime.now().strftime('%Y-%m-%d')
        daily_pnl = self.state.get('daily_pnl', {}).get(today, 0)
        account_balance = self.cfg.get('account_balance', 10000)
        daily_loss_limit = account_balance * 0.03
        if daily_pnl <= -daily_loss_limit:
            return False, f"Daily loss limit reached: ${daily_pnl:.2f} (limit: -${daily_loss_limit:.2f})"

        # Check consecutive losses
        if self.state.get('consecutive_losses', 0) >= 3:
            return False, f"3 consecutive losses — take a break. Reset at midnight."

        # Check max open positions
        open_count = len(self.state.get('open_positions', []))
        if open_count >= 2:
            return False, f"Max 2 open positions reached ({open_count})"

        return True, "OK"

    def position_size(self, account_balance: float, entry: float, stop: float) -> int:
        """
        Calculate position size using fixed fractional risk.
        Never risk more than 1% per trade, never allocate more than 25% per position.
        """
        risk_pct = self.cfg.get('risk_per_trade_pct', 1.0)
        max_position_pct = self.cfg.get('max_position_pct', 25.0)

        risk_amount = account_balance * (risk_pct / 100)
        risk_per_share = abs(entry - stop)
        if risk_per_share == 0:
            logger.warning("Risk per share is zero — cannot size position")
            return 0

        shares = int(risk_amount / risk_per_share)
        max_shares = int((account_balance * max_position_pct / 100) / entry)
        final_shares = min(shares, max_shares)

        logger.info("Position size: %d shares (risk=$%.2f, risk/share=$%.3f, max=%d)",
                    final_shares, risk_amount, risk_per_share, max_shares)
        return final_shares

    def record_trade(self, ticker: str, entry: float, exit_price: float,
                     shares: int, is_day_trade: bool = True):
        """Record a completed trade and update state."""
        pnl = (exit_price - entry) * shares
        today = datetime.now().strftime('%Y-%m-%d')

        # Update daily P&L
        daily = self.state.setdefault('daily_pnl', {})
        daily[today] = daily.get(today, 0) + pnl

        # Update consecutive losses
        if pnl < 0:
            self.state['consecutive_losses'] = self.state.get('consecutive_losses', 0) + 1
        else:
            self.state['consecutive_losses'] = 0

        # Record day trade
        if is_day_trade:
            self.state.setdefault('day_trades', []).append(datetime.now().isoformat())

        # Remove from open positions
        self.state['open_positions'] = [
            p for p in self.state.get('open_positions', [])
            if p.get('ticker') != ticker
        ]

        self._save_state()
        logger.info("Trade recorded: %s P&L=$%.2f, consecutive_losses=%d",
                    ticker, pnl, self.state['consecutive_losses'])

    def add_open_position(self, ticker: str, entry: float, stop: float,
                          shares: int, targets: Dict[str, float]):
        """Track an open position."""
        self.state.setdefault('open_positions', []).append({
            'ticker': ticker,
            'entry': entry,
            'stop': stop,
            'shares': shares,
            'targets': targets,
            'opened_at': datetime.now().isoformat()
        })
        self._save_state()

    def get_open_positions(self) -> List[Dict]:
        return self.state.get('open_positions', [])

    def daily_summary(self) -> Dict[str, Any]:
        """Get today's trading summary."""
        today = datetime.now().strftime('%Y-%m-%d')
        pnl = self.state.get('daily_pnl', {}).get(today, 0)
        trades_today = len([
            d for d in self.state.get('day_trades', [])
            if d.startswith(today)
        ])
        return {
            'date': today,
            'pnl': round(pnl, 2),
            'trades': trades_today,
            'consecutive_losses': self.state.get('consecutive_losses', 0),
            'open_positions': len(self.state.get('open_positions', [])),
            'pdt_remaining': max(0, self.PDT_LIMIT - len([
                d for d in self.state.get('day_trades', [])
                if datetime.fromisoformat(d) > datetime.now() - timedelta(days=5)
            ]))
        }

    def reset_daily(self):
        """Reset daily counters (run at midnight ET)."""
        today = datetime.now().strftime('%Y-%m-%d')
        self.state['daily_pnl'][today] = 0
        self._save_state()
        logger.info("Daily risk counters reset for %s", today)
