from __future__ import annotations

from typing import Any, Dict, List

from zone_hunter.backtest.backtester import BacktestTrade


def build_performance_report(
    trades: List[BacktestTrade],
    cancelled_signals: int = 0,
) -> Dict[str, Any]:
    closed = [t for t in trades if t.outcome != "OPEN"]
    total_signals = len(trades)
    wins = [t for t in closed if t.pnl_r > 0]
    losses = [t for t in closed if t.pnl_r < 0]

    gross_profit = sum(t.pnl_r for t in wins)
    gross_loss = abs(sum(t.pnl_r for t in losses))
    win_rate = (len(wins) / len(closed) * 100.0) if closed else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    expectancy = (sum(t.pnl_r for t in closed) / len(closed)) if closed else 0.0
    avg_rr = (sum(t.risk_reward for t in trades) / total_signals) if total_signals else 0.0

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in closed:
        equity += t.pnl_r
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd

    by_market: Dict[str, int] = {}
    by_setup: Dict[str, int] = {}
    for t in trades:
        by_market[t.market] = by_market.get(t.market, 0) + 1
        by_setup[t.setup_type] = by_setup.get(t.setup_type, 0) + 1

    return {
        "total_signals": total_signals,
        "closed_signals": len(closed),
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "INF",
        "expectancy_r": round(expectancy, 4),
        "max_drawdown_r": round(max_dd, 4),
        "avg_rr": round(avg_rr, 4),
        "by_market": by_market,
        "by_setup": by_setup,
        "cancelled_signals": cancelled_signals,
    }
