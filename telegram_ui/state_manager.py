from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class UserNavigationState:
    user_id: int
    chat_id: int
    current_screen: str = "MAIN_MENU"  # "MAIN_MENU", "CHANGE_MARKET", "ANALYSIS"
    selected_market: Optional[str] = None
    selected_mode: str = "mtf"  # "mtf" (H4->H1->M5) or "scp" (H1->M5)
    history_stack: List[Tuple[str, Optional[str], str]] = field(default_factory=list)
    is_processing: bool = False
    last_updated_ts: float = field(default_factory=time.time)


class NavigationStateManager:
    """Menyimpan state navigasi + mode per (chat_id, user_id), history stack, dan lock anti-callback ganda."""

    def __init__(self, callback_ttl_seconds: int = 3600) -> None:
        self.callback_ttl_seconds = callback_ttl_seconds
        self._states: Dict[Tuple[int, int], UserNavigationState] = {}

    def get_state(self, chat_id: int, user_id: int) -> UserNavigationState:
        key = (int(chat_id), int(user_id))
        state = self._states.get(key)
        if state is None:
            state = UserNavigationState(user_id=int(user_id), chat_id=int(chat_id))
            self._states[key] = state
        return state

    def is_callback_expired(self, callback_ts: Optional[int], now_ts: Optional[float] = None) -> bool:
        if callback_ts is None:
            return False
        current = now_ts if now_ts is not None else time.time()
        return (current - float(callback_ts)) > self.callback_ttl_seconds

    def acquire_lock(self, chat_id: int, user_id: int) -> bool:
        state = self.get_state(chat_id, user_id)
        if state.is_processing:
            return False
        state.is_processing = True
        state.last_updated_ts = time.time()
        return True

    def release_lock(self, chat_id: int, user_id: int) -> None:
        state = self.get_state(chat_id, user_id)
        state.is_processing = False
        state.last_updated_ts = time.time()

    def navigate_to(
        self,
        chat_id: int,
        user_id: int,
        screen: str,
        market: Optional[str] = None,
        mode: str = "mtf",
    ) -> UserNavigationState:
        state = self.get_state(chat_id, user_id)
        m = "scp" if mode == "scp" else "mtf"
        if state.current_screen != screen or state.selected_market != market or state.selected_mode != m:
            state.history_stack.append((state.current_screen, state.selected_market, state.selected_mode))
        state.current_screen = screen
        state.selected_market = market
        state.selected_mode = m
        state.last_updated_ts = time.time()
        return state

    def go_back(self, chat_id: int, user_id: int) -> Tuple[str, Optional[str], str]:
        state = self.get_state(chat_id, user_id)
        if state.history_stack:
            prev_screen, prev_market, prev_mode = state.history_stack.pop()
            state.current_screen = prev_screen
            state.selected_market = prev_market
            state.selected_mode = prev_mode
        else:
            state.current_screen = "MAIN_MENU"
            state.selected_market = None
            state.selected_mode = "mtf"
        state.last_updated_ts = time.time()
        return (state.current_screen, state.selected_market, state.selected_mode)

    def reset_home(self, chat_id: int, user_id: int) -> UserNavigationState:
        state = self.get_state(chat_id, user_id)
        state.history_stack.clear()
        state.current_screen = "MAIN_MENU"
        state.selected_market = None
        state.selected_mode = "mtf"
        state.last_updated_ts = time.time()
        return state
