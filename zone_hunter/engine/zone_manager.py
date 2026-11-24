from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


VALID_STATUSES = {
    "DETECTED",
    "ACTIVE",
    "APPROACHING",
    "TOUCHED",
    "MITIGATED",
    "INVALIDATED",
}

TERMINAL_STATUSES = {"INVALIDATED"}


@dataclass
class ManagedZone:
    zone_id: str
    market: str
    direction: str  # "BUY" or "SELL"
    timeframe: str
    zone_low: float
    zone_high: float
    zone_score: float
    score_breakdown: Dict[str, float]
    invalidation_price: float
    detection_time: Any
    freshness: str  # "FRESH" or "RETESTED"
    zone_status: str = "DETECTED"
    status_history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def transition_to(self, new_status: str, timestamp: Any, reason: str) -> None:
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Status zona tidak valid: {new_status}")
        if self.zone_status == "INVALIDATED" and new_status != "INVALIDATED":
            return
        if self.zone_status != new_status:
            self.zone_status = new_status
            self.status_history.append(
                {
                    "status": new_status,
                    "timestamp": timestamp,
                    "reason": reason,
                }
            )


class ZoneManager:
    """Mengelola siklus zona dengan batas maksimal 3 BUY dan 3 SELL aktif."""

    MAX_ACTIVE_PER_DIRECTION: int = 3

    def __init__(self, approach_distance: float = 0.0) -> None:
        self.approach_distance = approach_distance
        self.zones: Dict[str, ManagedZone] = {}

    def register_or_update(self, zone: ManagedZone, timestamp: Any) -> ManagedZone:
        existing = self.zones.get(zone.zone_id)
        if existing is None:
            if not zone.status_history:
                zone.status_history.append(
                    {
                        "status": zone.zone_status,
                        "timestamp": timestamp,
                        "reason": "Registered",
                    }
                )
            self.zones[zone.zone_id] = zone
            return zone

        if existing.zone_status == "INVALIDATED":
            return existing

        existing.zone_score = zone.zone_score
        existing.score_breakdown = zone.score_breakdown
        existing.freshness = zone.freshness
        existing.metadata.update(zone.metadata)
        return existing

    @staticmethod
    def _overlaps(a: ManagedZone, b: ManagedZone) -> bool:
        return (
            a.market == b.market
            and a.direction == b.direction
            and a.zone_id != b.zone_id
            and a.zone_low <= b.zone_high
            and a.zone_high >= b.zone_low
        )

    def evaluate_market(
        self,
        market: str,
        current_price: float,
        current_close: float,
        timestamp: Any,
        approach_buffer: Optional[float] = None,
    ) -> Dict[str, List[ManagedZone]]:
        buf = self.approach_distance if approach_buffer is None else approach_buffer
        market_zones = [z for z in self.zones.values() if z.market == market]

        for z in market_zones:
            if z.zone_status == "INVALIDATED":
                continue

            if z.direction == "BUY":
                if current_close < z.invalidation_price:
                    z.transition_to("INVALIDATED", timestamp, "Close menembus invalidation_price BUY")
                    continue
                if current_price <= z.zone_high and current_price >= z.zone_low:
                    z.freshness = "RETESTED"
                    z.transition_to("TOUCHED", timestamp, "Harga menyentuh zona BUY")
                elif current_price > z.zone_high and (current_price - z.zone_high) <= buf:
                    if z.zone_status in ("DETECTED", "ACTIVE"):
                        z.transition_to("APPROACHING", timestamp, "Harga mendekati zona BUY")
            else:
                if current_close > z.invalidation_price:
                    z.transition_to("INVALIDATED", timestamp, "Close menembus invalidation_price SELL")
                    continue
                if current_price >= z.zone_low and current_price <= z.zone_high:
                    z.freshness = "RETESTED"
                    z.transition_to("TOUCHED", timestamp, "Harga menyentuh zona SELL")
                elif current_price < z.zone_low and (z.zone_low - current_price) <= buf:
                    if z.zone_status in ("DETECTED", "ACTIVE"):
                        z.transition_to("APPROACHING", timestamp, "Harga mendekati zona SELL")

        active_states = {"ACTIVE", "APPROACHING", "TOUCHED"}
        selected_by_dir: Dict[str, List[ManagedZone]] = {"BUY": [], "SELL": []}

        for direction in ("BUY", "SELL"):
            pool = [
                z
                for z in market_zones
                if z.direction == direction and z.zone_status not in ("INVALIDATED", "MITIGATED")
            ]
            pool.sort(key=lambda x: (x.zone_score, str(x.detection_time)), reverse=True)

            chosen: List[ManagedZone] = []
            for cand in pool:
                if len(chosen) >= self.MAX_ACTIVE_PER_DIRECTION:
                    break
                if any(self._overlaps(cand, kept) for kept in chosen):
                    continue
                if cand.zone_status == "DETECTED":
                    cand.transition_to("ACTIVE", timestamp, f"Terpilih masuk top-{self.MAX_ACTIVE_PER_DIRECTION} {direction}")
                elif cand.zone_status not in active_states:
                    cand.transition_to("ACTIVE", timestamp, f"Diaktifkan kembali ke top-{self.MAX_ACTIVE_PER_DIRECTION} {direction}")
                chosen.append(cand)

            selected_by_dir[direction] = chosen

        return selected_by_dir

    def mark_mitigated(self, zone_id: str, timestamp: Any, reason: str = "Zona termitigasi") -> None:
        zone = self.zones.get(zone_id)
        if zone and zone.zone_status != "INVALIDATED":
            zone.freshness = "RETESTED"
            zone.transition_to("MITIGATED", timestamp, reason)
