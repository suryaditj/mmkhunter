from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Tuple

import pandas as pd

TIMEFRAME_SECONDS: Dict[str, int] = {
    "M5": 300,
    "M15": 900,
    "H1": 3600,
    "H4": 14400,
}


class CandleManager:
    """Mengelola cache OHLCV, closed-bar filtering, dan sinkronisasi timestamp antar TF."""

    def __init__(self) -> None:
        self._cache: Dict[Tuple[str, str], pd.DataFrame] = {}

    @staticmethod
    def _ensure_utc_df(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        out = df.copy()
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        out = out.dropna(subset=["timestamp", "open", "high", "low", "close"])
        return out.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)

    def update_cache(self, market: str, timeframe: str, df: pd.DataFrame) -> pd.DataFrame:
        key = (market.upper(), timeframe.upper())
        clean_new = self._ensure_utc_df(df)
        prev = self._cache.get(key)
        if prev is not None and not prev.empty:
            merged = pd.concat([prev, clean_new], ignore_index=True)
            merged = merged.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        else:
            merged = clean_new
        self._cache[key] = merged
        return merged.copy()

    def get_cached(self, market: str, timeframe: str) -> pd.DataFrame:
        key = (market.upper(), timeframe.upper())
        cached = self._cache.get(key)
        return cached.copy() if cached is not None else pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    def get_closed_candles(
        self,
        market: str,
        timeframe: str,
        reference_now: datetime | None = None,
    ) -> pd.DataFrame:
        tf_key = timeframe.upper()
        duration_sec = TIMEFRAME_SECONDS.get(tf_key)
        df = self.get_cached(market, tf_key)
        if df.empty or duration_sec is None:
            return df

        now_utc = (reference_now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        closed_mask = df["timestamp"].apply(
            lambda ts: (ts.to_pydatetime() + pd.Timedelta(seconds=duration_sec).to_pytimedelta()) <= now_utc
        )
        return df.loc[closed_mask].reset_index(drop=True)

    @staticmethod
    def align_to_anchor(df: pd.DataFrame, anchor_ts: datetime | pd.Timestamp | None) -> pd.DataFrame:
        if df is None or df.empty or anchor_ts is None:
            return df if df is not None else pd.DataFrame()
        anchor_utc = pd.to_datetime(anchor_ts, utc=True)
        out = df.copy()
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
        return out[out["timestamp"] <= anchor_utc].reset_index(drop=True)
