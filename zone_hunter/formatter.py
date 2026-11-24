from __future__ import annotations

from typing import Any, Dict, List


def format_zone_payload(zone_obj: Any) -> Dict[str, Any]:
    meta = getattr(zone_obj, "metadata", {}) or {}
    return {
        "zone_id": zone_obj.zone_id,
        "market": zone_obj.market,
        "direction": zone_obj.direction,
        "timeframe": zone_obj.timeframe,
        "pattern": meta.get("pattern", "SND"),
        "pattern_desc": meta.get("pattern_desc", ""),
        "snr_role": meta.get("snr_role", ""),
        "snr_valid": bool(meta.get("snr_valid", False)),
        "zone_high": zone_obj.zone_high,
        "zone_low": zone_obj.zone_low,
        "zone_score": zone_obj.zone_score,
        "score_breakdown": zone_obj.score_breakdown,
        "detection_time": str(zone_obj.detection_time),
        "zone_status": zone_obj.zone_status,
        "freshness": zone_obj.freshness,
        "invalidation_price": zone_obj.invalidation_price,
    }


def format_signal_payload(signal_obj: Any) -> Dict[str, Any]:
    return {
        "signal_id": signal_obj.signal_id,
        "market": signal_obj.market,
        "direction": signal_obj.direction,
        "entry": signal_obj.entry,
        "stop_loss": signal_obj.stop_loss,
        "take_profit_1": signal_obj.take_profit_1,
        "take_profit_2": signal_obj.take_profit_2,
        "risk_reward": signal_obj.risk_reward,
        "zone_score": signal_obj.zone_score,
        "confirmation_reasons": list(signal_obj.confirmation_reasons),
        "signal_time": str(signal_obj.signal_time),
        "signal_status": signal_obj.signal_status,
    }


def render_analysis_text(result: Dict[str, Any]) -> str:
    market = result.get("market", "-")
    mode = result.get("mode", "mtf")
    mode_label = "SCALPING (H1 -> M5)" if mode == "scp" else "MTF (H4 -> H1 -> M5)"
    trend_label = result.get("h4_trend", "-")
    trend_prefix = "Arah H1" if mode == "scp" else "Arah H4"
    trading_allowed = bool(result.get("trading_allowed", False))
    no_trade_reason = result.get("no_trade_reason")
    zones: List[Dict[str, Any]] = result.get("active_zones", [])
    signals: List[Dict[str, Any]] = result.get("confirmed_signals", [])

    lines = [
        f"ZONE HUNTER ENGINE — {market} [{mode_label}]",
        f"{trend_prefix}: {trend_label} | Zona H1 Aktif: {len(zones)} | Sinyal CONFIRMED: {len(signals)}",
    ]

    if not trading_allowed or not zones:
        lines.append(f"Status: TIDAK TRADING — {no_trade_reason or 'Zona H1 tidak tersedia.'}")
        return "\n".join(lines)

    for z in zones:
        pat_tag = f"{z.get('pattern', 'SND')}"
        snr_tag = f" | SNR: {z['snr_role']}" if z.get("snr_role") else ""
        lines.append(
            f"- [{z['direction']}] {pat_tag} ({z['timeframe']}{snr_tag}) | "
            f"Skor: {z['zone_score']} | Status: {z['zone_status']} | {z['freshness']} | "
            f"Range: {z['zone_low']} - {z['zone_high']} | Inv: {z['invalidation_price']}"
        )

    for s in signals:
        lines.append(
            f"* SINYAL {s['direction']} ({s['signal_id']}) | Entry: {s['entry']} | "
            f"SL: {s['stop_loss']} | TP1: {s['take_profit_1']} | TP2: {s['take_profit_2']} | "
            f"R:R: 1:{s['risk_reward']} | Skor: {s['zone_score']}"
        )

    if not signals:
        lines.append("Status Sinyal M5: WAIT (menunggu konfirmasi entry M5).")

    return "\n".join(lines)
