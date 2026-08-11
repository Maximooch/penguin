"""Session-scoped todo tools."""

from __future__ import annotations

import inspect
import json
from typing import Any, Callable

__all__ = ["TodoTools", "get_todo_tool_schemas"]


def get_todo_tool_schemas() -> list[dict[str, Any]]:
    """Return model-visible schemas for session todo tools."""
    return [
        {
            "name": "todowrite",
            "description": "Create or replace the active session's todo list.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": [
                                        "pending",
                                        "in_progress",
                                        "completed",
                                        "cancelled",
                                    ],
                                },
                                "priority": {
                                    "type": "string",
                                    "enum": ["high", "medium", "low"],
                                },
                            },
                            "required": [
                                "id",
                                "content",
                                "status",
                                "priority",
                            ],
                        },
                    }
                },
                "required": ["todos"],
            },
            "x-penguin-permissions": {
                "mutates_state": True,
                "requires_approval": False,
                "parallel_safe": False,
                "risk": "low",
            },
        },
        {
            "name": "todoread",
            "description": "Read the active session's todo list.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "x-penguin-permissions": {
                "mutates_state": False,
                "requires_approval": False,
                "parallel_safe": True,
                "risk": "low",
            },
        },
    ]


class TodoTools:
    """Read and replace the active session's todo list."""

    def __init__(self, core_getter: Callable[[], Any]) -> None:
        self._core_getter = core_getter

    def read(self, context: dict[str, Any]) -> str:
        """Return normalized todos for the active session."""
        resolved = self._resolve_session(context)
        if resolved is None:
            return self._error("Unable to resolve session for todoread")

        core, session_id = resolved
        from penguin.web.services.session_view import get_session_todo

        todos = get_session_todo(core, session_id)
        if todos is None:
            return self._error("Unable to resolve session for todoread")
        return json.dumps(todos, indent=2)

    async def write(self, todos: Any, context: dict[str, Any]) -> str:
        """Replace normalized todos for the active session and emit an update."""
        resolved = self._resolve_session(context)
        if resolved is None:
            return self._error("Unable to resolve session for todowrite")

        core, session_id = resolved
        from penguin.web.services.session_view import update_session_todo

        normalized = update_session_todo(core, session_id, todos)
        if normalized is None:
            return self._error("Unable to resolve session for todowrite")

        emit = getattr(core, "emit_ui_event", None)
        if callable(emit):
            result = emit(
                "todo.updated",
                {
                    "sessionID": session_id,
                    "session_id": session_id,
                    "conversation_id": session_id,
                    "todos": normalized,
                },
            )
            if inspect.isawaitable(result):
                await result

        return json.dumps(normalized, indent=2)

    def _resolve_session(self, context: dict[str, Any]) -> tuple[Any, str] | None:
        core = self._core_getter()
        session_id = context.get("session_id") or context.get("conversation_id")
        if core is None or not isinstance(session_id, str) or not session_id:
            return None
        return core, session_id

    @staticmethod
    def _error(message: str) -> str:
        return json.dumps({"error": message})
