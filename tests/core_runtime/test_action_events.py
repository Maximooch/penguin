"""Tests for OpenCode action and event bridge helpers."""

from __future__ import annotations

from pathlib import Path
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
    assert len(owner.event_bus.events) == 1
    event_type, payload = owner.event_bus.events[0]
    assert event_type == "opencode_event"
    assert payload["type"] == "todo.updated"
    assert payload["properties"] == {
        "todos": persisted_todos,
        "sessionID": "session_1",
        "conversation_id": "session_1",
        "directory": str(Path("/tmp/project").resolve()),
    }
    assert payload["runtime_event"]["type"] == "todo.updated"
    assert payload["runtime_event"]["scope"]["session_id"] == "session_1"
    assert payload["runtime_event"]["scope"]["conversation_id"] == "session_1"
    assert payload["runtime_event"]["scope"]["directory"] == str(
        Path("/tmp/project").resolve()
    )


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

    assert [event_type for event_type, _payload in owner.event_bus.events] == [
        "opencode_event",
        "opencode_event",
    ]

    first_payload = owner.event_bus.events[0][1]
    assert first_payload["type"] == "lsp.updated"
    assert first_payload["properties"] == {
        "files": ["src/a.py"],
        "sessionID": "session_1",
        "conversation_id": "session_1",
        "directory": str(Path("/tmp/project").resolve()),
    }
    assert first_payload["runtime_event"]["type"] == "lsp.updated"
    assert first_payload["runtime_event"]["scope"]["session_id"] == "session_1"

    second_payload = owner.event_bus.events[1][1]
    assert second_payload["type"] == "lsp.client.diagnostics"
    assert second_payload["properties"] == {
        "diagnostics": [{"path": "src/a.py", "severity": "error"}],
        "sessionID": "session_1",
        "conversation_id": "session_1",
        "directory": str(Path("/tmp/project").resolve()),
    }
    assert second_payload["runtime_event"]["type"] == "lsp.client.diagnostics"
    assert second_payload["runtime_event"]["scope"]["session_id"] == "session_1"


@pytest.mark.asyncio
async def test_handle_tui_lsp_events_ignore_mismatched_event_types() -> None:
    owner = _owner()

    await action_events.handle_tui_lsp_updated(owner, "other", {})
    await action_events.handle_tui_lsp_diagnostics(owner, "other", {})

    assert owner.event_bus.events == []


@pytest.mark.asyncio
async def test_handle_tui_action_uses_runtime_mapping_without_core_shim() -> None:
    class _Adapter:
        def __init__(self) -> None:
            self.starts: list[dict[str, Any]] = []

        async def on_tool_start(
            self,
            tool_name: str,
            tool_input: dict[str, Any],
            *,
            tool_call_id: str | None = None,
            metadata: dict[str, Any] | None = None,
            message_id: str | None = None,
            agent_id: str = "default",
            model_id: str | None = None,
            provider_id: str | None = None,
            variant: str | None = None,
        ) -> str:
            self.starts.append(
                {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_call_id": tool_call_id,
                    "metadata": metadata or {},
                    "message_id": message_id,
                    "agent_id": agent_id,
                    "model_id": model_id,
                    "provider_id": provider_id,
                    "variant": variant,
                }
            )
            return "part_read"

    adapter = _Adapter()
    owner = SimpleNamespace(
        _get_tui_adapter=lambda _session_id: adapter,
        _resolve_opencode_model_state=lambda session_id: {
            "modelID": f"model:{session_id}",
            "providerID": "openai",
            "variant": "high",
        },
        _opencode_stream_states={"session_read": {"message_id": "msg_1"}},
        _opencode_tool_parts={},
        _opencode_tool_info={},
    )

    await action_events.handle_tui_action(
        owner,
        "action",
        {
            "session_id": "session_read",
            "id": "call_read",
            "action": "read_file",
            "params": '{"path": "README.md", "max_lines": 25}',
            "agent_id": "worker",
        },
    )

    assert adapter.starts == [
        {
            "tool_name": "read",
            "tool_input": {"filePath": "README.md", "limit": 25},
            "tool_call_id": "call_read",
            "metadata": {},
            "message_id": "msg_1",
            "agent_id": "worker",
            "model_id": "model:session_read",
            "provider_id": "openai",
            "variant": "high",
        }
    ]
    assert owner._opencode_tool_parts == {"session_read:call_read": "part_read"}
    assert owner._opencode_tool_info["session_read:call_read"]["tool"] == "read"


