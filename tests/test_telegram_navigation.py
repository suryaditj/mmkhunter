from __future__ import annotations

import asyncio
from types import SimpleNamespace

from telegram_ui.bot_handlers import ZoneHunterTelegramBot
from telegram_ui.callbacks import MAX_CALLBACK_BYTES, build_callback, parse_callback
from telegram_ui.keyboards import build_analysis_result_keyboard, build_main_menu_keyboard
from telegram_ui.state_manager import NavigationStateManager


class FakeBotTransport:
    def __init__(self) -> None:
        self.sent_messages = []
        self.edited_messages = []
        self.deleted_messages = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None, parse_mode=None):
        msg = {
            "message_id": len(self.sent_messages) + 1,
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.sent_messages.append(msg)
        return msg


class FakeCallbackQuery:
    def __init__(self, data: str, chat_id: int, user_id: int) -> None:
        self.data = data
        self.message = SimpleNamespace(chat=SimpleNamespace(id=chat_id))
        self.answered = []

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.answered.append((text, show_alert))


def _make_update(data: str, chat_id: int, user_id: int):
    q = FakeCallbackQuery(data=data, chat_id=chat_id, user_id=user_id)
    upd = SimpleNamespace(
        callback_query=q,
        effective_chat=SimpleNamespace(id=chat_id),
        effective_user=SimpleNamespace(id=user_id),
    )
    return upd, q


def test_callback_length_and_keyboards():
    for action, mkt in [("home", None), ("mkt", "XAUUSD"), ("mkt", "BTCUSD"), ("ref", "XAUUSD"), ("chg", None), ("back", None)]:
        cb = build_callback(action, mkt)
        assert len(cb.encode("utf-8")) <= MAX_CALLBACK_BYTES
        parsed_action, parsed_mkt, _, parsed_mode = parse_callback(cb)
        assert parsed_action == action
        assert parsed_mkt == mkt
        assert parsed_mode in ("mtf", "scp")

    main_kb = build_main_menu_keyboard()
    main_labels = [btn.text for row in main_kb.inline_keyboard for btn in row]
    assert main_labels == ["🟡 XAUUSD", "₿ BTCUSD", "⚡ Scalping XAUUSD", "⚡ Scalping BTCUSD"]

    res_kb = build_analysis_result_keyboard("XAUUSD")
    res_labels = [btn.text for row in res_kb.inline_keyboard for btn in row]
    assert res_labels == ["🔄 Refresh", "🔀 Ganti Market", "⬅️ Kembali", "🏠 Menu Utama"]



def test_navigation_flow_refresh_persistence_and_multi_user():
    async def _run():
        analysis_calls = []

        def fake_analyzer(market: str):
            analysis_calls.append(market)
            return {"market": market, "formatted_text": f"HASIL_{market}_#{len(analysis_calls)}"}

        state_mgr = NavigationStateManager(callback_ttl_seconds=3600)
        controller = ZoneHunterTelegramBot(analyzer_fn=fake_analyzer, state_manager=state_mgr)
        transport = FakeBotTransport()
        ctx = SimpleNamespace(bot=transport)

        # User 1 pilih XAUUSD
        u1_sel, q1 = _make_update(build_callback("mkt", "XAUUSD"), chat_id=100, user_id=1)
        await controller.on_callback_query(u1_sel, ctx)
        assert len(q1.answered) == 1
        assert len(transport.sent_messages) == 1
        assert transport.sent_messages[0]["text"] == "HASIL_XAUUSD_#1"

        # User 1 tekan Refresh -> pesan baru, pesan #1 tetap utuh (immutable)
        u1_ref, q2 = _make_update(build_callback("ref", "XAUUSD"), chat_id=100, user_id=1)
        await controller.on_callback_query(u1_ref, ctx)
        assert len(transport.sent_messages) == 2
        assert transport.sent_messages[0]["text"] == "HASIL_XAUUSD_#1"
        assert transport.sent_messages[1]["text"] == "HASIL_XAUUSD_#2"
        assert len(transport.edited_messages) == 0
        assert len(transport.deleted_messages) == 0

        # User 1 tekan Ganti Market
        u1_chg, _ = _make_update(build_callback("chg"), chat_id=100, user_id=1)
        await controller.on_callback_query(u1_chg, ctx)
        assert len(transport.sent_messages) == 3

        # User 1 tekan Kembali -> kembali ke analisis XAUUSD sebelumnya
        u1_back, _ = _make_update(build_callback("back"), chat_id=100, user_id=1)
        await controller.on_callback_query(u1_back, ctx)
        assert len(transport.sent_messages) == 4
        assert "HASIL_XAUUSD" in transport.sent_messages[3]["text"]

        # User 1 tekan Menu Utama
        u1_home, _ = _make_update(build_callback("home"), chat_id=100, user_id=1)
        await controller.on_callback_query(u1_home, ctx)
        assert state_mgr.get_state(100, 1).current_screen == "MAIN_MENU"

        # Isolasi state antar pengguna (User 2 independen dari User 1)
        u2_sel, _ = _make_update(build_callback("mkt", "BTCUSD"), chat_id=100, user_id=2)
        await controller.on_callback_query(u2_sel, ctx)
        assert state_mgr.get_state(100, 2).selected_market == "BTCUSD"
        assert state_mgr.get_state(100, 1).selected_market is None

        # Simulasi callback ganda saat lock aktif
        assert state_mgr.acquire_lock(100, 1) is True
        u1_dup, q_dup = _make_update(build_callback("mkt", "XAUUSD"), chat_id=100, user_id=1)
        await controller.on_callback_query(u1_dup, ctx)
        assert len(q_dup.answered) == 1
        state_mgr.release_lock(100, 1)

    asyncio.run(_run())
