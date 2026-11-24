from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    tick_size: float
    price_decimals: int
    max_spread: float
    sl_atr_mult: float
    retracement_atr_mult: float
    min_rr: float = 2.0


DEFAULT_INSTRUMENT_SPECS: Dict[str, InstrumentSpec] = {
    "XAUUSD": InstrumentSpec(
        symbol="XAUUSD",
        tick_size=0.01,
        price_decimals=2,
        max_spread=0.80,
        sl_atr_mult=0.50,
        retracement_atr_mult=0.25,
        min_rr=2.0,
    ),
    "BTCUSD": InstrumentSpec(
        symbol="BTCUSD",
        tick_size=0.10,
        price_decimals=2,
        max_spread=50.0,
        sl_atr_mult=0.50,
        retracement_atr_mult=0.25,
        min_rr=2.0,
    ),
}


class RiskManager:
    """Mengelola spesifikasi instrumen terpisah (XAUUSD vs BTCUSD), presisi harga, spread, dan batas R:R."""

    def __init__(self, specs: Dict[str, InstrumentSpec] | None = None) -> None:
        self.specs: Dict[str, InstrumentSpec] = dict(specs or DEFAULT_INSTRUMENT_SPECS)

    def get_spec(self, market: str) -> InstrumentSpec:
        key = market.replace("/", "").upper()
        if key in self.specs:
            return self.specs[key]
        return InstrumentSpec(
            symbol=key,
            tick_size=0.01,
            price_decimals=2,
            max_spread=1.0,
            sl_atr_mult=0.5,
            retracement_atr_mult=0.25,
            min_rr=2.0,
        )

    def round_price(self, market: str, price: float) -> float:
        spec = self.get_spec(market)
        if spec.tick_size > 0:
            snapped = round(price / spec.tick_size) * spec.tick_size
        else:
            snapped = price
        return round(float(snapped), spec.price_decimals)

    def is_spread_acceptable(self, market: str, spread: float | None) -> bool:
        if spread is None or spread < 0:
            return False
        spec = self.get_spec(market)
        return float(spread) <= spec.max_spread

    @staticmethod
    def calculate_rr(direction: str, entry: float, stop_loss: float, take_profit: float) -> float:
        risk = abs(entry - stop_loss)
        if risk <= 1e-12:
            return 0.0
        if direction == "BUY":
            reward = take_profit - entry
        else:
            reward = entry - take_profit
        if reward <= 0.0:
            return 0.0
        return round(reward / risk, 4)

    def meets_min_rr(self, market: str, rr: float) -> bool:
        spec = self.get_spec(market)
        return rr >= spec.min_rr
