# server/history.py
# -*- coding: utf-8 -*-
"""
Менеджер истории диалога — по образцу utils/history_manager.py из референсного проекта,
но здесь хранится отдельная история на каждую яхту.
"""
from typing import Dict, List, Optional


class HistoryManager:
    """Хранит последние N сообщений (user/assistant) для одной яхты."""

    def __init__(self, max_history_length: int):
        self.max_history_length = max(1, int(max_history_length))
        self.messages: List[Dict[str, str]] = []

    def add_message(self, role: str, content: str) -> None:
        if role not in ("user", "assistant"):
            return
        if not isinstance(content, str) or not content.strip():
            return
        self.messages.append({"role": role, "content": content.strip()})
        self._truncate()

    def _truncate(self) -> None:
        while len(self.messages) > self.max_history_length:
            self.messages.pop(0)

    def set_max_history_length(self, n: int) -> None:
        self.max_history_length = max(1, int(n))
        self._truncate()

    def get_messages(self, system_prompt: Optional[str] = None) -> List[Dict[str, str]]:
        result: List[Dict[str, str]] = []
        if system_prompt and system_prompt.strip():
            result.append({"role": "system", "content": system_prompt.strip()})
        result.extend(self.messages)
        return result

    def clear(self) -> None:
        self.messages = []


class ConversationStore:
    """Держит по одному HistoryManager на каждую яхту."""

    def __init__(self, yacht_ids: List[str], max_history_length: int):
        self._histories: Dict[str, HistoryManager] = {
            yacht_id: HistoryManager(max_history_length) for yacht_id in yacht_ids
        }

    def get(self, yacht_id: str) -> HistoryManager:
        if yacht_id not in self._histories:
            raise KeyError(f"Неизвестная яхта: {yacht_id}")
        return self._histories[yacht_id]

    def clear(self, yacht_id: str) -> None:
        self.get(yacht_id).clear()

    def clear_all(self) -> None:
        for history in self._histories.values():
            history.clear()

    def set_max_history_length(self, n: int) -> None:
        for history in self._histories.values():
            history.set_max_history_length(n)
