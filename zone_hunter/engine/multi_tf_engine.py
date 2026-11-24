from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from zone_hunter.detectors.fair_value_gap import FairValueGapDetector
from zone_hunter.detectors.liquidity import LiquidityDetector
from zone_hunter.detectors.market_structure import MarketStructureDetector
from zone_hunter.detectors.order_block import OrderBlockDetector
from zone_hunter.detectors.supply_demand import SupplyDemandDetector


@dataclass
class MultiTFCandidate:
    market: str
    direction: str  # "BUY" or "SELL"
    alignment_type: str  # "TREND_ALIGNED"
    h4_trend: str
    h1_zone: Any
    h1_source_type: str  # "SUPPLY_DEMAND" or "ORDER_BLOCK"
    m15_validated: bool
    m5_ready: bool
    timestamp_anchor: Any
    evidence: Dict[str, Any] = field(default_factory=dict)


class MultiTFEngine:
    """
    Menjalankan:
    - Mode MTF: H4 (arah & zona induk) -> H1 (zona & penolakan di zona H4) -> M5 (konfirmasi entry).
    - Mode Scalping: H1 (arah & zona H1, koreksi diabaikan, jika zona H1 kosong -> tidak trading) -> M5 (konfirmasi entry).
    """

    def __init__(
        self,
        sd_detector: Optional[SupplyDemandDetector] = None,
        ob_detector: Optional[OrderBlockDetector] = None,
        liq_detector: Optional[LiquidityDetector] = None,
        ms_detector: Optional[MarketStructureDetector] = None,
        fvg_detector: Optional[FairValueGapDetector] = None,
    ) -> None:
        self.sd_detector = sd_detector or SupplyDemandDetector()
        self.ob_detector = ob_detector or OrderBlockDetector()
        self.liq_detector = liq_detector or LiquidityDetector()
        self.ms_detector = ms_detector or MarketStructureDetector()
        self.fvg_detector = fvg_detector or FairValueGapDetector()

    @staticmethod
    def _closed_slice(df: pd.DataFrame, is_last_bar_closed: bool = True) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        if is_last_bar_closed:
            return df.reset_index(drop=True)
        return df.iloc[:-1].reset_index(drop=True)

    @staticmethod
    def _latest_ts(df: pd.DataFrame) -> Any:
        if df is None or df.empty or "timestamp" not in df.columns:
            return None
        return df["timestamp"].iloc[-1]

    @staticmethod
    def _zone_reached_and_rejected(
        df_lower: pd.DataFrame,
        parent_zones: List[Any],
        direction: str,
    ) -> Optional[Any]:
        if df_lower.empty or not parent_zones:
            return None

        recent = df_lower.tail(6)
        r_highs = recent["high"].astype(float).to_numpy()
        r_lows = recent["low"].astype(float).to_numpy()
        r_opens = recent["open"].astype(float).to_numpy()
        r_closes = recent["close"].astype(float).to_numpy()

        for pz in reversed(parent_zones):
            if getattr(pz, "is_invalidated", False):
                continue
            if getattr(pz, "direction", "") != direction:
                continue
            z_low = float(pz.zone_low)
            z_high = float(pz.zone_high)

            reached = any((r_lows[i] <= z_high) and (r_highs[i] >= z_low) for i in range(len(recent)))
            if not reached:
                continue

            if direction == "BUY":
                rejected = any(
                    (r_lows[i] <= z_high)
                    and (r_closes[i] >= z_low)
                    and (
                        r_closes[i] > r_opens[i]
                        or (min(r_opens[i], r_closes[i]) - r_lows[i]) > abs(r_closes[i] - r_opens[i])
                    )
                    for i in range(len(recent))
                )
            else:
                rejected = any(
                    (r_highs[i] >= z_low)
                    and (r_closes[i] <= z_high)
                    and (
                        r_closes[i] < r_opens[i]
                        or (r_highs[i] - max(r_opens[i], r_closes[i])) > abs(r_closes[i] - r_opens[i])
                    )
                    for i in range(len(recent))
                )

            if rejected:
                return pz

        return None


    @staticmethod
    def _sequence_confirmed(
        df_lower: pd.DataFrame,
        zone: Any,
        direction: str,
        ms_events: List[Any],
    ) -> bool:
        """
        Memeriksa urutan:
        1) Harga menyentuh zona & mengalami rejection
        2) Muncul candle impulsif searah (bearish kuat untuk SELL / bullish kuat untuk BUY)
        3) Terjadi BOS ke bawah (SELL) atau BOS ke atas (BUY) sebagai konfirmasi
        """
        if df_lower is None or df_lower.empty or zone is None:
            return False

        z_low = float(zone.zone_low)
        z_high = float(zone.zone_high)
        opens = df_lower["open"].astype(float).to_numpy()
        highs = df_lower["high"].astype(float).to_numpy()
        lows = df_lower["low"].astype(float).to_numpy()
        closes = df_lower["close"].astype(float).to_numpy()
        bodies = np.abs(closes - opens)
        ranges = np.maximum(highs - lows, 1e-12)
        avg_body = float(np.mean(bodies[-14:])) if len(bodies) >= 1 else 0.0
        body_thresh = max(avg_body * 1.25, 1e-12)

        touch_idx = None
        start_scan = max(0, len(df_lower) - 12)

        if direction == "SELL":
            for i in range(start_scan, len(df_lower)):
                touched = (highs[i] >= z_low) and (lows[i] <= z_high)
                upper_wick = highs[i] - max(opens[i], closes[i])
                rejected = touched and (closes[i] <= z_high) and (
                    closes[i] < opens[i] or upper_wick > bodies[i]
                )
                if rejected:
                    touch_idx = i
                    break
            if touch_idx is None:
                return False

            has_strong_bear = any(
                (closes[j] < opens[j])
                and (bodies[j] >= body_thresh)
                and ((bodies[j] / ranges[j]) >= 0.55)
                for j in range(touch_idx, len(df_lower))
            )
            if not has_strong_bear:
                return False

            has_bos_down = any(
                getattr(ev, "event_type", "") == "BOS"
                and getattr(ev, "direction", "") == "BEARISH"
                and int(getattr(ev, "candle_index", -1)) >= touch_idx
                for ev in (ms_events or [])
            )
            return has_bos_down

        elif direction == "BUY":
            for i in range(start_scan, len(df_lower)):
                touched = (lows[i] <= z_high) and (highs[i] >= z_low)
                lower_wick = min(opens[i], closes[i]) - lows[i]
                rejected = touched and (closes[i] >= z_low) and (
                    closes[i] > opens[i] or lower_wick > bodies[i]
                )
                if rejected:
                    touch_idx = i
                    break
            if touch_idx is None:
                return False

            has_strong_bull = any(
                (closes[j] > opens[j])
                and (bodies[j] >= body_thresh)
                and ((bodies[j] / ranges[j]) >= 0.55)
                for j in range(touch_idx, len(df_lower))
            )
            if not has_strong_bull:
                return False

            has_bos_up = any(
                getattr(ev, "event_type", "") == "BOS"
                and getattr(ev, "direction", "") == "BULLISH"
                and int(getattr(ev, "candle_index", -1)) >= touch_idx
                for ev in (ms_events or [])
            )
            return has_bos_up

        return False

    def _build_m5_candidate(
        self,
        market: str,
        direction: str,
        trend_label: str,
        zone: Any,
        source_type: str,
        m5_ts: Any,
        m5_ms: Dict[str, Any],
        m5_liq: Dict[str, Any],
        m5_fvg: List[Any],
        extra_evidence: Dict[str, Any],
    ) -> Optional[MultiTFCandidate]:
        if getattr(zone, "is_invalidated", False):
            return None

        m5_choch_or_bos = any(
            ev.direction == trend_label and ev.timestamp <= (m5_ts or ev.timestamp)
            for ev in m5_ms["events"]
        )
        m5_sweep = any(
            sw.direction_bias == direction and sw.sweep_time <= (m5_ts or sw.sweep_time)
            for sw in m5_liq["sweeps"]
        )
        m5_fvg_ok = any(
            g.direction == direction and g.fill_status != "FULLY_FILLED"
            for g in m5_fvg
        )
        m5_ready = bool(m5_choch_or_bos or m5_sweep or m5_fvg_ok)

        ev = dict(extra_evidence)
        ev.update(
            {
                "m5_choch_or_bos": m5_choch_or_bos,
                "m5_sweep": m5_sweep,
                "m5_fvg_ok": m5_fvg_ok,
                "m5_fvg_count": len(
                    [g for g in m5_fvg if g.direction == direction and g.fill_status != "FULLY_FILLED"]
                ),
            }
        )

        return MultiTFCandidate(
            market=market,
            direction=direction,
            alignment_type="TREND_ALIGNED",
            h4_trend=trend_label,
            h1_zone=zone,
            h1_source_type=source_type,
            m15_validated=True,
            m5_ready=m5_ready,
            timestamp_anchor=m5_ts,
            evidence=ev,
        )

    def analyze_scalping(
        self,
        market: str,
        candles_by_tf: Dict[str, pd.DataFrame],
        closed_flags: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """Mode Scalping 2 TF: H1 (arah & zona, koreksi diabaikan, jika zona H1 kosong -> tidak trading) -> M5 (konfirmasi entry)."""
        flags = closed_flags or {}
        df_h1 = self._closed_slice(candles_by_tf.get("H1", pd.DataFrame()), flags.get("H1", True))
        df_m5 = self._closed_slice(candles_by_tf.get("M5", pd.DataFrame()), flags.get("M5", True))

        h1_ms = self.ms_detector.detect(df_h1, market=market, timeframe="H1")
        h1_trend = h1_ms["trend"]
        m5_ts = self._latest_ts(df_m5)

        if h1_trend not in ("BULLISH", "BEARISH"):
            return {
                "market": market,
                "mode": "scp",
                "h4_trend": h1_trend,
                "trend_label": h1_trend,
                "no_trade_reason": "Arah H1 belum jelas (RANGE); koreksi/tidak ada sinyal scalping.",
                "anchors": {"H1": self._latest_ts(df_h1), "M5": m5_ts},
                "candidates": [],
            }

        target_direction = "BUY" if h1_trend == "BULLISH" else "SELL"
        h1_sd_list = [
            z for z in self.sd_detector.detect(df_h1, market=market, timeframe="H1")
            if getattr(z, "direction", "") == target_direction and not getattr(z, "is_invalidated", False)
        ]
        h1_ob_list = [
            z for z in self.ob_detector.detect(df_h1, market=market, timeframe="H1")
            if getattr(z, "direction", "") == target_direction and not getattr(z, "is_invalidated", False)
        ]

        if not h1_sd_list and not h1_ob_list:
            return {
                "market": market,
                "mode": "scp",
                "h4_trend": h1_trend,
                "trend_label": h1_trend,
                "no_trade_reason": f"H1 tidak menunjukkan zona {target_direction} apapun -> tidak trading.",
                "anchors": {"H1": self._latest_ts(df_h1), "M5": m5_ts},
                "candidates": [],
            }

        h1_liq = self.liq_detector.detect(df_h1, market=market, timeframe="H1")
        m5_ms = self.ms_detector.detect(df_m5, market=market, timeframe="M5")

        # Pastikan harga M5 menyentuh zona H1 + rejection + candle impulsif searah + BOS konfirmasi
        all_h1_zones = h1_sd_list + h1_ob_list
        matched_h1_zone = self._zone_reached_and_rejected(df_m5, all_h1_zones, target_direction)
        if matched_h1_zone is None:
            return {
                "market": market,
                "mode": "scp",
                "h4_trend": h1_trend,
                "trend_label": h1_trend,
                "no_trade_reason": f"Harga belum sampai di zona {target_direction} H1 atau belum menunjukkan penolakan (dianggap koreksi).",
                "anchors": {"H1": self._latest_ts(df_h1), "M5": m5_ts},
                "candidates": [],
            }

        seq_ok_zones = [
            z for z in all_h1_zones
            if self._sequence_confirmed(df_m5, z, target_direction, m5_ms.get("events", []))
        ]
        if not seq_ok_zones:
            return {
                "market": market,
                "mode": "scp",
                "h4_trend": h1_trend,
                "trend_label": h1_trend,
                "no_trade_reason": f"Urutan konfirmasi {target_direction} belum lengkap (butuh rejection + candle impulsif + BOS searah).",
                "anchors": {"H1": self._latest_ts(df_h1), "M5": m5_ts},
                "candidates": [],
            }
        m5_liq = self.liq_detector.detect(df_m5, market=market, timeframe="M5")
        m5_fvg = self.fvg_detector.detect(df_m5, market=market, timeframe="M5")

        candidates: List[MultiTFCandidate] = []
        extra = {
            "h4_aligned": True,
            "h1_ms": h1_ms,
            "h1_liq": h1_liq,
            "scalping_2tf": True,
        }
        seq_ids = {getattr(z, "zone_id", id(z)) for z in seq_ok_zones}
        for sd in h1_sd_list:
            if getattr(sd, "zone_id", id(sd)) not in seq_ids:
                continue
            cand = self._build_m5_candidate(
                market, target_direction, h1_trend, sd, "SUPPLY_DEMAND", m5_ts, m5_ms, m5_liq, m5_fvg, extra
            )
            if cand is not None:
                cand.evidence["sequence_confirmed"] = True
                candidates.append(cand)
        for ob in h1_ob_list:
            if getattr(ob, "zone_id", id(ob)) not in seq_ids:
                continue
            cand = self._build_m5_candidate(
                market, target_direction, h1_trend, ob, "ORDER_BLOCK", m5_ts, m5_ms, m5_liq, m5_fvg, extra
            )
            if cand is not None:
                cand.evidence["sequence_confirmed"] = True
                candidates.append(cand)

        return {
            "market": market,
            "mode": "scp",
            "h4_trend": h1_trend,
            "trend_label": h1_trend,
            "no_trade_reason": None if candidates else f"H1 tidak menunjukkan zona {target_direction} apapun -> tidak trading.",
            "anchors": {"H1": self._latest_ts(df_h1), "M5": m5_ts},
            "candidates": candidates,
        }

    def analyze(
        self,
        market: str,
        candles_by_tf: Dict[str, pd.DataFrame],
        closed_flags: Optional[Dict[str, bool]] = None,
        mode: str = "mtf",
    ) -> Dict[str, Any]:
        if mode == "scp":
            return self.analyze_scalping(market, candles_by_tf, closed_flags=closed_flags)

        flags = closed_flags or {}
        df_h4 = self._closed_slice(candles_by_tf.get("H4", pd.DataFrame()), flags.get("H4", True))
        df_h1 = self._closed_slice(candles_by_tf.get("H1", pd.DataFrame()), flags.get("H1", True))
        df_m5 = self._closed_slice(candles_by_tf.get("M5", pd.DataFrame()), flags.get("M5", True))
        df_m15 = self._closed_slice(candles_by_tf.get("M15", pd.DataFrame()), flags.get("M15", True))

        h4_ms = self.ms_detector.detect(df_h4, market=market, timeframe="H4")
        h4_trend = h4_ms["trend"]

        m5_ts = self._latest_ts(df_m5)
        m15_ts = self._latest_ts(df_m15)

        if h4_trend not in ("BULLISH", "BEARISH"):
            return {
                "market": market,
                "mode": "mtf",
                "h4_trend": h4_trend,
                "trend_label": h4_trend,
                "no_trade_reason": "Arah H4 belum jelas (RANGE); koreksi/tidak ada sinyal.",
                "anchors": {
                    "H4": self._latest_ts(df_h4),
                    "H1": self._latest_ts(df_h1),
                    "M15": m15_ts,
                    "M5": m5_ts,
                },
                "candidates": [],
            }

        target_direction = "BUY" if h4_trend == "BULLISH" else "SELL"

        h4_sd = self.sd_detector.detect(df_h4, market=market, timeframe="H4")
        h4_ob = self.ob_detector.detect(df_h4, market=market, timeframe="H4")
        h4_zones_aligned = [
            z for z in (h4_sd + h4_ob)
            if getattr(z, "direction", "") == target_direction and not getattr(z, "is_invalidated", False)
        ]

        matched_h4_zone = self._zone_reached_and_rejected(df_h1, h4_zones_aligned, target_direction)
        if matched_h4_zone is None:
            return {
                "market": market,
                "mode": "mtf",
                "h4_trend": h4_trend,
                "trend_label": h4_trend,
                "no_trade_reason": f"Harga H1 belum sampai di zona {target_direction} H4 atau belum menunjukkan penolakan (dianggap koreksi).",
                "anchors": {
                    "H4": self._latest_ts(df_h4),
                    "H1": self._latest_ts(df_h1),
                    "M15": m15_ts,
                    "M5": m5_ts,
                },
                "candidates": [],
            }

        h1_sd_list = [
            z for z in self.sd_detector.detect(df_h1, market=market, timeframe="H1")
            if getattr(z, "direction", "") == target_direction and not getattr(z, "is_invalidated", False)
        ]
        h1_ob_list = [
            z for z in self.ob_detector.detect(df_h1, market=market, timeframe="H1")
            if getattr(z, "direction", "") == target_direction and not getattr(z, "is_invalidated", False)
        ]

        if not h1_sd_list and not h1_ob_list:
            return {
                "market": market,
                "mode": "mtf",
                "h4_trend": h4_trend,
                "trend_label": h4_trend,
                "no_trade_reason": f"H1 tidak menunjukkan zona {target_direction} valid -> tidak trading.",
                "anchors": {
                    "H4": self._latest_ts(df_h4),
                    "H1": self._latest_ts(df_h1),
                    "M15": m15_ts,
                    "M5": m5_ts,
                },
                "candidates": [],
            }

        h1_liq = self.liq_detector.detect(df_h1, market=market, timeframe="H1")
        h1_ms = self.ms_detector.detect(df_h1, market=market, timeframe="H1")

        m5_ms = self.ms_detector.detect(df_m5, market=market, timeframe="M5")
        m5_liq = self.liq_detector.detect(df_m5, market=market, timeframe="M5")
        m5_fvg = self.fvg_detector.detect(df_m5, market=market, timeframe="M5")

        candidates: List[MultiTFCandidate] = []
        extra = {
            "h4_aligned": True,
            "h4_zone_id": getattr(matched_h4_zone, "zone_id", None),
            "h4_rejection_confirmed": True,
            "h1_ms": h1_ms,
            "h1_liq": h1_liq,
        }

        for sd in h1_sd_list:
            cand = self._build_m5_candidate(
                market, target_direction, h4_trend, sd, "SUPPLY_DEMAND", m5_ts, m5_ms, m5_liq, m5_fvg, extra
            )
            if cand is not None:
                candidates.append(cand)

        for ob in h1_ob_list:
            cand = self._build_m5_candidate(
                market, target_direction, h4_trend, ob, "ORDER_BLOCK", m5_ts, m5_ms, m5_liq, m5_fvg, extra
            )
            if cand is not None:
                candidates.append(cand)

        return {
            "market": market,
            "mode": "mtf",
            "h4_trend": h4_trend,
            "trend_label": h4_trend,
            "no_trade_reason": None if candidates else f"H1 tidak menunjukkan zona {target_direction} valid -> tidak trading.",
            "anchors": {
                "H4": self._latest_ts(df_h4),
                "H1": self._latest_ts(df_h1),
                "M15": m15_ts,
                "M5": m5_ts,
            },
            "candidates": candidates,
        }
