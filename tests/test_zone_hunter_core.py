from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd

from zone_hunter.data.candle_manager import CandleManager
from zone_hunter.data.data_validator import DataValidator
from zone_hunter.detectors.fair_value_gap import FairValueGapDetector
from zone_hunter.detectors.liquidity import LiquidityDetector
from zone_hunter.detectors.market_structure import MarketStructureDetector
from zone_hunter.detectors.order_block import OrderBlockDetector
from zone_hunter.detectors.supply_demand import SupplyDemandDetector
from zone_hunter.engine.confirmation import ConfirmationEngine
from zone_hunter.engine.entry_engine import EntryEngine
from zone_hunter.engine.multi_tf_engine import MultiTFEngine
from zone_hunter.engine.signal_manager import SignalManager, TradingSignal
from zone_hunter.engine.zone_manager import ManagedZone, ZoneManager
from zone_hunter.engine.zone_scoring import ZoneScoringEngine


def _sample_df(rows: int = 60, start_price: float = 2600.0, step_minutes: int = 5) -> pd.DataFrame:
    base_time = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
    records = []
    price = start_price
    for i in range(rows):
        ts = base_time + timedelta(minutes=step_minutes * i)
        wave = np.sin(i / 4.0) * 6.0 + (1.5 if 20 <= i <= 24 else 0.0)
        o = price
        c = price + wave
        h = max(o, c) + 2.0
        l = min(o, c) - 2.0
        records.append({"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": 100 + i})
        price = c
    return pd.DataFrame(records)


def test_detectors_and_mtf_run():
    df_h4 = _sample_df(80, 2600.0, 240)
    df_h1 = _sample_df(80, 2600.0, 60)
    df_m15 = _sample_df(80, 2600.0, 15)
    df_m5 = _sample_df(80, 2600.0, 5)

    assert isinstance(SupplyDemandDetector().detect(df_h1, "XAUUSD", "H1"), list)
    assert isinstance(OrderBlockDetector().detect(df_h1, "XAUUSD", "H1"), list)
    assert "levels" in LiquidityDetector().detect(df_m15, "XAUUSD", "M15")
    assert "events" in MarketStructureDetector().detect(df_h4, "XAUUSD", "H4")
    assert isinstance(FairValueGapDetector().detect(df_m15, "XAUUSD", "M15"), list)

    mtf = MultiTFEngine().analyze("XAUUSD", {"H4": df_h4, "H1": df_h1, "M15": df_m15, "M5": df_m5})
    assert mtf["market"] == "XAUUSD"
    assert mtf["h4_trend"] in ("BULLISH", "BEARISH", "RANGE")


def test_scoring_threshold_and_zone_manager_cap():
    scorer = ZoneScoringEngine()
    low_res = scorer.score_zone({"sd_zone": {"impulse_strength": 0.2, "is_invalidated": False}})
    assert low_res.total_score < 70.0
    assert not low_res.is_signal_candidate

    high_res = scorer.score_zone(
        {
            "sd_zone": {"impulse_strength": 0.9, "is_invalidated": False},
            "ob_zone": {"displacement_strength": 0.9, "is_invalidated": False},
            "same_event_overlap": False,
            "liquidity_info": {"has_sweep": True, "equal_hl": True, "clear_target_pool": True},
            "structure_info": {"bos_aligned": True, "choch_present": True, "swing_sequence_valid": True},
            "mtf_info": {"h4_aligned": True, "m15_validated": True, "m5_ready": True, "alignment_type": "TREND_ALIGNED"},
            "freshness_impulse_info": {"is_fresh": True, "retest_count": 0, "impulse_quality": 1.0},
        }
    )
    assert high_res.total_score >= 70.0
    assert high_res.is_signal_candidate

    zm = ZoneManager(approach_distance=5.0)
    now = datetime.now(timezone.utc)
    for idx in range(5):
        zm.register_or_update(
            ManagedZone(
                zone_id=f"Z_BUY_{idx}",
                market="BTCUSD",
                direction="BUY",
                timeframe="H1",
                zone_low=85000.0 + idx * 5000,
                zone_high=85500.0 + idx * 5000,
                zone_score=70.0 + idx * 4,
                score_breakdown={},
                invalidation_price=84000.0 + idx * 5000,
                detection_time=now,
                freshness="FRESH",
            ),
            now,
        )
    active = zm.evaluate_market("BTCUSD", current_price=84900.0, current_close=84900.0, timestamp=now)
    assert len(active["BUY"]) <= 3


def test_confirmation_entry_and_duplicate_signal():
    conf = ConfirmationEngine()
    wait_res = conf.evaluate("BUY", 80.0, True, True, True, True, True, False)
    assert wait_res.status == "WAIT"

    ok_res = conf.evaluate("BUY", 80.0, True, True, True, True, True, True)
    assert ok_res.status == "CONFIRMED"

    plan = EntryEngine().build_plan(
        market="XAUUSD",
        direction="BUY",
        zone_low=2600.0,
        zone_high=2610.0,
        invalidation_price=2595.0,
        atr_value=4.0,
        liquidity_targets=[2635.0, 2650.0],
    )
    assert plan.is_valid
    assert plan.risk_reward >= 2.0

    sm = SignalManager()
    ts = datetime.now(timezone.utc)
    sig = TradingSignal("S1", "XAUUSD", "BUY", plan.entry, plan.stop_loss, plan.take_profit_1, plan.take_profit_2, plan.risk_reward, 80.0, ok_res.reasons, ts, "CONFIRMED", "Z1")
    assert sm.publish_if_unique(sig) is not None
    assert sm.publish_if_unique(sig) is None


def test_closed_bar_and_validator():
    now = datetime.now(timezone.utc)
    df = pd.DataFrame(
        [
            {"timestamp": now - timedelta(hours=2), "open": 2600.0, "high": 2610.0, "low": 2595.0, "close": 2605.0, "volume": 10},
            {"timestamp": now, "open": 2605.0, "high": 2615.0, "low": 2600.0, "close": 2612.0, "volume": 12},
        ]
    )
    cm = CandleManager()
    cm.update_cache("XAUUSD", "H1", df)
    closed = cm.get_closed_candles("XAUUSD", "H1", reference_now=now)
    assert len(closed) == 1

    val = DataValidator().validate_ohlcv(df, "M5", reference_now=now, min_candles=2)
    assert val.is_valid
