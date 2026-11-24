from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from zone_hunter.risk.risk_manager import RiskManager
from zone_hunter.risk.volatility_manager import VolatilityManager


@dataclass
class TradePlan:
    market: str
    direction: str  # "BUY" or "SELL"
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    risk_reward_tp2: float
    atr_value: float
    atr_buffer: float
    is_valid: bool
    rejection_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class EntryEngine:
    """Menghitung Entry retracement, SL di luar invalidasi + ATR buffer, serta TP1/TP2 (R:R >= 1:2)."""

    def __init__(
        self,
        risk_manager: Optional[RiskManager] = None,
        volatility_manager: Optional[VolatilityManager] = None,
    ) -> None:
        self.risk_manager = risk_manager or RiskManager()
        self.volatility_manager = volatility_manager or VolatilityManager()

    def build_plan(
        self,
        market: str,
        direction: str,
        zone_low: float,
        zone_high: float,
        invalidation_price: float,
        atr_value: float,
        liquidity_targets: Optional[List[float]] = None,
    ) -> TradePlan:
        dir_upper = direction.upper()
        spec = self.risk_manager.get_spec(market)
        atr_buf = self.volatility_manager.compute_buffer(atr_value, spec.sl_atr_mult)
        retrace_buf = self.volatility_manager.compute_buffer(atr_value, spec.retracement_atr_mult)

        targets = sorted([float(x) for x in (liquidity_targets or []) if x is not None])

        if dir_upper == "BUY":
            raw_entry = min(zone_high, max(zone_low, zone_low + 0.65 * (zone_high - zone_low)))
            if retrace_buf > 0 and (raw_entry - retrace_buf) > zone_low:
                raw_entry = raw_entry - retrace_buf
            entry = self.risk_manager.round_price(market, raw_entry)

            raw_sl = min(invalidation_price, zone_low) - atr_buf
            stop_loss = self.risk_manager.round_price(market, raw_sl)

            risk_dist = entry - stop_loss
            if risk_dist <= 0:
                return TradePlan(
                    market=market,
                    direction=dir_upper,
                    entry=entry,
                    stop_loss=stop_loss,
                    take_profit_1=entry,
                    take_profit_2=entry,
                    risk_reward=0.0,
                    risk_reward_tp2=0.0,
                    atr_value=atr_value,
                    atr_buffer=atr_buf,
                    is_valid=False,
                    rejection_reason="Jarak entry ke stop loss tidak valid (<= 0)",
                )

            above_targets = [t for t in targets if t > entry + (spec.min_rr * risk_dist)]
            if len(above_targets) >= 2:
                tp1 = self.risk_manager.round_price(market, above_targets[0])
                tp2 = self.risk_manager.round_price(market, above_targets[-1])
            elif len(above_targets) == 1:
                tp1 = self.risk_manager.round_price(market, above_targets[0])
                tp2 = self.risk_manager.round_price(market, max(above_targets[0], entry + (spec.min_rr * 1.5 * risk_dist)))
            else:
                tp1 = self.risk_manager.round_price(market, entry + (spec.min_rr * risk_dist))
                tp2 = self.risk_manager.round_price(market, entry + (spec.min_rr * 1.5 * risk_dist))

        elif dir_upper == "SELL":
            raw_entry = max(zone_low, min(zone_high, zone_low + 0.35 * (zone_high - zone_low)))
            if retrace_buf > 0 and (raw_entry + retrace_buf) < zone_high:
                raw_entry = raw_entry + retrace_buf
            entry = self.risk_manager.round_price(market, raw_entry)

            raw_sl = max(invalidation_price, zone_high) + atr_buf
            stop_loss = self.risk_manager.round_price(market, raw_sl)

            risk_dist = stop_loss - entry
            if risk_dist <= 0:
                return TradePlan(
                    market=market,
                    direction=dir_upper,
                    entry=entry,
                    stop_loss=stop_loss,
                    take_profit_1=entry,
                    take_profit_2=entry,
                    risk_reward=0.0,
                    risk_reward_tp2=0.0,
                    atr_value=atr_value,
                    atr_buffer=atr_buf,
                    is_valid=False,
                    rejection_reason="Jarak stop loss ke entry tidak valid (<= 0)",
                )

            below_targets = sorted(
                [t for t in targets if t < entry - (spec.min_rr * risk_dist)],
                reverse=True,
            )
            if len(below_targets) >= 2:
                tp1 = self.risk_manager.round_price(market, below_targets[0])
                tp2 = self.risk_manager.round_price(market, below_targets[-1])
            elif len(below_targets) == 1:
                tp1 = self.risk_manager.round_price(market, below_targets[0])
                tp2 = self.risk_manager.round_price(market, min(below_targets[0], entry - (spec.min_rr * 1.5 * risk_dist)))
            else:
                tp1 = self.risk_manager.round_price(market, entry - (spec.min_rr * risk_dist))
                tp2 = self.risk_manager.round_price(market, entry - (spec.min_rr * 1.5 * risk_dist))
        else:
            return TradePlan(
                market=market,
                direction=dir_upper,
                entry=0.0,
                stop_loss=0.0,
                take_profit_1=0.0,
                take_profit_2=0.0,
                risk_reward=0.0,
                risk_reward_tp2=0.0,
                atr_value=atr_value,
                atr_buffer=atr_buf,
                is_valid=False,
                rejection_reason="Arah tidak dikenal",
            )

        rr1 = self.risk_manager.calculate_rr(dir_upper, entry, stop_loss, tp1)
        rr2 = self.risk_manager.calculate_rr(dir_upper, entry, stop_loss, tp2)

        if not self.risk_manager.meets_min_rr(market, rr1):
            return TradePlan(
                market=market,
                direction=dir_upper,
                entry=entry,
                stop_loss=stop_loss,
                take_profit_1=tp1,
                take_profit_2=tp2,
                risk_reward=rr1,
                risk_reward_tp2=rr2,
                atr_value=atr_value,
                atr_buffer=atr_buf,
                is_valid=False,
                rejection_reason=f"R:R {rr1:.2f} di bawah minimal {spec.min_rr:.2f}",
            )

        return TradePlan(
            market=market,
            direction=dir_upper,
            entry=entry,
            stop_loss=stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            risk_reward=rr1,
            risk_reward_tp2=rr2,
            atr_value=atr_value,
            atr_buffer=atr_buf,
            is_valid=True,
        )
