"""Tests for OpenCode action and event bridge helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import action_events


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


def _owner() -> SimpleNamespace:
    return SimpleNamespace(
        event_bus=_EventBus(),
        _normalize_todo_items=lambda value: [
            {
                "id": str(item.get("id", "todo_1")),
                "content": str(item.get("content", "")),
                "status": str(item.get("status", "pending")),
                "priority": str(item.get("priority", "medium")),
            }
            for item in value
            if isinstance(item, dict)
        ],
    )


@pytest.mark.asyncio
async def test_handle_tui_todo_updated_persists_and_emits_scoped_event() -> None:
    owner = _owner()
    persist_calls: list[tuple[str, list[dict[str, str]]]] = []
    persisted_todos = [
        {
            "id": "todo_persisted",
            "content": "Persisted todo",
            "status": "completed",
            "priority": "high",
        }
    ]

    def _update_session_todo(
        _owner: Any,
        session_id: str,
        todos: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        persist_calls.append((session_id, todos))
        return persisted_todos

    await action_events.handle_tui_todo_updated(
        owner,
        "todo.updated",
        {
            "todos": [
                {
                    "id": "todo_1",
                    "content": "Implement bridge parity",
                    "status": "in_progress",
                    "priority": "medium",
                }
            ]
        },
        execution_context=SimpleNamespace(
            session_id="session_1",
            conversation_id=None,
            directory="/tmp/project",
        ),
        update_session_todo=_update_session_todo,
    )

    assert persist_calls == [
        (
            "session_1",
            [
                {
                    "id": "todo_1",
                    "content": "Implement bridge parity",
                    "status": "in_progress",
                    "priority": "medium",
                }
            ],
        )
    ]
    assert owner.event_bus.events == [
        (
            "opencode_event",
            {
                "type": "todo.updated",
                "properties": {
                    "todos": persisted_todos,
                    "sessionID": "session_1",
                    "conversation_id": "session_1",
                    "directory": "/tmp/project",
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_handle_tui_todo_updated_requires_session() -> None:
    owner = _owner()

    await action_events.handle_tui_todo_updated(
        owner,
        "todo.updated",
        {"todos": []},
    )

    assert owner.event_bus.events == []


@pytest.mark.asyncio
async def test_handle_tui_lsp_events_emit_scoped_opencode_events() -> None:
    owner = _owner()
    context = SimpleNamespace(
        session_id="session_1",
        conversation_id=None,
        directory="/tmp/project",
    )

    await action_events.handle_tui_lsp_updated(
        owner,
        "lsp.updated",
        {"files": ["src/a.py"]},
        execution_context=context,
    )
    await action_events.handle_tui_lsp_diagnostics(
        owner,
        "lsp.client.diagnostics",
        {"diagnostics": [{"path": "src/a.py", "severity": "error"}]},
        execution_context=context,
    )

    assert owner.event_bus.events == [
        (
            "opencode_event",
            {
                "type": "lsp.updated",
                "properties": {
                    "files": ["src/a.py"],
                    "sessionID": "session_1",
                    "conversation_id": "session_1",
                    "directory": "/tmp/project",
                },
            },
        ),
        (
            "opencode_event",
            {
                "type": "lsp.client.diagnostics",
                "properties": {
                    "diagnostics": [{"path": "src/a.py", "severity": "error"}],
                    "sessionID": "session_1",
                    "conversation_id": "session_1",
                    "directory": "/tmp/project",
                },
            },
        ),
    ]


@pytest.mark.asyncio
async def test_handle_tui_lsp_events_ignore_mismatched_event_types() -> None:
    owner = _owner()

    await action_events.handle_tui_lsp_updated(owner, "other", {})
    await action_events.handle_tui_lsp_diagnostics(owner, "other", {})

    assert owner.event_bus.events == []
