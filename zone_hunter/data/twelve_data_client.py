from __future__ import annotations

import logging
import os
import time
from collections import deque
from typing import Any, Dict, Optional

import pandas as pd
import requests

logger = logging.getLogger("zone_hunter.twelve_data")

TIMEFRAME_TO_TD_INTERVAL: Dict[str, str] = {
    "M5": "5min",
    "M15": "15min",
    "H1": "1h",
    "H4": "4h",
}

SYMBOL_TO_TD_PAIR: Dict[str, str] = {
    "XAUUSD": "XAU/USD",
    "XAU/USD": "XAU/USD",
    "BTCUSD": "BTC/USD",
    "BTC/USD": "BTC/USD",
}


def sanitize_log_text(text: str, api_key: Optional[str]) -> str:
    if not text or not api_key:
        return text
    return text.replace(api_key, "***REDACTED***")


class TwelveDataClient:
    """Klien READ-ONLY Twelve Data API untuk mengambil data OHLCV multi-timeframe."""

    BASE_URL = "https://api.twelvedata.com"

    def __init__(
        self,
        api_key: Optional[str] = None,
        rate_limit_per_min: Optional[int] = None,
        timezone: str = "UTC",
        timeout: int = 15,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("TWELVE_DATA_API_KEY", "").strip()
        env_limit = os.getenv("TWELVE_DATA_RATE_LIMIT_PER_MIN", "8").strip()
        parsed_limit = int(env_limit) if env_limit.isdigit() and int(env_limit) > 0 else 8
        self.rate_limit_per_min = rate_limit_per_min if rate_limit_per_min is not None else parsed_limit
        self.timezone = timezone
        self.timeout = timeout
        self.session = session or requests.Session()
        self._request_timestamps: deque[float] = deque()

    @staticmethod
    def normalize_symbol(market: str) -> str:
        clean = market.strip().upper()
        return SYMBOL_TO_TD_PAIR.get(clean, clean)

    @staticmethod
    def map_interval(timeframe: str) -> str:
        tf_upper = timeframe.strip().upper()
        if tf_upper not in TIMEFRAME_TO_TD_INTERVAL:
            raise ValueError(f"Timeframe tidak didukung Twelve Data mapping: {timeframe}")
        return TIMEFRAME_TO_TD_INTERVAL[tf_upper]

    def _respect_rate_limit(self) -> None:
        now = time.monotonic()
        window_sec = 60.0
        while self._request_timestamps and (now - self._request_timestamps[0]) >= window_sec:
            self._request_timestamps.popleft()

        if len(self._request_timestamps) >= self.rate_limit_per_min:
            sleep_for = window_sec - (now - self._request_timestamps[0]) + 0.05
            if sleep_for > 0:
                logger.info("Rate limit %s req/min tercapai, jeda %.2fs", self.rate_limit_per_min, sleep_for)
                time.sleep(sleep_for)
                now = time.monotonic()
                while self._request_timestamps and (now - self._request_timestamps[0]) >= window_sec:
                    self._request_timestamps.popleft()

        self._request_timestamps.append(now)

    def fetch_ohlcv(
        self,
        market: str,
        timeframe: str,
        outputsize: int = 200,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        if not self.api_key:
            raise RuntimeError("TWELVE_DATA_API_KEY belum diatur di environment variable.")

        symbol = self.normalize_symbol(market)
        interval = self.map_interval(timeframe)

        params: Dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": int(outputsize),
            "timezone": self.timezone,
            "apikey": self.api_key,
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        self._respect_rate_limit()

        try:
            resp = self.session.get(f"{self.BASE_URL}/time_series", params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            safe_msg = sanitize_log_text(str(exc), self.api_key)
            logger.error("Gagal mengambil data Twelve Data (%s %s): %s", symbol, interval, safe_msg)
            raise RuntimeError(f"Error koneksi Twelve Data: {safe_msg}") from exc

        if not isinstance(payload, dict) or payload.get("status") == "error":
            err_msg = sanitize_log_text(str(payload.get("message", payload) if isinstance(payload, dict) else payload), self.api_key)
            raise RuntimeError(f"Twelve Data API error untuk {symbol} {interval}: {err_msg}")

        values = payload.get("values")
        if not values or not isinstance(values, list):
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(values)
        df = df.rename(columns={"datetime": "timestamp"})

        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
        else:
            df["volume"] = 0.0

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp", "open", "high", "low", "close"])
        df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last").reset_index(drop=True)
        return df[["timestamp", "open", "high", "low", "close", "volume"]]
