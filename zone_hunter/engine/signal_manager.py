from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TradingSignal:
    signal_id: str
    market: str
    direction: str  # "BUY" or "SELL"
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    zone_score: float
    confirmation_reasons: List[str]
    signal_time: Any
    signal_status: str = "CONFIRMED"
    zone_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SignalManager:
    """Mencegah sinyal duplikat dan menjaga riwayat sinyal tetap immutable setelah diterbitkan."""

    def __init__(self) -> None:
        self._signals: Dict[str, TradingSignal] = {}
        self._dedup_keys: set[tuple[str, str, str, str]] = set()
        self.cancelled_count: int = 0

    @staticmethod
    def _make_dedup_key(market: str, direction: str, zone_id: Optional[str], signal_time: Any) -> tuple[str, str, str, str]:
        return (
            market.upper(),
            direction.upper(),
            str(zone_id or ""),
            str(signal_time),
        )

    def publish_if_unique(self, signal: TradingSignal) -> Optional[TradingSignal]:
        if signal.signal_status != "CONFIRMED":
            return None
        key = self._make_dedup_key(signal.market, signal.direction, signal.zone_id, signal.signal_time)
        if key in self._dedup_keys or signal.signal_id in self._signals:
            return None

        self._dedup_keys.add(key)
        self._signals[signal.signal_id] = signal
        return signal

    def record_cancelled(self) -> None:
        self.cancelled_count += 1

    def get_all_signals(self) -> List[TradingSignal]:
        return list(self._signals.values())
