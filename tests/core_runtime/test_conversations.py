"""Tests for core conversation facade helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from penguin.core import PenguinCore
from penguin.core_runtime import conversations


class _ConversationManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.session = SimpleNamespace(
            id="conv_1",
            messages=[
                SimpleNamespace(
                    role="user",
                    content="hello",
                    timestamp="2026-05-25T00:00:00",
                    agent_id="default",
                    recipient_id=None,
                    message_type="message",
                    metadata={"source": "test"},
                )
            ],
            created_at="created",
            last_active="active",
            metadata={"title": "Test"},
        )
        self.load_result = True

    def list_conversations(
        self,
        *,
        limit: int,
        offset: int,
        search_term: str | None,
    ) -> list[dict[str, Any]]:
        self.calls.append(("list", (limit, offset, search_term)))
        return [{"id": "conv_1"}]

    def load(self, conversation_id: str) -> bool:
        self.calls.append(("load", conversation_id))
        return self.load_result

    def get_current_session(self) -> Any:
        self.calls.append(("current", None))
        return self.session

    def get_conversation_history(
        self,
        conversation_id: str,
        *,
        include_system: bool,
        limit: int | None,
    ) -> list[dict[str, Any]]:
        self.calls.append(("history", (conversation_id, include_system, limit)))
        return [{"role": "user"}]

    def create_new_conversation(self) -> str:
        self.calls.append(("create", None))
        return "conv_new"

    def delete_conversation(self, conversation_id: str) -> bool:
        self.calls.append(("delete", conversation_id))
        return True

    def get_session_stats(self) -> dict[str, Any]:
        self.calls.append(("stats", None))
        return {"total": 1}


def test_list_conversations_forwards_pagination_and_search() -> None:
    manager = _ConversationManager()

    result = conversations.list_conversations(
        manager,
        limit=5,
        offset=10,
        search_term="build",
    )

    assert result == [{"id": "conv_1"}]
    assert manager.calls == [("list", (5, 10, "build"))]


def test_get_conversation_loads_and_serializes_current_session() -> None:
    manager = _ConversationManager()

    payload = conversations.get_conversation(manager, "conv_1")

    assert payload == {
        "id": "conv_1",
        "messages": [
            {
                "role": "user",
                "content": "hello",
                "timestamp": "2026-05-25T00:00:00",
                "agent_id": "default",
                "recipient_id": None,
                "message_type": "message",
                "metadata": {"source": "test"},
            }
        ],
        "created_at": "created",
        "last_active": "active",
        "metadata": {"title": "Test"},
    }
    assert manager.calls == [("load", "conv_1"), ("current", None)]


def test_get_conversation_returns_none_when_load_fails() -> None:
    manager = _ConversationManager()
    manager.load_result = False

    assert conversations.get_conversation(manager, "missing") is None
    assert manager.calls == [("load", "missing")]


def test_history_create_delete_and_stats_forward_to_manager() -> None:
    manager = _ConversationManager()

    assert conversations.get_conversation_history(
        manager,
        "conv_1",
        include_system=False,
        limit=3,
    ) == [{"role": "user"}]
    assert conversations.create_conversation(manager) == "conv_new"
    assert conversations.delete_conversation(manager, "conv_1") is True
    assert conversations.get_conversation_stats(manager) == {"total": 1}
    assert manager.calls == [
        ("history", ("conv_1", False, 3)),
        ("create", None),
        ("delete", "conv_1"),
        ("stats", None),
    ]


def test_core_conversation_shims_delegate_to_runtime() -> None:
    manager = _ConversationManager()
    core = PenguinCore.__new__(PenguinCore)
    core.conversation_manager = manager

    assert core.list_conversations(limit=1, offset=2, search_term="x") == [
        {"id": "conv_1"}
    ]
    assert core.get_conversation("conv_1")["id"] == "conv_1"
    assert core.get_conversation_history(
        "conv_1",
        include_system=False,
        limit=2,
    ) == [{"role": "user"}]
    assert core.create_conversation() == "conv_new"
    assert core.delete_conversation("conv_1") is True
    assert core.get_conversation_stats() == {"total": 1}
