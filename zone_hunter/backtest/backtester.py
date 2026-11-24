from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

import pandas as pd


@dataclass
class BacktestTrade:
    signal_id: str
    market: str
    direction: str
    setup_type: str
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    outcome: str  # "WIN_TP1", "WIN_TP2", "LOSS_SL", "OPEN"
    pnl_r: float


class Backtester:
    """Simulator backtest closed-bar (tanpa look-ahead bias) & walk-forward window."""

    @staticmethod
    def evaluate_trade_closed_bars(
        trade: BacktestTrade,
        future_df: pd.DataFrame,
    ) -> BacktestTrade:
        if future_df is None or future_df.empty:
            trade.outcome = "OPEN"
            trade.pnl_r = 0.0
            return trade

        for _, row in future_df.iterrows():
            high = float(row["high"])
            low = float(row["low"])
            if trade.direction == "BUY":
                if low <= trade.stop_loss:
                    trade.outcome = "LOSS_SL"
                    trade.pnl_r = -1.0
                    return trade
                if high >= trade.take_profit_2:
                    trade.outcome = "WIN_TP2"
                    trade.pnl_r = max(trade.risk_reward * 1.5, trade.risk_reward)
                    return trade
                if high >= trade.take_profit_1:
                    trade.outcome = "WIN_TP1"
                    trade.pnl_r = trade.risk_reward
                    return trade
            else:
                if high >= trade.stop_loss:
                    trade.outcome = "LOSS_SL"
                    trade.pnl_r = -1.0
                    return trade
                if low <= trade.take_profit_2:
                    trade.outcome = "WIN_TP2"
                    trade.pnl_r = max(trade.risk_reward * 1.5, trade.risk_reward)
                    return trade
                if low <= trade.take_profit_1:
                    trade.outcome = "WIN_TP1"
                    trade.pnl_r = trade.risk_reward
                    return trade

        trade.outcome = "OPEN"
        trade.pnl_r = 0.0
        return trade

    def walk_forward_slices(
        self,
        df: pd.DataFrame,
        train_size: int = 200,
        test_size: int = 50,
        step_size: int = 50,
    ) -> List[Dict[str, pd.DataFrame]]:
        slices: List[Dict[str, pd.DataFrame]] = []
        n = len(df)
        start = 0
        while start + train_size + test_size <= n:
            train_end = start + train_size
            test_end = train_end + test_size
            slices.append(
                {
                    "train": df.iloc[start:train_end].reset_index(drop=True),
                    "test": df.iloc[train_end:test_end].reset_index(drop=True),
                }
            )
            start += step_size
        return slices
