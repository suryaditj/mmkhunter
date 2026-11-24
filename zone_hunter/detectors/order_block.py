from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd


@dataclass
class OrderBlockZone:
    zone_id: str
    market: str
    timeframe: str
    direction: str  # "BUY" (Bullish OB) or "SELL" (Bearish OB)
    zone_low: float
    zone_high: float
    invalidation_price: float
    created_at: Any
    candle_index: int
    candle_timestamp: Any
    candle_ohlc: Dict[str, float]
    displacement_strength: float
    is_mitigated: bool = False
    is_invalidated: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class OrderBlockDetector:
    """Detektor Order Block berbasis displacement candle dan validasi struktur."""

    def __init__(
        self,
        atr_period: int = 14,
        displacement_body_atr: float = 1.2,
        lookback_structure: int = 5,
    ) -> None:
        self.atr_period = atr_period
        self.displacement_body_atr = displacement_body_atr
        self.lookback_structure = lookback_structure

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
    ) -> List[OrderBlockZone]:
        required_cols = {"open", "high", "low", "close"}
        if df is None or df.empty or not required_cols.issubset(df.columns):
            return []

        data = df.reset_index(drop=True).copy()
        if len(data) < self.atr_period + 3:
            return []

        opens = data["open"].astype(float).to_numpy()
        highs = data["high"].astype(float).to_numpy()
        lows = data["low"].astype(float).to_numpy()
        closes = data["close"].astype(float).to_numpy()
        times = data["timestamp"].tolist() if "timestamp" in data.columns else list(range(len(data)))
        atr = self._compute_atr(data, self.atr_period).to_numpy()

        obs: List[OrderBlockZone] = []
        n = len(data)

        for i in range(1, n - 1):
            current_atr = max(float(atr[i + 1]), 1e-12)
            disp_body = abs(float(closes[i + 1]) - float(opens[i + 1]))
            disp_ratio = disp_body / current_atr

            if disp_ratio < self.displacement_body_atr:
                continue

            struct_start = max(0, i - self.lookback_structure)
            prior_high = float(np.max(highs[struct_start:i]))
            prior_low = float(np.min(lows[struct_start:i]))

            if (
                closes[i] < opens[i]
                and closes[i + 1] > opens[i + 1]
                and closes[i + 1] > highs[i]
                and closes[i + 1] >= prior_high
            ):
                z_low = float(lows[i])
                z_high = float(highs[i])
                inv_price = z_low

                mitigated = False
                invalidated = False
                for j in range(i + 2, n):
                    if closes[j] < inv_price:
                        invalidated = True
                        break
                    if lows[j] <= z_high and highs[j] >= z_low:
                        mitigated = True

                obs.append(
                    OrderBlockZone(
                        zone_id=f"OB_{market}_{timeframe}_BUY_{i}",
                        market=market,
                        timeframe=timeframe,
                        direction="BUY",
                        zone_low=z_low,
                        zone_high=z_high,
                        invalidation_price=inv_price,
                        created_at=times[i + 1],
                        candle_index=i,
                        candle_timestamp=times[i],
                        candle_ohlc={
                            "open": float(opens[i]),
                            "high": float(highs[i]),
                            "low": float(lows[i]),
                            "close": float(closes[i]),
                        },
                        displacement_strength=float(min(disp_ratio / (self.displacement_body_atr * 2.0), 1.0)),
                        is_mitigated=mitigated,
                        is_invalidated=invalidated,
                        metadata={"displacement_index": i + 1, "prior_high": prior_high},
                    )
                )

            elif (
                closes[i] > opens[i]
                and closes[i + 1] < opens[i + 1]
                and closes[i + 1] < lows[i]
                and closes[i + 1] <= prior_low
            ):
                z_low = float(lows[i])
                z_high = float(highs[i])
                inv_price = z_high

                mitigated = False
                invalidated = False
                for j in range(i + 2, n):
                    if closes[j] > inv_price:
                        invalidated = True
                        break
                    if lows[j] <= z_high and highs[j] >= z_low:
                        mitigated = True

                obs.append(
                    OrderBlockZone(
                        zone_id=f"OB_{market}_{timeframe}_SELL_{i}",
                        market=market,
                        timeframe=timeframe,
                        direction="SELL",
                        zone_low=z_low,
                        zone_high=z_high,
                        invalidation_price=inv_price,
                        created_at=times[i + 1],
                        candle_index=i,
                        candle_timestamp=times[i],
                        candle_ohlc={
                            "open": float(opens[i]),
                            "high": float(highs[i]),
                            "low": float(lows[i]),
                            "close": float(closes[i]),
                        },
                        displacement_strength=float(min(disp_ratio / (self.displacement_body_atr * 2.0), 1.0)),
                        is_mitigated=mitigated,
                        is_invalidated=invalidated,
                        metadata={"displacement_index": i + 1, "prior_low": prior_low},
                    )
                )

        return obs
