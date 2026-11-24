from __future__ import annotations

import numpy as np
import pandas as pd


class VolatilityManager:
    """Menghitung ATR dan buffer volatilitas untuk penempatan SL dan entry retracement."""

    def __init__(self, atr_period: int = 14) -> None:
        self.atr_period = atr_period

    def compute_atr_series(self, df: pd.DataFrame) -> pd.Series:
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
        return tr.rolling(window=self.atr_period, min_periods=1).mean()

    def get_latest_atr(self, df: pd.DataFrame) -> float:
        if df is None or df.empty or not {"high", "low", "close"}.issubset(df.columns):
            return 0.0
        series = self.compute_atr_series(df.reset_index(drop=True))
        val = float(series.iloc[-1])
        return val if np.isfinite(val) and val > 0.0 else 0.0

    @staticmethod
    def compute_buffer(atr_value: float, multiplier: float) -> float:
        return max(0.0, float(atr_value)) * max(0.0, float(multiplier))
