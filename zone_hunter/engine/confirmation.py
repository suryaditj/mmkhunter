from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ConfirmationResult:
    status: str  # "CONFIRMED" or "WAIT"
    direction: str  # "BUY" or "SELL"
    checks: Dict[str, bool] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    missing_reasons: List[str] = field(default_factory=list)

    @property
    def is_confirmed(self) -> bool:
        return self.status == "CONFIRMED"


class ConfirmationEngine:
    """Mengevaluasi 7 syarat wajib untuk CONFIRMED BUY / SELL; selain itu tetap WAIT."""

    MIN_SCORE: float = 70.0

    def evaluate(
        self,
        direction: str,
        zone_score: float,
        price_in_zone: bool,
        has_liquidity_sweep: bool,
        m5_choch_confirmed: bool,
        has_displacement: bool,
        has_clear_structure_and_invalidation: bool,
        spread_and_data_valid: bool,
        extra_context: Dict[str, Any] | None = None,
    ) -> ConfirmationResult:
        dir_upper = direction.upper()
        if dir_upper not in ("BUY", "SELL"):
            return ConfirmationResult(
                status="WAIT",
                direction=dir_upper,
                checks={},
                missing_reasons=["Arah tidak valid"],
            )

        checks: Dict[str, bool] = {
            "price_in_zone": bool(price_in_zone),
            "liquidity_sweep": bool(has_liquidity_sweep),
            "m5_choch_confirmed": bool(m5_choch_confirmed),
            "displacement": bool(has_displacement),
            "clear_entry_and_invalidation": bool(has_clear_structure_and_invalidation),
            "min_zone_score_70": float(zone_score) >= self.MIN_SCORE,
            "spread_and_data_quality": bool(spread_and_data_valid),
        }

        label_map = {
            "price_in_zone": f"Harga memasuki zona {dir_upper} valid",
            "liquidity_sweep": f"Liquidity sweep {dir_upper} teridentifikasi",
            "m5_choch_confirmed": f"M5 {dir_upper} CHoCH terkonfirmasi",
            "displacement": f"Displacement {dir_upper} valid",
            "clear_entry_and_invalidation": "Struktur entry & invalidasi jelas",
            "min_zone_score_70": f"Zone score >= {self.MIN_SCORE:.0f} (aktual: {zone_score:.2f})",
            "spread_and_data_quality": "Spread & kualitas data memenuhi syarat",
        }

        reasons: List[str] = [label_map[k] for k, ok in checks.items() if ok]
        missing: List[str] = [label_map[k] for k, ok in checks.items() if not ok]

        if all(checks.values()):
            return ConfirmationResult(
                status="CONFIRMED",
                direction=dir_upper,
                checks=checks,
                reasons=reasons,
                missing_reasons=[],
            )

        return ConfirmationResult(
            status="WAIT",
            direction=dir_upper,
            checks=checks,
            reasons=reasons,
            missing_reasons=missing,
        )
