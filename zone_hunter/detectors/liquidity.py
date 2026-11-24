from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd


@dataclass
class LiquidityLevel:
    level_id: str
    market: str
    timeframe: str
    pool_type: str  # "BSL" or "SSL"
    subtype: str  # "SWING_HIGH", "SWING_LOW", "EQUAL_HIGH", "EQUAL_LOW"
    price: float
    formed_at: Any
    candle_indices: List[int]
    swept: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LiquiditySweep:
    sweep_id: str
    market: str
    timeframe: str
    direction_bias: str  # "SELL" (setelah BSL sweep) atau "BUY" (setelah SSL sweep)
    pool_type: str  # "BSL" atau "SSL"
    swept_level: float
    extreme_price: float
    sweep_time: Any
    candle_index: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class LiquidityDetector:
    """Detektor Swing High/Low, Equal High/Low, BSL/SSL, dan Liquidity Sweep."""

    def __init__(
        self,
        left_bars: int = 3,
        right_bars: int = 3,
        atr_period: int = 14,
        equal_tolerance_atr: float = 0.15,
        sweep_window: int = 2,
    ) -> None:
        self.left_bars = left_bars
        self.right_bars = right_bars
        self.atr_period = atr_period
        self.equal_tolerance_atr = equal_tolerance_atr
        self.sweep_window = sweep_window

    @staticmethod
    def _compute_atr(df: pd.DataFrame, period: int) -> pd.Series:
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return tr.rolling(window=period, min_periods=1).mean()

    def detect(
        self,
        df: pd.DataFrame,
        market: str,
        timeframe: str,
    ) -> Dict[str, Any]:
        required_cols = {"high", "low", "close"}
        if df is None or df.empty or not required_cols.issubset(df.columns):
            return {"levels": [], "sweeps": []}

        data = df.reset_index(drop=True).copy()
        n = len(data)
        min_len = self.left_bars + self.right_bars + 1
        if n < min_len:
            return {"levels": [], "sweeps": []}

        highs = data["high"].astype(float).to_numpy()
        lows = data["low"].astype(float).to_numpy()
        closes = data["close"].astype(float).to_numpy()
        times = data["timestamp"].tolist() if "timestamp" in data.columns else list(range(n))
        atr = self._compute_atr(data, self.atr_period).to_numpy()

        swing_highs: List[tuple[int, float]] = []
        swing_lows: List[tuple[int, float]] = []

        for i in range(self.left_bars, n - self.right_bars):
            win_high = highs[i - self.left_bars : i + self.right_bars + 1]
            win_low = lows[i - self.left_bars : i + self.right_bars + 1]

            if highs[i] == np.max(win_high) and np.sum(win_high == highs[i]) == 1:
                swing_highs.append((i, float(highs[i])))
            if lows[i] == np.min(win_low) and np.sum(win_low == lows[i]) == 1:
                swing_lows.append((i, float(lows[i])))

        levels: List[LiquidityLevel] = []
        sweeps: List[LiquiditySweep] = []

        used_sh = set()
        for idx_a, (i_a, p_a) in enumerate(swing_highs):
            if idx_a in used_sh:
                continue
            tol = max(float(atr[i_a]) * self.equal_tolerance_atr, 1e-12)
            cluster_indices = [i_a]
            cluster_prices = [p_a]
            used_sh.add(idx_a)

            for idx_b in range(idx_a + 1, len(swing_highs)):
                i_b, p_b = swing_highs[idx_b]
                if abs(p_b - p_a) <= tol:
                    cluster_indices.append(i_b)
                    cluster_prices.append(p_b)
                    used_sh.add(idx_b)

            is_eq = len(cluster_indices) >= 2
            lvl_price = float(np.mean(cluster_prices)) if is_eq else float(p_a)
            subtype = "EQUAL_HIGH" if is_eq else "SWING_HIGH"
            lvl = LiquidityLevel(
                level_id=f"LIQ_{market}_{timeframe}_{subtype}_{cluster_indices[0]}",
                market=market,
                timeframe=timeframe,
                pool_type="BSL",
                subtype=subtype,
                price=lvl_price,
                formed_at=times[cluster_indices[-1]],
                candle_indices=cluster_indices,
                swept=False,
            )

            start_scan = cluster_indices[-1] + 1
            for j in range(start_scan, n):
                if highs[j] > lvl_price:
                    end_win = min(j + self.sweep_window, n)
                    reclaimed = any(closes[k] < lvl_price for k in range(j, end_win))
                    if reclaimed:
                        lvl.swept = True
                        sweeps.append(
                            LiquiditySweep(
                                sweep_id=f"SWEEP_{market}_{timeframe}_BSL_{cluster_indices[-1]}_{j}",
                                market=market,
                                timeframe=timeframe,
                                direction_bias="SELL",
                                pool_type="BSL",
                                swept_level=lvl_price,
                                extreme_price=float(np.max(highs[j:end_win])),
                                sweep_time=times[j],
                                candle_index=j,
                                metadata={"level_id": lvl.level_id, "subtype": subtype},
                            )
                        )
                        break

            levels.append(lvl)

        used_sl = set()
        for idx_a, (i_a, p_a) in enumerate(swing_lows):
            if idx_a in used_sl:
                continue
            tol = max(float(atr[i_a]) * self.equal_tolerance_atr, 1e-12)
            cluster_indices = [i_a]
            cluster_prices = [p_a]
            used_sl.add(idx_a)

            for idx_b in range(idx_a + 1, len(swing_lows)):
                i_b, p_b = swing_lows[idx_b]
                if abs(p_b - p_a) <= tol:
                    cluster_indices.append(i_b)
                    cluster_prices.append(p_b)
                    used_sl.add(idx_b)

            is_eq = len(cluster_indices) >= 2
            lvl_price = float(np.mean(cluster_prices)) if is_eq else float(p_a)
            subtype = "EQUAL_LOW" if is_eq else "SWING_LOW"
            lvl = LiquidityLevel(
                level_id=f"LIQ_{market}_{timeframe}_{subtype}_{cluster_indices[0]}",
                market=market,
                timeframe=timeframe,
                pool_type="SSL",
                subtype=subtype,
                price=lvl_price,
                formed_at=times[cluster_indices[-1]],
                candle_indices=cluster_indices,
                swept=False,
            )

            start_scan = cluster_indices[-1] + 1
            for j in range(start_scan, n):
                if lows[j] < lvl_price:
                    end_win = min(j + self.sweep_window, n)
                    reclaimed = any(closes[k] > lvl_price for k in range(j, end_win))
                    if reclaimed:
                        lvl.swept = True
                        sweeps.append(
                            LiquiditySweep(
                                sweep_id=f"SWEEP_{market}_{timeframe}_SSL_{cluster_indices[-1]}_{j}",
                                market=market,
                                timeframe=timeframe,
                                direction_bias="BUY",
                                pool_type="SSL",
                                swept_level=lvl_price,
                                extreme_price=float(np.min(lows[j:end_win])),
                                sweep_time=times[j],
                                candle_index=j,
                                metadata={"level_id": lvl.level_id, "subtype": subtype},
                            )
                        )
                        break

            levels.append(lvl)

        return {"levels": levels, "sweeps": sweeps}