@pytest.mark.asyncio
async def test_handle_tui_action_result_uses_runtime_metadata_without_core_shim() -> (
    None
):
    class _Adapter:
        def __init__(self) -> None:
            self.ends: list[dict[str, Any]] = []

        async def on_tool_end(
            self,
            part_id: str,
            output: Any,
            error: Any = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            self.ends.append(
                {
                    "part_id": part_id,
                    "output": output,
                    "error": error,
                    "metadata": metadata or {},
                }
            )

    adapter = _Adapter()
    owner = SimpleNamespace(
        _get_tui_adapter=lambda _session_id: adapter,
        _opencode_tool_parts={"session_edit:call_edit": "part_edit"},
        _opencode_tool_info={
            "session_edit:call_edit": {
                "metadata": {
                    "diff": "--- a/file.txt\n+++ b/file.txt\n@@\n-old\n+new\n"
                },
                "input": {"filePath": "file.txt"},
                "action": "apply_diff",
            }
        },
    )

    await action_events.handle_tui_action_result(
        owner,
        "action_result",
        {
            "session_id": "session_edit",
            "id": "call_edit",
            "status": "completed",
            "result": "Error parsing diff",
            "action": "apply_diff",
        },
    )

    assert adapter.ends == [
        {
            "part_id": "part_edit",
            "output": "Error parsing diff",
            "error": "Error parsing diff",
            "metadata": {
                "attemptedDiff": "--- a/file.txt\n+++ b/file.txt\n@@\n-old\n+new\n"
            },
        }
    ]
    assert owner._opencode_tool_parts == {}
    assert owner._opencode_tool_info == {}


@pytest.mark.asyncio
async def test_handle_tui_action_result_synthesizes_missing_start() -> None:
    class _Adapter:
        def __init__(self) -> None:
            self.starts: list[dict[str, Any]] = []
            self.ends: list[dict[str, Any]] = []

        async def on_tool_start(
            self,
            tool_name: str,
            tool_input: dict[str, Any],
            *,
            tool_call_id: str | None = None,
            metadata: dict[str, Any] | None = None,
            message_id: str | None = None,
            agent_id: str = "default",
            model_id: str | None = None,
            provider_id: str | None = None,
            variant: str | None = None,
        ) -> str:
            self.starts.append(
                {
                    "tool_name": tool_name,
                    "tool_input": tool_input,
                    "tool_call_id": tool_call_id,
                    "metadata": metadata or {},
                    "message_id": message_id,
                    "agent_id": agent_id,
                    "model_id": model_id,
                    "provider_id": provider_id,
                    "variant": variant,
                }
            )
            return "part_synthesized"

        async def on_tool_end(
            self,
            part_id: str,
            output: Any,
            error: Any = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            self.ends.append(
                {
                    "part_id": part_id,
                    "output": output,
                    "error": error,
                    "metadata": metadata or {},
                }
            )

    adapter = _Adapter()
    owner = SimpleNamespace(
        _get_tui_adapter=lambda _session_id: adapter,
        _resolve_opencode_model_state=lambda session_id: {
            "modelID": f"model:{session_id}",
            "providerID": "openai",
            "variant": "low",
        },
        _opencode_stream_states={"session_missing": {"message_id": "msg_1"}},
        _opencode_tool_parts={},
        _opencode_tool_info={},
    )

    await action_events.handle_tui_action_result(
        owner,
        "action_result",
        {
            "session_id": "session_missing",
            "id": "call_missing",
            "action": "read_file",
            "result": "contents",
            "agent_id": "worker",
        },
    )

    assert adapter.starts == [
        {
            "tool_name": "read",
            "tool_input": {"filePath": ""},
            "tool_call_id": "call_missing",
            "metadata": {},
            "message_id": "msg_1",
            "agent_id": "worker",
            "model_id": "model:session_missing",
            "provider_id": "openai",
            "variant": "low",
        }
    ]
    assert adapter.ends == [
        {
            "part_id": "part_synthesized",
            "output": "contents",
            "error": None,
            "metadata": {},
        }
    ]
    assert owner._opencode_tool_parts == {}
    assert owner._opencode_tool_info == {}


@pytest.mark.asyncio
async def test_tool_call_ids_are_scoped_by_session() -> None:
    class _Adapter:
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            self.starts: list[str] = []
            self.ends: list[str] = []

        async def on_tool_start(
            self,
            tool_name: str,
            tool_input: dict[str, Any],
            *,
            tool_call_id: str | None = None,
            **_: Any,
        ) -> str:
            del tool_name, tool_input
            self.starts.append(str(tool_call_id))
            return f"part_{self.session_id}"

        async def on_tool_end(
            self,
            part_id: str,
            output: Any,
            error: Any = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            del output, error, metadata
            self.ends.append(part_id)

    adapters = {
        "session_a": _Adapter("session_a"),
        "session_b": _Adapter("session_b"),
    }
    owner = SimpleNamespace(
        _get_tui_adapter=lambda session_id: adapters[session_id],
        _resolve_opencode_model_state=lambda session_id: {
            "modelID": f"model:{session_id}",
            "providerID": "openai",
            "variant": None,
        },
        _opencode_stream_states={},
        _opencode_tool_parts={},
        _opencode_tool_info={},
    )

    for session_id in ("session_a", "session_b"):
        await action_events.handle_tui_action(
            owner,
            "action",
            {
                "session_id": session_id,
                "id": "call_shared",
                "action": "read_file",
                "params": {"path": f"{session_id}.txt"},
            },
        )

    await action_events.handle_tui_action_result(
        owner,
        "action_result",
        {
            "session_id": "session_a",
            "id": "call_shared",
            "action": "read_file",
            "result": "done",
        },
    )

    assert adapters["session_a"].starts == ["call_shared"]
    assert adapters["session_b"].starts == ["call_shared"]
    assert adapters["session_a"].ends == ["part_session_a"]
    assert adapters["session_b"].ends == []
    assert owner._opencode_tool_parts == {"session_b:call_shared": "part_session_b"}
    assert set(owner._opencode_tool_info) == {"session_b:call_shared"}
