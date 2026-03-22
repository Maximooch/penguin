"""Tests for ActionExecutor todo actions."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.system.state import Session
from penguin.utils.parser import ActionExecutor


class _Manager:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.modified: list[str] = []
        self.saved: list[str] = []

    def load_session(self, session_id: str) -> Session | None:
        if session_id != self._session.id:
            return None
        return self._session

    def mark_session_modified(self, session_id: str) -> None:
        self.modified.append(session_id)

    def save_session(self, session: Session) -> bool:
        self.saved.append(session.id)
        return True


@pytest.mark.asyncio
async def test_todowrite_persists_session_todos_and_emits_event(tmp_path: Path) -> None:
    session = Session(id="session_todo_executor")
    manager = _Manager(session)
    conversation = SimpleNamespace(
        session_manager=manager,
        get_current_session=lambda: session,
    )
    events: list[tuple[str, dict[str, Any]]] = []

    async def _emit(event_type: str, data: dict[str, Any]) -> None:
        events.append((event_type, data))

    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
        conversation_system=conversation,
        ui_event_callback=_emit,
    )

    payload = {
        "todos": [
            {
                "id": "todo_1",
                "content": "Implement session.todo endpoint",
                "status": "in_progress",
                "priority": "high",
            },
            {
                "id": "todo_2",
                "content": "Emit todo.updated events",
                "status": "pending",
                "priority": "medium",
            },
        ]
    }

    with execution_context_scope(
        ExecutionContext(
            session_id=session.id,
            conversation_id=session.id,
            directory=str(tmp_path),
        )
    ):
        result = await executor._todo_write(json.dumps(payload))

    persisted = session.metadata.get("_opencode_todo_v1")
    assert isinstance(persisted, list)
    assert persisted[0]["content"] == "Implement session.todo endpoint"
    assert manager.modified == [session.id]
    assert manager.saved == [session.id]

    result_payload = json.loads(result)
    assert result_payload[0]["status"] == "in_progress"

    todo_events = [event for event in events if event[0] == "todo.updated"]
    assert todo_events
    assert todo_events[-1][1]["sessionID"] == session.id
    assert todo_events[-1][1]["todos"][1]["id"] == "todo_2"


@pytest.mark.asyncio
async def test_todoread_returns_persisted_todos() -> None:
    session = Session(id="session_todo_read")
    session.metadata["_opencode_todo_v1"] = [
        {
            "id": "todo_1",
            "content": "Read todo list",
            "status": "pending",
            "priority": "medium",
        }
    ]
    manager = _Manager(session)
    conversation = SimpleNamespace(
        session_manager=manager,
        get_current_session=lambda: session,
    )

    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
        conversation_system=conversation,
    )

    with execution_context_scope(
        ExecutionContext(session_id=session.id, conversation_id=session.id)
    ):
        result = executor._todo_read("")

    payload = json.loads(result)
    assert payload[0]["content"] == "Read todo list"
    assert payload[0]["priority"] == "medium"
