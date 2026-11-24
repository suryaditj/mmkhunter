from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd


@dataclass
class SupplyDemandZone:
    zone_id: str
    market: str
    timeframe: str
    direction: str  # "BUY" (Demand) or "SELL" (Supply)
    zone_low: float
    zone_high: float
    invalidation_price: float
    created_at: Any
    impulse_strength: float  # 0.0 - 1.0
    impulse_move: float
    base_range: float
    retest_count: int = 0
    is_fresh: bool = True
    is_mitigated: bool = False
    is_invalidated: bool = False
    last_updated_at: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SupplyDemandDetector:
    """
    Detektor zona SNR / SND berbasis pola urutan:
    - RBD: Rally - Base - Drop (Supply / SELL)
    - DBD: Drop - Base - Drop (Supply / SELL)
    - DBR: Drop - Base - Rally (Demand / BUY)
    - RBR: Rally - Base - Rally (Demand / BUY)
    Dilengkapi validasi SNR (Support/Resistance & SNR Flip) untuk memperkuat kevalidan sebelum entry.
    """

    PATTERN_TO_DIRECTION: Dict[str, str] = {
        "RBD": "SELL",
        "DBD": "SELL",
        "DBR": "BUY",
        "RBR": "BUY",
    }

    def __init__(
        self,
        atr_period: int = 14,
        max_base_candles: int = 4,
        max_base_body_ratio: float = 0.45,
        base_body_mult: float = 0.75,
        min_impulse_atr: float = 1.8,
        min_impulse_to_base: float = 2.0,
        mitigation_penetration: float = 0.5,
        invalidation_atr_buffer: float = 0.0,
    ) -> None:
        self.atr_period = atr_period
        self.max_base_candles = max_base_candles
        self.max_base_body_ratio = max_base_body_ratio
        self.base_body_mult = base_body_mult
        self.min_impulse_atr = min_impulse_atr
        self.min_impulse_to_base = min_impulse_to_base
        self.mitigation_penetration = mitigation_penetration
        self.invalidation_atr_buffer = invalidation_atr_buffer

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

    @staticmethod
    def _evaluate_snr_context(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        start_base: int,
        end_base: int,
        z_low: float,
        z_high: float,
        direction: str,
        tol: float,
    ) -> Dict[str, Any]:
        """Mengecek apakah area zona selaras dengan level SNR historis / SNR flip."""
        snr_touches = 0
        snr_flip = False

        lookback_start = max(0, start_base - 20)
        for k in range(lookback_start, start_base):
            in_band = (lows[k] <= z_high + tol) and (highs[k] >= z_low - tol)
            if in_band:
                snr_touches += 1
                if direction == "BUY" and closes[k] < z_low:
                    snr_flip = True
                elif direction == "SELL" and closes[k] > z_high:
                    snr_flip = True

        for j in range(end_base + 1, len(closes)):
            if direction == "BUY" and closes[j] > z_high:
                snr_flip = True
            elif direction == "SELL" and closes[j] < z_low:
                snr_flip = True

        if snr_flip:
            snr_role = "SNR_FLIP"
        elif direction == "BUY":
            snr_role = "SUPPORT"
        else:
            snr_role = "RESISTANCE"

        snr_valid = (snr_touches > 0) or snr_flip
        return {
            "snr_valid": snr_valid,
            "snr_role": snr_role,
            "snr_touches": snr_touches,
            "snr_flip": snr_flip,
        }

    def detect(
        self,
        df: pd.DataFrame,
        market: str,
        timeframe: str,
    ) -> List[SupplyDemandZone]:
        required_cols = {"open", "high", "low", "close"}
        if df is None or df.empty or not required_cols.issubset(df.columns):
            return []

        data = df.reset_index(drop=True).copy()
        if len(data) < self.atr_period + 5:
            return []

        opens = data["open"].astype(float).to_numpy()
        highs = data["high"].astype(float).to_numpy()
        lows = data["low"].astype(float).to_numpy()
        closes = data["close"].astype(float).to_numpy()
        times = data["timestamp"].tolist() if "timestamp" in data.columns else list(range(len(data)))
        atr = self._compute_atr(data, self.atr_period).to_numpy()

        bodies = np.abs(closes - opens)
        ranges = np.maximum(highs - lows, 1e-12)
        avg_body = pd.Series(bodies).rolling(window=self.atr_period, min_periods=1).mean().to_numpy()

        def is_base_candle(idx: int) -> bool:
            body_ratio = bodies[idx] / ranges[idx]
            return (body_ratio <= self.max_base_body_ratio) and (
                bodies[idx] <= avg_body[idx] * self.base_body_mult
            )

        zones: List[SupplyDemandZone] = []
        n = len(data)

        for end_base in range(2, n - 2):
            current_atr = max(float(atr[end_base]), 1e-12)

            start_base = end_base
            steps = 1
            while start_base > 1 and steps < self.max_base_candles and is_base_candle(start_base - 1):
                start_base -= 1
                steps += 1

            if not is_base_candle(end_base):
                continue

            base_low = float(np.min(lows[start_base : end_base + 1]))
            base_high = float(np.max(highs[start_base : end_base + 1]))
            base_range = max(base_high - base_low, current_atr * 0.1)

            # Deteksi leg sebelum base (Rally vs Drop) pada 1-3 candle sebelum start_base
            leg_in_start = max(0, start_base - 3)
            leg_in_high = float(np.max(highs[leg_in_start:start_base]))
            leg_in_low = float(np.min(lows[leg_in_start:start_base]))
            rally_in_move = leg_in_high - leg_in_low
            drop_in_move = leg_in_high - leg_in_low

            rally_in = (
                (closes[start_base - 1] > closes[leg_in_start])
                and (rally_in_move >= current_atr * 0.8)
            )
            drop_in = (
                (closes[start_base - 1] < closes[leg_in_start])
                and (drop_in_move >= current_atr * 0.8)
            )

            # Deteksi leg keluar / impuls setelah base (Rally vs Drop)
            impulse_end_idx = min(end_base + 3, n - 1)
            bull_peak = float(np.max(highs[end_base + 1 : impulse_end_idx + 1]))
            bear_trough = float(np.min(lows[end_base + 1 : impulse_end_idx + 1]))

            bull_move = bull_peak - base_high
            bear_move = base_low - bear_trough

            candidates = []

            # Demand patterns (BUY): DBR (Drop-Base-Rally) & RBR (Rally-Base-Rally)
            if (
                bull_move >= self.min_impulse_atr * current_atr
                and bull_move / base_range >= self.min_impulse_to_base
            ):
                pattern = "DBR" if drop_in else ("RBR" if rally_in else "DBR")
                pattern_desc = "Drop - Base - Rally" if pattern == "DBR" else "Rally - Base - Rally"
                snr_info = self._evaluate_snr_context(
                    highs, lows, closes, start_base, end_base, base_low, base_high, "BUY", current_atr * 0.25
                )
                base_strength = float(
                    np.clip(
                        0.5 * min(bull_move / (self.min_impulse_atr * current_atr * 1.5), 1.0)
                        + 0.5 * min((bull_move / base_range) / (self.min_impulse_to_base * 1.5), 1.0),
                        0.0,
                        1.0,
                    )
                )
                strength = float(np.clip(base_strength + (0.12 if snr_info["snr_valid"] else 0.0), 0.0, 1.0))
                invalidation = base_low - self.invalidation_atr_buffer * current_atr
                candidates.append(
                    ("BUY", pattern, pattern_desc, "DEMAND", base_low, base_high, invalidation, bull_move, strength, snr_info)
                )

            # Supply patterns (SELL): RBD (Rally-Base-Drop) & DBD (Drop-Base-Drop)
            if (
                bear_move >= self.min_impulse_atr * current_atr
                and bear_move / base_range >= self.min_impulse_to_base
            ):
                pattern = "RBD" if rally_in else ("DBD" if drop_in else "RBD")
                pattern_desc = "Rally - Base - Drop" if pattern == "RBD" else "Drop - Base - Drop"
                snr_info = self._evaluate_snr_context(
                    highs, lows, closes, start_base, end_base, base_low, base_high, "SELL", current_atr * 0.25
                )
                base_strength = float(
                    np.clip(
                        0.5 * min(bear_move / (self.min_impulse_atr * current_atr * 1.5), 1.0)
                        + 0.5 * min((bear_move / base_range) / (self.min_impulse_to_base * 1.5), 1.0),
                        0.0,
                        1.0,
                    )
                )
                strength = float(np.clip(base_strength + (0.12 if snr_info["snr_valid"] else 0.0), 0.0, 1.0))
                invalidation = base_high + self.invalidation_atr_buffer * current_atr
                candidates.append(
                    ("SELL", pattern, pattern_desc, "SUPPLY", base_low, base_high, invalidation, bear_move, strength, snr_info)
                )

            for direction, pattern, pattern_desc, zone_kind, z_low, z_high, inv_price, imp_move, strength, snr_info in candidates:
                retest_count = 0
                is_mitigated = False
                is_invalidated = False
                last_time = times[end_base]
                zone_height = max(z_high - z_low, 1e-12)

                for j in range(end_base + 1, n):
                    c_high = float(highs[j])
                    c_low = float(lows[j])
                    c_close = float(closes[j])
                    last_time = times[j]

                    if direction == "BUY" and c_close < inv_price:
                        is_invalidated = True
                        break
                    if direction == "SELL" and c_close > inv_price:
                        is_invalidated = True
                        break

                    touched = (c_low <= z_high) and (c_high >= z_low)
                    if touched:
                        retest_count += 1
                        if direction == "BUY":
                            penetration = (z_high - min(c_low, z_high)) / zone_height
                        else:
                            penetration = (max(c_low, z_low) - z_low) / zone_height
                        if penetration >= self.mitigation_penetration:
                            is_mitigated = True

                zone_id = f"{pattern}_{market}_{timeframe}_{start_base}_{end_base}"
                zones.append(
                    SupplyDemandZone(
                        zone_id=zone_id,
                        market=market,
                        timeframe=timeframe,
                        direction=direction,
                        zone_low=z_low,
                        zone_high=z_high,
                        invalidation_price=inv_price,
                        created_at=times[end_base],
                        impulse_strength=strength,
                        impulse_move=imp_move,
                        base_range=base_range,
                        retest_count=retest_count,
                        is_fresh=(retest_count == 0),
                        is_mitigated=is_mitigated,
                        is_invalidated=is_invalidated,
                        last_updated_at=last_time,
                        metadata={
                            "pattern": pattern,
                            "pattern_desc": pattern_desc,
                            "zone_kind": zone_kind,
                            "snr_valid": snr_info["snr_valid"],
                            "snr_role": snr_info["snr_role"],
                            "snr_touches": snr_info["snr_touches"],
                            "snr_flip": snr_info["snr_flip"],
                            "base_start_idx": start_base,
                            "base_end_idx": end_base,
                            "base_candle_count": end_base - start_base + 1,
                        },
                    )
                )

        return zones
