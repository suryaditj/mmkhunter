from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd


@dataclass
class FairValueGap:
    fvg_id: str
    market: str
    timeframe: str
    direction: str  # "BUY" (Bullish FVG) or "SELL" (Bearish FVG)
    gap_low: float
    gap_high: float
    created_at: Any
    candle_index: int
    fill_ratio: float = 0.0  # 0.0 - 1.0
    fill_status: str = "UNFILLED"  # "UNFILLED", "PARTIALLY_FILLED", "FULLY_FILLED"
    metadata: Dict[str, Any] = field(default_factory=dict)


class FairValueGapDetector:
    """Detektor Bullish & Bearish Fair Value Gap beserta status partial/full fill."""

    def __init__(
        self,
        atr_period: int = 14,
        min_gap_atr: float = 0.0,
        full_fill_threshold: float = 0.999,
    ) -> None:
        self.atr_period = atr_period
        self.min_gap_atr = min_gap_atr
        self.full_fill_threshold = full_fill_threshold

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
    ) -> List[FairValueGap]:
        required_cols = {"high", "low", "close"}
        if df is None or df.empty or not required_cols.issubset(df.columns):
            return []

        data = df.reset_index(drop=True).copy()
        n = len(data)
        if n < 3:
            return []

        highs = data["high"].astype(float).to_numpy()
        lows = data["low"].astype(float).to_numpy()
        times = data["timestamp"].tolist() if "timestamp" in data.columns else list(range(n))
        atr = self._compute_atr(data, self.atr_period).to_numpy()

        fvgs: List[FairValueGap] = []

        for i in range(1, n - 1):
            current_atr = max(float(atr[i]), 1e-12)
            min_size = self.min_gap_atr * current_atr

            if lows[i + 1] > highs[i - 1]:
                gap_low = float(highs[i - 1])
                gap_high = float(lows[i + 1])
                gap_size = gap_high - gap_low
                if gap_size > 0 and gap_size >= min_size:
                    min_future_low = gap_high
                    if i + 2 < n:
                        min_future_low = min(gap_high, float(np.min(lows[i + 2 :])))
                    fill_ratio = float(np.clip((gap_high - min_future_low) / gap_size, 0.0, 1.0))
                    if fill_ratio >= self.full_fill_threshold:
                        fill_ratio = 1.0
                        status = "FULLY_FILLED"
                    elif fill_ratio > 0.0:
                        status = "PARTIALLY_FILLED"
                    else:
                        status = "UNFILLED"

                    fvgs.append(
                        FairValueGap(
                            fvg_id=f"FVG_{market}_{timeframe}_BUY_{i}",
                            market=market,
                            timeframe=timeframe,
                            direction="BUY",
                            gap_low=gap_low,
                            gap_high=gap_high,
                            created_at=times[i + 1],
                            candle_index=i,
                            fill_ratio=fill_ratio,
                            fill_status=status,
                            metadata={"gap_size": gap_size},
                        )
                    )

            elif highs[i + 1] < lows[i - 1]:
                gap_low = float(highs[i + 1])
                gap_high = float(lows[i - 1])
                gap_size = gap_high - gap_low
                if gap_size > 0 and gap_size >= min_size:
                    max_future_high = gap_low
                    if i + 2 < n:
                        max_future_high = max(gap_low, float(np.max(highs[i + 2 :])))
                    fill_ratio = float(np.clip((max_future_high - gap_low) / gap_size, 0.0, 1.0))
                    if fill_ratio >= self.full_fill_threshold:
                        fill_ratio = 1.0
                        status = "FULLY_FILLED"
                    elif fill_ratio > 0.0:
                        status = "PARTIALLY_FILLED"
                    else:
                        status = "UNFILLED"

                    fvgs.append(
                        FairValueGap(
                            fvg_id=f"FVG_{market}_{timeframe}_SELL_{i}",
                            market=market,
                            timeframe=timeframe,
                            direction="SELL",
                            gap_low=gap_low,
                            gap_high=gap_high,
                            created_at=times[i + 1],
                            candle_index=i,
                            fill_ratio=fill_ratio,
                            fill_status=status,
                            metadata={"gap_size": gap_size},
                        )
                    )

        return fvgs
