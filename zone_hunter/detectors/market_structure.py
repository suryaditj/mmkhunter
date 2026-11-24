from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


@dataclass
class SwingPoint:
    point_type: str  # "HH", "HL", "LH", "LL", "SH", "SL"
    price: float
    candle_index: int
    timestamp: Any


@dataclass
class StructureEvent:
    event_type: str  # "BOS" or "CHoCH"
    direction: str  # "BULLISH" or "BEARISH"
    broken_level: float
    close_price: float
    candle_index: int
    timestamp: Any
    previous_trend: str
    new_trend: str
    metadata: Dict[str, Any] = field(default_factory=dict)


class MarketStructureDetector:
    """Detektor struktur pasar: HH, HL, LH, LL, BOS, dan CHoCH berbasis candle close."""

    def __init__(self, left_bars: int = 3, right_bars: int = 3) -> None:
        self.left_bars = left_bars
        self.right_bars = right_bars

    def detect(
        self,
        df: pd.DataFrame,
        market: str,
        timeframe: str,
    ) -> Dict[str, Any]:
        required_cols = {"high", "low", "close"}
        if df is None or df.empty or not required_cols.issubset(df.columns):
            return {
                "trend": "RANGE",
                "swing_points": [],
                "events": [],
                "last_swing_high": None,
                "last_swing_low": None,
            }

        data = df.reset_index(drop=True).copy()
        n = len(data)
        if n < self.left_bars + self.right_bars + 1:
            return {
                "trend": "RANGE",
                "swing_points": [],
                "events": [],
                "last_swing_high": None,
                "last_swing_low": None,
            }

        highs = data["high"].astype(float).to_numpy()
        lows = data["low"].astype(float).to_numpy()
        closes = data["close"].astype(float).to_numpy()
        times = data["timestamp"].tolist() if "timestamp" in data.columns else list(range(n))

        raw_pivots: List[tuple[int, str, float]] = []
        for i in range(self.left_bars, n - self.right_bars):
            win_h = highs[i - self.left_bars : i + self.right_bars + 1]
            win_l = lows[i - self.left_bars : i + self.right_bars + 1]
            is_sh = highs[i] == np.max(win_h) and np.sum(win_h == highs[i]) == 1
            is_sl = lows[i] == np.min(win_l) and np.sum(win_l == lows[i]) == 1
            if is_sh:
                raw_pivots.append((i, "SH", float(highs[i])))
            if is_sl:
                raw_pivots.append((i, "SL", float(lows[i])))

        raw_pivots.sort(key=lambda x: x[0])

        swing_points: List[SwingPoint] = []
        last_sh: Optional[float] = None
        last_sl: Optional[float] = None

        for idx, kind, price in raw_pivots:
            if kind == "SH":
                if last_sh is None:
                    label = "SH"
                elif price > last_sh:
                    label = "HH"
                else:
                    label = "LH"
                last_sh = price
                swing_points.append(SwingPoint(label, price, idx, times[idx]))
            else:
                if last_sl is None:
                    label = "SL"
                elif price > last_sl:
                    label = "HL"
                else:
                    label = "LL"
                last_sl = price
                swing_points.append(SwingPoint(label, price, idx, times[idx]))

        events: List[StructureEvent] = []
        trend = "RANGE"
        active_high: Optional[float] = None
        active_low: Optional[float] = None

        pivot_ptr = 0
        for c_idx in range(n):
            while pivot_ptr < len(swing_points) and swing_points[pivot_ptr].candle_index < c_idx:
                sp = swing_points[pivot_ptr]
                if sp.point_type in ("SH", "HH", "LH"):
                    active_high = sp.price
                elif sp.point_type in ("SL", "HL", "LL"):
                    active_low = sp.price
                pivot_ptr += 1

            c_close = float(closes[c_idx])

            if active_high is not None and c_close > active_high:
                if trend == "BEARISH":
                    ev_type = "CHoCH"
                    new_trend = "BULLISH"
                else:
                    ev_type = "BOS"
                    new_trend = "BULLISH"
                events.append(
                    StructureEvent(
                        event_type=ev_type,
                        direction="BULLISH",
                        broken_level=active_high,
                        close_price=c_close,
                        candle_index=c_idx,
                        timestamp=times[c_idx],
                        previous_trend=trend,
                        new_trend=new_trend,
                        metadata={"market": market, "timeframe": timeframe},
                    )
                )
                trend = new_trend
                active_high = None

            elif active_low is not None and c_close < active_low:
                if trend == "BULLISH":
                    ev_type = "CHoCH"
                    new_trend = "BEARISH"
                else:
                    ev_type = "BOS"
                    new_trend = "BEARISH"
                events.append(
                    StructureEvent(
                        event_type=ev_type,
                        direction="BEARISH",
                        broken_level=active_low,
                        close_price=c_close,
                        candle_index=c_idx,
                        timestamp=times[c_idx],
                        previous_trend=trend,
                        new_trend=new_trend,
                        metadata={"market": market, "timeframe": timeframe},
                    )
                )
                trend = new_trend
                active_low = None

        return {
            "trend": trend,
            "swing_points": swing_points,
            "events": events,
            "last_swing_high": last_sh,
            "last_swing_low": last_sl,
        }
