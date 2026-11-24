from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ScoreResult:
    total_score: float
    category: str  # "Excellent", "Strong", "Moderate", "Weak"
    is_signal_candidate: bool  # True if total_score >= 70.0
    breakdown: Dict[str, float] = field(default_factory=dict)
    audit_notes: List[str] = field(default_factory=list)


class ZoneScoringEngine:
    """Menghitung skor zona 0-100 secara transparan dan terukur tanpa double counting."""

    MIN_CANDIDATE_SCORE: float = 70.0

    @staticmethod
    def classify_score(score: float) -> str:
        if score >= 85.0:
            return "Excellent"
        if score >= 70.0:
            return "Strong"
        if score >= 55.0:
            return "Moderate"
        return "Weak"

    def score_zone(self, context: Dict[str, Any]) -> ScoreResult:
        breakdown: Dict[str, float] = {
            "supply_demand": 0.0,
            "order_block": 0.0,
            "liquidity": 0.0,
            "market_structure": 0.0,
            "multi_tf_alignment": 0.0,
            "freshness_and_impulse": 0.0,
        }
        notes: List[str] = []

        sd = context.get("sd_zone")
        sd_score = 0.0
        if sd is not None:
            imp_str = float(getattr(sd, "impulse_strength", sd.get("impulse_strength", 0.0) if isinstance(sd, dict) else 0.0))
            is_inv = bool(getattr(sd, "is_invalidated", sd.get("is_invalidated", False) if isinstance(sd, dict) else False))
            if not is_inv:
                sd_score = round(min(12.0 + 8.0 * max(0.0, min(imp_str, 1.0)), 20.0), 2)
                notes.append(f"S&D valid (impulse_strength={imp_str:.2f}) -> {sd_score}/20")
            else:
                notes.append("S&D invalidated -> 0/20")
        else:
            notes.append("Tidak ada bukti S&D -> 0/20")
        breakdown["supply_demand"] = sd_score

        ob = context.get("ob_zone")
        ob_score = 0.0
        if ob is not None:
            disp_str = float(
                getattr(ob, "displacement_strength", ob.get("displacement_strength", 0.0) if isinstance(ob, dict) else 0.0)
            )
            ob_inv = bool(getattr(ob, "is_invalidated", ob.get("is_invalidated", False) if isinstance(ob, dict) else False))
            if not ob_inv:
                ob_score = round(min(9.0 + 6.0 * max(0.0, min(disp_str, 1.0)), 15.0), 2)
                notes.append(f"OB tervalidasi displacement ({disp_str:.2f}) -> {ob_score}/15")
            else:
                notes.append("OB invalidated -> 0/15")
        else:
            notes.append("Tidak ada bukti OB -> 0/15")
        breakdown["order_block"] = ob_score

        if sd_score > 0 and ob_score > 0 and bool(context.get("same_event_overlap", False)):
            overlap_deduction = round(min(ob_score * 0.35, 5.0), 2)
            ob_score = round(max(0.0, ob_score - overlap_deduction), 2)
            breakdown["order_block"] = ob_score
            notes.append(f"Penyesuaian anti-double-count OB & S&D sama (-{overlap_deduction}) -> OB {ob_score}/15")

        liq = context.get("liquidity_info") or {}
        liq_score = 0.0
        if bool(liq.get("has_sweep", False)):
            liq_score += 10.0
            notes.append("Liquidity sweep teridentifikasi (+10)")
        if bool(liq.get("equal_hl", False)):
            liq_score += 5.0
            notes.append("Equal High/Low pool terdeteksi (+5)")
        if bool(liq.get("clear_target_pool", False)):
            liq_score += 5.0
            notes.append("Target likuiditas BSL/SSL jelas (+5)")
        liq_score = round(min(liq_score, 20.0), 2)
        breakdown["liquidity"] = liq_score

        ms = context.get("structure_info") or {}
        ms_score = 0.0
        if bool(ms.get("bos_aligned", False)):
            ms_score += 10.0
            notes.append("BOS searah arah setup (+10)")
        if bool(ms.get("choch_present", False)):
            ms_score += 6.0
            notes.append("CHoCH terkonfirmasi (+6)")
        if bool(ms.get("swing_sequence_valid", False)):
            ms_score += 4.0
            notes.append("Rangkaian swing HH/HL atau LH/LL valid (+4)")
        ms_score = round(min(ms_score, 20.0), 2)
        breakdown["market_structure"] = ms_score

        mtf = context.get("mtf_info") or {}
        mtf_score = 0.0
        if bool(mtf.get("h4_aligned", False)):
            mtf_score += 6.0
            notes.append("Konteks H4 selaras (+6)")
        elif str(mtf.get("alignment_type", "")).upper() == "COUNTERTREND":
            mtf_score += 2.0
            notes.append("Setup countertrend terhadap H4 (+2)")
        if bool(mtf.get("m15_validated", False)):
            mtf_score += 5.0
            notes.append("Validasi M15 terpenuhi (+5)")
        if bool(mtf.get("m5_ready", False)):
            mtf_score += 4.0
            notes.append("Kesiapan konfirmasi M5 aktif (+4)")
        mtf_score = round(min(mtf_score, 15.0), 2)
        breakdown["multi_tf_alignment"] = mtf_score

        fi = context.get("freshness_impulse_info") or {}
        fi_score = 0.0
        retests = int(fi.get("retest_count", 0))
        is_fresh = bool(fi.get("is_fresh", retests == 0))
        imp_q = float(fi.get("impulse_quality", 0.0))
        if is_fresh and retests == 0:
            fi_score += 5.0
            notes.append("Zona fresh tanpa retest (+5)")
        elif retests == 1:
            fi_score += 2.5
            notes.append("Zona retest ke-1 (+2.5)")
        else:
            notes.append(f"Retest={retests} -> poin freshness minimal")
        fi_score += 5.0 * max(0.0, min(imp_q, 1.0))
        fi_score = round(min(fi_score, 10.0), 2)
        breakdown["freshness_and_impulse"] = fi_score

        total = round(sum(breakdown.values()), 2)
        total = max(0.0, min(total, 100.0))
        category = self.classify_score(total)
        is_candidate = total >= self.MIN_CANDIDATE_SCORE

        return ScoreResult(
            total_score=total,
            category=category,
            is_signal_candidate=is_candidate,
            breakdown=breakdown,
            audit_notes=notes,
        )
