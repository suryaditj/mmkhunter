from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from zone_hunter.data.candle_manager import TIMEFRAME_SECONDS


@dataclass
class ValidationReport:
    is_valid: bool
    is_stale: bool
    spread_ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DataValidator:
    """Validasi kelengkapan OHLC, kesegaran data (anti-stale), dan batas spread."""

    def validate_ohlcv(
        self,
        df: pd.DataFrame,
        timeframe: str,
        reference_now: Optional[datetime] = None,
        max_stale_multiplier: float = 2.5,
        min_candles: int = 30,
    ) -> ValidationReport:
        errors: List[str] = []
        warnings: List[str] = []
        required_cols = {"timestamp", "open", "high", "low", "close"}

        if df is None or df.empty:
            return ValidationReport(
                is_valid=False,
                is_stale=True,
                spread_ok=False,
                errors=["Data OHLCV kosong."],
            )

        if not required_cols.issubset(df.columns):
            missing = sorted(required_cols - set(df.columns))
            return ValidationReport(
                is_valid=False,
                is_stale=True,
                spread_ok=False,
                errors=[f"Kolom wajib hilang: {missing}"],
            )

        if len(df) < min_candles:
            errors.append(f"Jumlah candle ({len(df)}) kurang dari minimum ({min_candles}).")

        if df[["open", "high", "low", "close"]].isna().any().any():
            errors.append("Terdapat nilai NaN pada OHLC.")

        if (df[["open", "high", "low", "close"]] <= 0).any().any():
            errors.append("Terdapat harga <= 0 pada OHLC.")

        max_oc = df[["open", "close"]].max(axis=1)
        min_oc = df[["open", "close"]].min(axis=1)
        if (df["high"] < max_oc).any():
            errors.append("Ditemukan candle dengan high < max(open, close).")
        if (df["low"] > min_oc).any():
            errors.append("Ditemukan candle dengan low > min(open, close).")

        is_stale = False
        tf_key = timeframe.upper()
        tf_sec = TIMEFRAME_SECONDS.get(tf_key)
        now_utc = (reference_now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        latest_ts = pd.to_datetime(df["timestamp"].iloc[-1], utc=True)

        if pd.isna(latest_ts):
            errors.append("Timestamp candle terakhir tidak valid.")
            is_stale = True
        elif tf_sec is not None:
            age_sec = (now_utc - latest_ts.to_pydatetime()).total_seconds()
            max_age = tf_sec * max_stale_multiplier
            if age_sec > max_age:
                is_stale = True
                errors.append(
                    f"Data {tf_key} stale: umur candle terakhir {age_sec:.0f}s melebihi batas {max_age:.0f}s."
                )

        is_valid = (len(errors) == 0) and (not is_stale)
        return ValidationReport(
            is_valid=is_valid,
            is_stale=is_stale,
            spread_ok=True,
            errors=errors,
            warnings=warnings,
            metadata={"latest_timestamp": latest_ts.isoformat() if not pd.isna(latest_ts) else None},
        )
