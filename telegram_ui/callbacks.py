from __future__ import annotations

import time
from typing import Optional, Tuple

CB_MAIN_MENU = "zh:home"
CB_SELECT_XAU = "zh:mkt:XAUUSD"
CB_SELECT_BTC = "zh:mkt:BTCUSD"
CB_REFRESH_PREFIX = "zh:ref"
CB_CHANGE_MARKET = "zh:chg"
CB_BACK = "zh:back"

MAX_CALLBACK_BYTES = 64
VALID_MODES = ("mtf", "scp")


def normalize_mode(mode: Optional[str]) -> str:
    if not mode:
        return "mtf"
    m = mode.strip().lower()
    if m in ("scp", "scalping"):
        return "scp"
    return "mtf"


def build_callback(
    action: str,
    market: Optional[str] = None,
    epoch_sec: Optional[int] = None,
    mode: Optional[str] = None,
) -> str:
    ts = int(epoch_sec if epoch_sec is not None else time.time())
    m = normalize_mode(mode)
    if action == "home":
        raw = f"{CB_MAIN_MENU}:{ts}"
    elif action == "mkt" and market:
        raw = f"zh:mkt:{market.upper()}:{m}:{ts}"
    elif action == "ref" and market:
        raw = f"{CB_REFRESH_PREFIX}:{market.upper()}:{m}:{ts}"
    elif action == "chg":
        raw = f"{CB_CHANGE_MARKET}:{m}:{ts}"
    elif action == "back":
        raw = f"{CB_BACK}:{ts}"
    else:
        raise ValueError(f"Action callback tidak valid: {action}")

    encoded = raw.encode("utf-8")
    if len(encoded) > MAX_CALLBACK_BYTES:
        raise ValueError(f"callback_data melebihi {MAX_CALLBACK_BYTES} byte: {len(encoded)}")
    return raw


def parse_callback(data: str) -> Tuple[str, Optional[str], Optional[int], str]:
    """
    Mengembalikan tuple (action, market, timestamp_sec, mode).
    mode: "mtf" (H4 -> H1 -> M5) atau "scp" (Scalping H1 -> M5).
    """
    if not data or len(data.encode("utf-8")) > MAX_CALLBACK_BYTES:
        return ("invalid", None, None, "mtf")

    parts = data.split(":")
    if len(parts) < 2 or parts[0] != "zh":
        return ("invalid", None, None, "mtf")

    kind = parts[1]
    if kind in ("home", "back"):
        ts = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else None
        return (kind, None, ts, "mtf")

    if kind == "chg":
        mode = "mtf"
        ts = None
        if len(parts) >= 3 and parts[2] in VALID_MODES:
            mode = parts[2]
            if len(parts) >= 4 and parts[3].isdigit():
                ts = int(parts[3])
        elif len(parts) >= 3 and parts[2].isdigit():
            ts = int(parts[2])
        return (kind, None, ts, mode)

    if kind in ("mkt", "ref") and len(parts) >= 3:
        mkt = parts[2].upper()
        if mkt not in ("XAUUSD", "BTCUSD"):
            return ("invalid", None, None, "mtf")
        mode = "mtf"
        ts = None
        if len(parts) >= 4 and parts[3] in VALID_MODES:
            mode = parts[3]
            if len(parts) >= 5 and parts[4].isdigit():
                ts = int(parts[4])
        elif len(parts) >= 4 and parts[3].isdigit():
            ts = int(parts[3])
        return (kind, mkt, ts, mode)

    return ("invalid", None, None, "mtf")
