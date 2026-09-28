"""Native ToolManager todo tool tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.system.state import Session
from penguin.tools.tool_manager import ToolManager


class _SessionManager:
    def __init__(self, session: Session) -> None:
        self.sessions = {session.id: (session, 0.0)}
        self.session_index: dict[str, Any] = {}
        self.modified: list[str] = []
        self.saved: list[str] = []

    def mark_session_modified(self, session_id: str) -> None:
        self.modified.append(session_id)

    def save_session(self, session: Session) -> bool:
        self.saved.append(session.id)
        return True


def _tool_manager(
    session: Session,
    events: list[tuple[str, dict[str, Any]]],
) -> ToolManager:
    session_manager = _SessionManager(session)

    async def emit_ui_event(event_type: str, data: dict[str, Any]) -> None:
        events.append((event_type, data))

    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=session_manager,
            agent_session_managers={},
        ),
        emit_ui_event=emit_ui_event,
    )
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)
    manager._permission_enabled = False
    manager.set_core(core)
    return manager


def test_todo_tools_are_exposed_to_native_providers() -> None:
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)

    schemas = manager.get_responses_tools(include_web_search=False)
    by_name = {schema["name"]: schema for schema in schemas}

    assert {"todowrite", "todoread"} <= by_name.keys()
    assert by_name["todowrite"]["parameters"]["required"] == ["todos"]
    assert by_name["todoread"]["parameters"]["required"] == []


def test_todo_tools_round_trip_through_tool_manager() -> None:
    session = Session(id="session_native_todo")
    events: list[tuple[str, dict[str, Any]]] = []
    manager = _tool_manager(session, events)
    context = ExecutionContext(session_id=session.id, conversation_id=session.id)
    todos = [
        {
            "id": "todo_1",
            "content": "Expose native todo tools",
            "status": "in_progress",
            "priority": "high",
        }
    ]

    with execution_context_scope(context):
        write_result = manager.execute_tool("todowrite", {"todos": todos})
        read_result = manager.execute_tool("todoread", {})

    assert json.loads(write_result) == todos
    assert json.loads(read_result) == todos
    assert session.metadata["_opencode_todo_v1"] == todos
    assert events == [
        (
            "todo.updated",
            {
                "sessionID": session.id,
                "session_id": session.id,
                "conversation_id": session.id,
                "todos": todos,
            },
        )
    ]
