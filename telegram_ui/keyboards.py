from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from telegram_ui.callbacks import build_callback


def build_main_menu_keyboard(epoch_sec: int | None = None) -> InlineKeyboardMarkup:
    """
    MAIN MENU:
    - 🟡 XAUUSD (H4 -> H1 -> M5) | ₿ BTCUSD (H4 -> H1 -> M5)
    - ⚡ Scalping XAUUSD (H1 -> M5) | ⚡ Scalping BTCUSD (H1 -> M5)
    """
    keyboard = [
        [
            InlineKeyboardButton("🟡 XAUUSD", callback_data=build_callback("mkt", "XAUUSD", epoch_sec, mode="mtf")),
            InlineKeyboardButton("₿ BTCUSD", callback_data=build_callback("mkt", "BTCUSD", epoch_sec, mode="mtf")),
        ],
        [
            InlineKeyboardButton("⚡ Scalping XAUUSD", callback_data=build_callback("mkt", "XAUUSD", epoch_sec, mode="scp")),
            InlineKeyboardButton("⚡ Scalping BTCUSD", callback_data=build_callback("mkt", "BTCUSD", epoch_sec, mode="scp")),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_analysis_result_keyboard(
    market: str,
    epoch_sec: int | None = None,
    mode: str = "mtf",
) -> InlineKeyboardMarkup:
    """
    ANALYSIS RESULT MENU:
    - 🔄 Refresh
    - 🔀 Ganti Market
    - ⬅️ Kembali
    - 🏠 Menu Utama
    """
    mkt = market.upper()
    m = "scp" if mode == "scp" else "mtf"
    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=build_callback("ref", mkt, epoch_sec, mode=m)),
            InlineKeyboardButton("🔀 Ganti Market", callback_data=build_callback("chg", None, epoch_sec, mode=m)),
        ],
        [
            InlineKeyboardButton("⬅️ Kembali", callback_data=build_callback("back", None, epoch_sec, mode=m)),
            InlineKeyboardButton("🏠 Menu Utama", callback_data=build_callback("home", None, epoch_sec, mode=m)),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
