from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from zone_hunter.data.candle_manager import CandleManager
from zone_hunter.data.data_validator import DataValidator
from zone_hunter.data.twelve_data_client import TwelveDataClient
from zone_hunter.engine.confirmation import ConfirmationEngine
from zone_hunter.engine.entry_engine import EntryEngine
from zone_hunter.engine.multi_tf_engine import MultiTFEngine
from zone_hunter.engine.signal_manager import SignalManager, TradingSignal
from zone_hunter.engine.zone_manager import ManagedZone, ZoneManager
from zone_hunter.engine.zone_scoring import ZoneScoringEngine
from zone_hunter.formatter import format_signal_payload, format_zone_payload, render_analysis_text
from zone_hunter.risk.risk_manager import RiskManager
from zone_hunter.risk.volatility_manager import VolatilityManager


class ZoneHunterPipeline:
    """Orkestrator analisis Zone Hunter untuk mode MTF (H4 -> H1 -> M5) dan Scalping (H1 -> M5)."""

    MTF_TIMEFRAMES: tuple[str, ...] = ("H4", "H1", "M5")
    SCALPING_TIMEFRAMES: tuple[str, ...] = ("H1", "M5")

    def __init__(
        self,
        data_client: Optional[TwelveDataClient] = None,
        candle_manager: Optional[CandleManager] = None,
        validator: Optional[DataValidator] = None,
        mtf_engine: Optional[MultiTFEngine] = None,
        scoring_engine: Optional[ZoneScoringEngine] = None,
        zone_manager: Optional[ZoneManager] = None,
        confirmation_engine: Optional[ConfirmationEngine] = None,
        entry_engine: Optional[EntryEngine] = None,
        signal_manager: Optional[SignalManager] = None,
        risk_manager: Optional[RiskManager] = None,
        volatility_manager: Optional[VolatilityManager] = None,
        spread_provider: Optional[Callable[[str], float]] = None,
    ) -> None:
        self.data_client = data_client
        self.candle_manager = candle_manager or CandleManager()
        self.validator = validator or DataValidator()
        self.mtf_engine = mtf_engine or MultiTFEngine()
        self.scoring_engine = scoring_engine or ZoneScoringEngine()
        self.zone_manager = zone_manager or ZoneManager()
        self.confirmation_engine = confirmation_engine or ConfirmationEngine()
        self.risk_manager = risk_manager or RiskManager()
        self.volatility_manager = volatility_manager or VolatilityManager()
        self.entry_engine = entry_engine or EntryEngine(self.risk_manager, self.volatility_manager)
        self.signal_manager = signal_manager or SignalManager()
        self.spread_provider = spread_provider

    def _get_client(self) -> TwelveDataClient:
        if self.data_client is None:
            self.data_client = TwelveDataClient()
        return self.data_client

    def run_analysis(
        self,
        market: str,
        candles_override: Optional[Dict[str, pd.DataFrame]] = None,
        reference_now: Optional[datetime] = None,
        current_spread: Optional[float] = None,
        mode: str = "mtf",
    ) -> Dict[str, Any]:
        mkt = market.replace("/", "").upper()
        m = "scp" if str(mode).lower() in ("scp", "scalping") else "mtf"
        tfs = self.SCALPING_TIMEFRAMES if m == "scp" else self.MTF_TIMEFRAMES
        now_utc = (reference_now or datetime.now(timezone.utc)).astimezone(timezone.utc)

        closed_by_tf: Dict[str, pd.DataFrame] = {}
        validation_errors: List[str] = []

        if candles_override is not None:
            for tf in tfs:
                raw_df = candles_override.get(tf, pd.DataFrame())
                self.candle_manager.update_cache(mkt, tf, raw_df)
                closed_df = self.candle_manager.get_closed_candles(mkt, tf, reference_now=now_utc)
                rep = self.validator.validate_ohlcv(closed_df, tf, reference_now=now_utc, min_candles=20)
                if not rep.is_valid:
                    validation_errors.extend([f"{tf}: {e}" for e in rep.errors])
                closed_by_tf[tf] = closed_df
        else:
            client = self._get_client()
            for tf in tfs:
                fetched = client.fetch_ohlcv(mkt, tf, outputsize=150)
                self.candle_manager.update_cache(mkt, tf, fetched)
                closed_df = self.candle_manager.get_closed_candles(mkt, tf, reference_now=now_utc)
                rep = self.validator.validate_ohlcv(closed_df, tf, reference_now=now_utc, min_candles=20)
                if not rep.is_valid:
                    validation_errors.extend([f"{tf}: {e}" for e in rep.errors])
                closed_by_tf[tf] = closed_df

        df_m5 = closed_by_tf.get("M5", pd.DataFrame())
        if df_m5.empty:
            payload = {
                "market": mkt,
                "mode": m,
                "h4_trend": "UNKNOWN",
                "trading_allowed": False,
                "no_trade_reason": "Data M5 closed kosong -> tidak trading.",
                "active_zones": [],
                "confirmed_signals": [],
                "validation_errors": validation_errors or ["Data M5 closed kosong."],
                "analyzed_at": now_utc.isoformat(),
            }
            payload["formatted_text"] = render_analysis_text(payload)
            return payload

        mtf_res = self.mtf_engine.analyze(mkt, closed_by_tf, mode=m)
        trend_label = mtf_res.get("trend_label", mtf_res.get("h4_trend", "RANGE"))
        candidates = mtf_res.get("candidates", [])

        if not candidates:
            reason = mtf_res.get("no_trade_reason") or "Tidak ada zona valid -> tidak trading."
            payload = {
                "market": mkt,
                "mode": m,
                "h4_trend": trend_label,
                "trading_allowed": False,
                "no_trade_reason": reason,
                "active_zones": [],
                "confirmed_signals": [],
                "validation_errors": validation_errors,
                "analyzed_at": now_utc.isoformat(),
            }
            payload["formatted_text"] = render_analysis_text(payload)
            return payload

        latest_close = float(df_m5["close"].iloc[-1])
        latest_high = float(df_m5["high"].iloc[-1])
        latest_low = float(df_m5["low"].iloc[-1])
        m5_atr = self.volatility_manager.get_latest_atr(df_m5)

        if current_spread is not None:
            spread_val = float(current_spread)
        elif self.spread_provider is not None:
            spread_val = float(self.spread_provider(mkt))
        else:
            spread_val = 0.0

        spread_ok = self.risk_manager.is_spread_acceptable(mkt, spread_val)
        data_quality_ok = (len(validation_errors) == 0) and spread_ok

        for cand in candidates:
            z = cand.h1_zone
            ev = cand.evidence
            h1_ms_events = ev.get("h1_ms", {}).get("events", [])
            h1_liq = ev.get("h1_liq", {})
            expected_dir = "BULLISH" if cand.direction == "BUY" else "BEARISH"

            score_ctx = {
                "sd_zone": z if cand.h1_source_type == "SUPPLY_DEMAND" else None,
                "ob_zone": z if cand.h1_source_type == "ORDER_BLOCK" else None,
                "same_event_overlap": False,
                "liquidity_info": {
                    "has_sweep": bool(ev.get("m5_sweep")),
                    "equal_hl": any(
                        lvl.subtype in ("EQUAL_HIGH", "EQUAL_LOW") for lvl in h1_liq.get("levels", [])
                    ),
                    "clear_target_pool": len(h1_liq.get("levels", [])) > 0,
                },
                "structure_info": {
                    "bos_aligned": any(
                        e.event_type == "BOS" and e.direction == expected_dir for e in h1_ms_events
                    ),
                    "choch_present": bool(ev.get("m5_choch_or_bos")),
                    "swing_sequence_valid": len(ev.get("h1_ms", {}).get("swing_points", [])) >= 2,
                },
                "mtf_info": {
                    "h4_aligned": bool(ev.get("h4_aligned")),
                    "m15_validated": True,
                    "m5_ready": cand.m5_ready,
                    "alignment_type": cand.alignment_type,
                },
                "freshness_impulse_info": {
                    "is_fresh": bool(getattr(z, "is_fresh", not getattr(z, "is_mitigated", False))),
                    "retest_count": int(getattr(z, "retest_count", 0)),
                    "impulse_quality": float(
                        getattr(z, "impulse_strength", getattr(z, "displacement_strength", 0.5))
                    ),
                },
            }

            score_res = self.scoring_engine.score_zone(score_ctx)
            is_fresh_flag = bool(getattr(z, "is_fresh", not getattr(z, "is_mitigated", False)))
            managed = ManagedZone(
                zone_id=z.zone_id,
                market=mkt,
                direction=cand.direction,
                timeframe="H1",
                zone_low=float(z.zone_low),
                zone_high=float(z.zone_high),
                zone_score=score_res.total_score,
                score_breakdown=score_res.breakdown,
                invalidation_price=float(z.invalidation_price),
                detection_time=z.created_at,
                freshness="FRESH" if is_fresh_flag else "RETESTED",
                metadata={
                    "alignment_type": cand.alignment_type,
                    "pattern": getattr(z, "metadata", {}).get("pattern", "SND"),
                    "pattern_desc": getattr(z, "metadata", {}).get("pattern_desc", ""),
                    "zone_kind": getattr(z, "metadata", {}).get("zone_kind", ""),
                    "snr_role": getattr(z, "metadata", {}).get("snr_role", ""),
                    "snr_valid": bool(getattr(z, "metadata", {}).get("snr_valid", False)),
                    "m5_ready": cand.m5_ready,
                    "m5_sweep": bool(ev.get("m5_sweep")),
                    "m5_choch": bool(ev.get("m5_choch_or_bos")),
                    "has_displacement": float(
                        getattr(z, "impulse_strength", getattr(z, "displacement_strength", 0.0))
                    ) > 0.0,
                },
            )
            self.zone_manager.register_or_update(managed, now_utc)

        selected_map = self.zone_manager.evaluate_market(
            market=mkt,
            current_price=latest_close,
            current_close=latest_close,
            timestamp=now_utc,
            approach_buffer=m5_atr * 1.5,
        )

        active_zones_objs: List[ManagedZone] = (
            selected_map["BUY"] if trend_label == "BULLISH" else selected_map["SELL"]
        )
        confirmed_signals_payloads: List[Dict[str, Any]] = []

        for mz in active_zones_objs:
            in_zone = (latest_low <= mz.zone_high) and (latest_high >= mz.zone_low)
            conf = self.confirmation_engine.evaluate(
                direction=mz.direction,
                zone_score=mz.zone_score,
                price_in_zone=in_zone,
                has_liquidity_sweep=bool(mz.metadata.get("m5_sweep", False)),
                m5_choch_confirmed=bool(mz.metadata.get("m5_choch", False)),
                has_displacement=bool(mz.metadata.get("has_displacement", False)),
                has_clear_structure_and_invalidation=(mz.invalidation_price > 0),
                spread_and_data_valid=data_quality_ok,
            )
            if not conf.is_confirmed:
                continue

            plan = self.entry_engine.build_plan(
                market=mkt,
                direction=mz.direction,
                zone_low=mz.zone_low,
                zone_high=mz.zone_high,
                invalidation_price=mz.invalidation_price,
                atr_value=max(m5_atr, self.risk_manager.get_spec(mkt).tick_size),
            )
            if not plan.is_valid:
                self.signal_manager.record_cancelled()
                continue

            sig_id = f"SIG_{mkt}_{m.upper()}_{mz.direction}_{mz.zone_id}_{int(now_utc.timestamp())}"
            sig = TradingSignal(
                signal_id=sig_id,
                market=mkt,
                direction=mz.direction,
                entry=plan.entry,
                stop_loss=plan.stop_loss,
                take_profit_1=plan.take_profit_1,
                take_profit_2=plan.take_profit_2,
                risk_reward=plan.risk_reward,
                zone_score=mz.zone_score,
                confirmation_reasons=conf.reasons,
                signal_time=now_utc.isoformat(),
                signal_status="CONFIRMED",
                zone_id=mz.zone_id,
            )
            published = self.signal_manager.publish_if_unique(sig)
            if published is not None:
                confirmed_signals_payloads.append(format_signal_payload(published))

        result = {
            "market": mkt,
            "mode": m,
            "h4_trend": trend_label,
            "trading_allowed": True,
            "no_trade_reason": None,
            "active_zones": [format_zone_payload(z) for z in active_zones_objs],
            "confirmed_signals": confirmed_signals_payloads,
            "validation_errors": validation_errors,
            "analyzed_at": now_utc.isoformat(),
        }
        result["formatted_text"] = render_analysis_text(result)
        return result
