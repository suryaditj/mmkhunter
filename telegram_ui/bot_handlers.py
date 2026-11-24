from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes

from telegram_ui.callbacks import parse_callback
from telegram_ui.keyboards import build_analysis_result_keyboard, build_main_menu_keyboard
from telegram_ui.state_manager import NavigationStateManager


class ZoneHunterTelegramBot:
    """
    Controller Telegram Inline Keyboard & Navigation System untuk ZONE HUNTER ENGINE.
    Mendukung mode MTF (H4 -> H1 -> M5) dan Scalping (H1 -> M5).
    """

    MAIN_MENU_TEXT = (
        "🎯 *ZONE HUNTER ENGINE*\n"
        "• *MTF*: `H4 → H1 → M5`\n"
        "• *Scalping*: `H1 → M5`\n\n"
        "Silakan pilih market / mode:"
    )

    CHANGE_MARKET_TEXT = (
        "🔀 *GANTI MARKET / MODE*\n"
        "Pilih market atau mode scalping (H1 → M5):"
    )

    def __init__(
        self,
        analyzer_fn: Callable[..., Dict[str, Any]],
        state_manager: Optional[NavigationStateManager] = None,
    ) -> None:
        self.analyzer_fn = analyzer_fn
        self.state_manager = state_manager or NavigationStateManager()

    async def _run_analyzer(self, market: str, mode: str = "mtf") -> Dict[str, Any]:
        sig = inspect.signature(self.analyzer_fn)
        accepts_mode = "mode" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        )
        if inspect.iscoroutinefunction(self.analyzer_fn):
            return await self.analyzer_fn(market, mode=mode) if accepts_mode else await self.analyzer_fn(market)
        loop = asyncio.get_running_loop()
        if accepts_mode:
            return await loop.run_in_executor(None, lambda: self.analyzer_fn(market, mode=mode))
        return await loop.run_in_executor(None, self.analyzer_fn, market)

    async def handle_main_menu(
        self,
        chat_id: int,
        user_id: int,
        send_fn: Callable[..., Any],
    ) -> Any:
        self.state_manager.reset_home(chat_id, user_id)
        return await send_fn(
            text=self.MAIN_MENU_TEXT,
            reply_markup=build_main_menu_keyboard(),
            parse_mode="Markdown",
        )

    async def handle_change_market(
        self,
        chat_id: int,
        user_id: int,
        send_fn: Callable[..., Any],
        mode: str = "mtf",
    ) -> Any:
        self.state_manager.navigate_to(chat_id, user_id, screen="CHANGE_MARKET", market=None, mode=mode)
        return await send_fn(
            text=self.CHANGE_MARKET_TEXT,
            reply_markup=build_main_menu_keyboard(),
            parse_mode="Markdown",
        )

    async def handle_analysis(
        self,
        chat_id: int,
        user_id: int,
        market: str,
        send_fn: Callable[..., Any],
        is_refresh: bool = False,
        mode: str = "mtf",
    ) -> Any:
        mkt = market.upper()
        m = "scp" if mode == "scp" else "mtf"
        if not is_refresh:
            self.state_manager.navigate_to(chat_id, user_id, screen="ANALYSIS", market=mkt, mode=m)
        else:
            state = self.state_manager.get_state(chat_id, user_id)
            state.current_screen = "ANALYSIS"
            state.selected_market = mkt
            state.selected_mode = m

        result = await self._run_analyzer(mkt, mode=m)
        text = result.get("formatted_text") or f"ZONE HUNTER ENGINE — {mkt} ({m.upper()})"

        return await send_fn(
            text=text,
            reply_markup=build_analysis_result_keyboard(mkt, mode=m),
        )

    async def handle_market_selection(
        self,
        chat_id: int,
        user_id: int,
        market: str,
        send_fn: Callable[..., Any],
        mode: str = "mtf",
    ) -> Any:
        return await self.handle_analysis(chat_id, user_id, market, send_fn, is_refresh=False, mode=mode)

    async def handle_refresh(
        self,
        chat_id: int,
        user_id: int,
        market: str,
        send_fn: Callable[..., Any],
        mode: str = "mtf",
    ) -> Any:
        return await self.handle_analysis(chat_id, user_id, market, send_fn, is_refresh=True, mode=mode)

    async def handle_back_navigation(
        self,
        chat_id: int,
        user_id: int,
        send_fn: Callable[..., Any],
    ) -> Any:
        prev_screen, prev_market, prev_mode = self.state_manager.go_back(chat_id, user_id)
        if prev_screen == "ANALYSIS" and prev_market in ("XAUUSD", "BTCUSD"):
            result = await self._run_analyzer(prev_market, mode=prev_mode)
            text = result.get("formatted_text") or f"ZONE HUNTER ENGINE — {prev_market} ({prev_mode.upper()})"
            return await send_fn(
                text=text,
                reply_markup=build_analysis_result_keyboard(prev_market, mode=prev_mode),
            )
        if prev_screen == "CHANGE_MARKET":
            return await send_fn(
                text=self.CHANGE_MARKET_TEXT,
                reply_markup=build_main_menu_keyboard(),
                parse_mode="Markdown",
            )
        return await send_fn(
            text=self.MAIN_MENU_TEXT,
            reply_markup=build_main_menu_keyboard(),
            parse_mode="Markdown",
        )

    async def handle_main_menu_navigation(
        self,
        chat_id: int,
        user_id: int,
        send_fn: Callable[..., Any],
    ) -> Any:
        return await self.handle_main_menu(chat_id, user_id, send_fn)

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_chat or not update.effective_user or not update.message:
            return
        await self.handle_main_menu(
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            send_fn=update.message.reply_text,
        )

    async def main_menu_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await self.start_command(update, context)

    async def on_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query is None or update.effective_chat is None or update.effective_user is None:
            return

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id

        if query.message and query.message.chat and query.message.chat.id != chat_id:
            await query.answer("Sesi chat tidak cocok.", show_alert=True)
            return

        action, market, cb_ts, mode = parse_callback(query.data or "")
        if action == "invalid":
            await query.answer("Tombol tidak valid.", show_alert=True)
            return

        if self.state_manager.is_callback_expired(cb_ts):
            await query.answer("Tombol sudah kedaluwarsa. Silakan buka /menu.", show_alert=True)
            return

        if not self.state_manager.acquire_lock(chat_id, user_id):
            await query.answer("Analisis sedang berjalan, harap tunggu...", show_alert=False)
            return

        await query.answer()
        try:
            async def send_new_message(**kwargs: Any) -> Any:
                return await context.bot.send_message(chat_id=chat_id, **kwargs)

            if action == "mkt" and market:
                await self.handle_market_selection(chat_id, user_id, market, send_new_message, mode=mode)
            elif action == "ref" and market:
                await self.handle_refresh(chat_id, user_id, market, send_new_message, mode=mode)
            elif action == "chg":
                await self.handle_change_market(chat_id, user_id, send_new_message, mode=mode)
            elif action == "back":
                await self.handle_back_navigation(chat_id, user_id, send_new_message)
            elif action == "home":
                await self.handle_main_menu_navigation(chat_id, user_id, send_new_message)
        finally:
            self.state_manager.release_lock(chat_id, user_id)
