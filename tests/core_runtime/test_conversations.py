"""Tests for core conversation facade helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from penguin.core import PenguinCore
from penguin.core_runtime import conversations
from penguin.system.state import MessageCategory


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


def test_resolve_conversation_manager_prefers_engine_scoped_manager() -> None:
    default_manager = SimpleNamespace(name="default")
    scoped_manager = SimpleNamespace(name="planner")
    engine = SimpleNamespace(
        get_conversation_manager=Mock(return_value=scoped_manager),
    )
    owner = SimpleNamespace(conversation_manager=default_manager, engine=engine)
    log = Mock()

    resolved = conversations.resolve_conversation_manager(
        owner,
        "planner",
        log=log,
    )

    assert resolved is scoped_manager
    engine.get_conversation_manager.assert_called_once_with("planner")
    log.warning.assert_not_called()


def test_resolve_conversation_manager_keeps_default_when_engine_returns_none() -> None:
    default_manager = SimpleNamespace(name="default")
    engine = SimpleNamespace(get_conversation_manager=Mock(return_value=None))
    owner = SimpleNamespace(conversation_manager=default_manager, engine=engine)

    resolved = conversations.resolve_conversation_manager(
        owner,
        "planner",
        log=Mock(),
    )

    assert resolved is default_manager


def test_resolve_conversation_manager_logs_engine_lookup_failures() -> None:
    default_manager = SimpleNamespace(name="default")
    engine = SimpleNamespace(
        get_conversation_manager=Mock(side_effect=RuntimeError("boom")),
    )
    owner = SimpleNamespace(conversation_manager=default_manager, engine=engine)
    log = Mock()

    resolved = conversations.resolve_conversation_manager(
        owner,
        "planner",
        log=log,
    )

    assert resolved is default_manager
    log.warning.assert_called_once()
    assert "Engine conversation manager lookup failed" in log.warning.call_args.args[0]


def test_resolve_conversation_manager_activates_legacy_agent_without_engine() -> None:
    manager = SimpleNamespace(set_current_agent=Mock())
    owner = SimpleNamespace(conversation_manager=manager, engine=None)

    resolved = conversations.resolve_conversation_manager(
        owner,
        "planner",
        log=Mock(),
    )

    assert resolved is manager
    manager.set_current_agent.assert_called_once_with("planner")


def test_resolve_conversation_manager_logs_legacy_activation_failure() -> None:
    def _raise(_agent_id: str) -> None:
        raise RuntimeError("cannot switch")

    manager = SimpleNamespace(set_current_agent=_raise)
    owner = SimpleNamespace(conversation_manager=manager, engine=None)
    log = Mock()

    resolved = conversations.resolve_conversation_manager(
        owner,
        "planner",
        log=log,
    )

    assert resolved is manager
    log.warning.assert_called_once()
    assert "Failed to activate agent" in log.warning.call_args.args[0]


def test_load_process_conversation_prefers_scoped_conversation() -> None:
    scoped_conversation = SimpleNamespace(
        session=SimpleNamespace(id="session_after_load"),
        load=Mock(return_value=True),
    )
    manager = SimpleNamespace(
        conversation=scoped_conversation,
        load=Mock(return_value=False),
    )

    result = conversations.load_process_conversation(
        manager,
        "conv_1",
        log=Mock(),
    )

    assert result == conversations.ConversationLoadResult(
        via="conversation",
        ok=True,
        scoped_session_id="session_after_load",
    )
    scoped_conversation.load.assert_called_once_with("conv_1")
    manager.load.assert_not_called()


def test_load_process_conversation_falls_back_to_manager_and_logs_failure() -> None:
    manager = SimpleNamespace(load=Mock(return_value=False))
    log = Mock()

    result = conversations.load_process_conversation(
        manager,
        "missing",
        log=log,
    )

    assert result == conversations.ConversationLoadResult(
        via="manager",
        ok=False,
        scoped_session_id=None,
    )
    manager.load.assert_called_once_with("missing")
    log.warning.assert_called_once_with("Failed to load conversation %s", "missing")


def test_load_process_context_files_prefers_scoped_conversation() -> None:
    scoped_conversation = SimpleNamespace(load_context_file=Mock())
    manager = SimpleNamespace(
        conversation=scoped_conversation,
        load_context_file=Mock(),
    )

    count = conversations.load_process_context_files(
        manager,
        ["notes.md", "plan.md"],
    )

    assert count == 2
    assert [
        call.args[0] for call in scoped_conversation.load_context_file.call_args_list
    ] == ["notes.md", "plan.md"]
    manager.load_context_file.assert_not_called()


def test_load_process_context_files_falls_back_to_manager_and_skips_empty() -> None:
    manager = SimpleNamespace(load_context_file=Mock())

    assert conversations.load_process_context_files(manager, None) == 0
    assert conversations.load_process_context_files(manager, []) == 0

    count = conversations.load_process_context_files(
        manager,
        ["notes.md"],
    )

    assert count == 1
    manager.load_context_file.assert_called_once_with("notes.md")


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


def test_session_payload_hides_private_runtime_messages() -> None:
    """Conversation reads do not expose category or metadata-private messages."""

    session = SimpleNamespace(
        id="conv_private",
        messages=[
            SimpleNamespace(
                role="system",
                content="internal category",
                timestamp="2026-05-25T00:00:00",
                agent_id="default",
                recipient_id=None,
                message_type="message",
                category=MessageCategory.INTERNAL,
                metadata={},
            ),
            SimpleNamespace(
                role="system",
                content="metadata private",
                timestamp="2026-05-25T00:00:01",
                agent_id="default",
                recipient_id=None,
                message_type="message",
                category=MessageCategory.SYSTEM,
                metadata={"visibility": "internal"},
            ),
            SimpleNamespace(
                role="user",
                content="visible",
                timestamp="2026-05-25T00:00:02",
                agent_id="default",
                recipient_id=None,
                message_type="message",
                category=MessageCategory.DIALOG,
                metadata={},
            ),
        ],
        created_at="created",
        last_active="active",
        metadata={},
    )

    payload = conversations.session_payload(session)

    assert [message["content"] for message in payload["messages"]] == ["visible"]


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
