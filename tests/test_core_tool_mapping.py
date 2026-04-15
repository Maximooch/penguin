"""Tests for OpenCode tool mapping and transcript persistence."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core import PenguinCore
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    get_current_execution_context,
)
from penguin.system.state import Session
from penguin.web.services.session_view import (
    TODO_KEY,
    TRANSCRIPT_KEY,
    get_session_messages,
)


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_name: str, payload: dict[str, Any]) -> None:
        self.events.append((event_name, payload))


@pytest.mark.parametrize(
    ("action", "params", "expected_tool", "expected_values"),
    [
        (
            "code_execution",
            {"code": "print(13)"},
            "bash",
            {"command": "print(13)", "description": "IPython"},
        ),
        (
            "insert_lines",
            {"path": "src/main.py", "after_line": 4, "new_content": "print('x')"},
            "edit",
            {"filePath": "src/main.py", "afterLine": 4},
        ),
        (
            "delete_lines",
            {"path": "src/main.py", "start_line": 5, "end_line": 7},
            "edit",
            {"filePath": "src/main.py", "startLine": 5, "endLine": 7},
        ),
        (
            "enhanced_write",
            {"path": "README.md", "content": "hello", "backup": True},
            "write",
            {"filePath": "README.md", "content": "hello", "backup": True},
        ),
        (
            "multiedit",
            {"content": "apply=true\nfile.py:\n@@ -1 +1 @@\n-a\n+b\n", "apply": True},
            "edit",
            {"filePath": "(multiple files)", "apply": True},
        ),
        (
            "workspace_search",
            {"query": "TODO"},
            "grep",
            {"pattern": "TODO", "path": "."},
        ),
        (
            "enhanced_diff",
            {"file1": "src/a.py", "file2": "src/b.py", "semantic": True},
            "read",
            {
                "filePath": "src/a.py",
                "comparePath": "src/b.py",
                "semantic": True,
            },
        ),
        (
            "todowrite",
            {
                "todos": [
                    {
                        "id": "todo_1",
                        "content": "Track todo progress",
                        "status": "pending",
                        "priority": "medium",
                    }
                ]
            },
            "todowrite",
            {
                "todos": [
                    {
                        "id": "todo_1",
                        "content": "Track todo progress",
                        "status": "pending",
                        "priority": "medium",
                    }
                ]
            },
        ),
        (
            "todoread",
            {},
            "todoread",
            {},
        ),
        (
            "question",
            {
                "questions": [
                    {
                        "question": "Which target should I use?",
                        "header": "Target",
                        "options": [
                            {"label": "A", "description": "Use target A"},
                            {"label": "B", "description": "Use target B"},
                        ],
                    }
                ]
            },
            "question",
            {
                "questions": [
                    {
                        "question": "Which target should I use?",
                        "header": "Target",
                        "options": [
                            {"label": "A", "description": "Use target A"},
                            {"label": "B", "description": "Use target B"},
                        ],
                    }
                ]
            },
        ),
    ],
)
def test_map_action_to_tool_covers_common_coding_workflows(
    action: str,
    params: Any,
    expected_tool: str,
    expected_values: dict[str, Any],
) -> None:
    core = PenguinCore.__new__(PenguinCore)

    mapped_tool, tool_input, metadata = core._map_action_to_tool(action, params)

    assert mapped_tool == expected_tool
    assert isinstance(tool_input, dict)
    for key, value in expected_values.items():
        assert tool_input.get(key) == value
    assert isinstance(metadata, dict)


def test_map_action_to_tool_maps_isolated_spawn_sub_agent_to_task_card() -> None:
    core = PenguinCore.__new__(PenguinCore)

    mapped_tool, tool_input, metadata = core._map_action_to_tool(
        "spawn_sub_agent",
        {
            "id": "smoke_agent",
            "share_session": False,
            "initial_prompt": "Smoke test only. List the first 5 top-level items.",
        },
    )

    assert mapped_tool == "task"
    assert tool_input["subagent_type"] == "smoke agent"
    assert tool_input["description"].startswith("Smoke test only.")
    assert metadata["summary"][0]["tool"] == "subagent"
    assert metadata["summary"][0]["state"]["status"] == "running"


def test_map_action_to_tool_keeps_shared_session_spawn_sub_agent_generic() -> None:
    core = PenguinCore.__new__(PenguinCore)

    mapped_tool, tool_input, metadata = core._map_action_to_tool(
        "spawn_sub_agent",
        {
            "id": "shared_agent",
            "share_session": True,
            "initial_prompt": "Use the parent session.",
        },
    )

    assert mapped_tool == "spawn_sub_agent"
    assert tool_input["id"] == "shared_agent"
    assert metadata == {}


def test_map_action_result_metadata_extracts_diff_for_replace_lines() -> None:
    core = PenguinCore.__new__(PenguinCore)
    result = (
        "Replaced lines 2-2 in src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line1\n"
        "-line2\n"
        "+line2_updated\n"
        " line3\n"
    )

    metadata = core._map_action_result_metadata(
        "replace_lines",
        result,
        existing={"source": "test"},
        tool_input={"filePath": "src/main.py"},
    )

    assert metadata["source"] == "test"
    assert metadata["filePath"] == "src/main.py"
    assert metadata["diff"].startswith("--- a/src/main.py")
    assert "+++ b/src/main.py" in metadata["diff"]


def test_map_action_result_metadata_sets_output_for_code_execution() -> None:
    core = PenguinCore.__new__(PenguinCore)

    metadata = core._map_action_result_metadata(
        "code_execution",
        "13\nRESULT=13",
        existing={"source": "test"},
    )

    assert metadata["source"] == "test"
    assert metadata["output"] == "13\nRESULT=13"


@pytest.mark.asyncio
async def test_on_tui_action_passes_model_state_for_tool_only_turns() -> None:
    class _Adapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

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
            self.calls.append(
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
            return "part_tool_1"

    core = PenguinCore.__new__(PenguinCore)
    adapter = _Adapter()
    core.model_config = SimpleNamespace(model="gpt-5.4", provider="openai")
    setattr(core, "_opencode_tool_parts", {})
    setattr(core, "_opencode_tool_info", {})
    setattr(core, "_opencode_stream_states", {})
    setattr(core, "_get_tui_adapter", lambda _session_id: adapter)

    await core._on_tui_action(
        "action",
        {
            "session_id": "session_tool_only",
            "id": "call_tool_1",
            "action": "read_file",
            "params": '{"path": "README.md", "limit": 120}',
        },
    )

    assert adapter.calls
    call = adapter.calls[-1]
    assert call["tool_name"] == "read"
    assert call["tool_call_id"] == "call_tool_1"
    assert call["message_id"] is None
    assert call["model_id"] == "gpt-5.4"
    assert call["provider_id"] == "openai"


@pytest.mark.asyncio
async def test_emit_opencode_user_message_uses_client_message_id_and_model_state() -> (
    None
):
    class _Adapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def on_user_message_with_metadata(
            self,
            content: str,
            *,
            message_id: str | None = None,
            agent_id: str = "default",
            model_id: str | None = None,
            provider_id: str | None = None,
            variant: str | None = None,
        ) -> str:
            self.calls.append(
                {
                    "content": content,
                    "message_id": message_id,
                    "agent_id": agent_id,
                    "model_id": model_id,
                    "provider_id": provider_id,
                    "variant": variant,
                }
            )
            return message_id or "msg_generated"

    core = PenguinCore.__new__(PenguinCore)
    adapter = _Adapter()
    setattr(
        core, "conversation_manager", SimpleNamespace(get_current_session=lambda: None)
    )
    setattr(core, "model_config", SimpleNamespace(model="gpt-5.4", provider="openai"))
    setattr(core, "_get_tui_adapter", lambda _session_id: adapter)
    setattr(
        core,
        "_resolve_opencode_model_state",
        lambda session_id: {
            "modelID": "gpt-5.4",
            "providerID": "openai",
            "variant": "high",
        },
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="session_user_emit",
            conversation_id="session_user_emit",
            agent_id="build",
        )
    ):
        message_id = await core._emit_opencode_user_message_with_metadata(
            "hello",
            message_id="msg_client_1",
            agent_id="build",
        )

    assert message_id == "msg_client_1"
    assert adapter.calls == [
        {
            "content": "hello",
            "message_id": "msg_client_1",
            "agent_id": "build",
            "model_id": "gpt-5.4",
            "provider_id": "openai",
            "variant": "high",
        }
    ]


def test_map_action_result_metadata_extracts_diff_for_edit_with_pattern() -> None:
    core = PenguinCore.__new__(PenguinCore)
    result = (
        "Successfully edited src/main.py:\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-DEBUG = False\n"
        "+DEBUG = True\n"
    )

    metadata = core._map_action_result_metadata(
        "edit_with_pattern",
        result,
        existing=None,
        tool_input={"filePath": "src/main.py"},
    )

    assert metadata["filePath"] == "src/main.py"
    assert metadata["diff"].startswith("--- a/src/main.py")
    assert "+DEBUG = True" in metadata["diff"]


def test_map_action_result_metadata_captures_files_for_multiedit() -> None:
    core = PenguinCore.__new__(PenguinCore)

    metadata = core._map_action_result_metadata(
        "multiedit",
        json.dumps(
            {
                "success": True,
                "files": ["src/a.py", "src/b.py"],
                "files_edited": [
                    "/tmp/workspace/src/a.py",
                    "/tmp/workspace/src/b.py",
                ],
                "applied": True,
            }
        ),
        existing=None,
        tool_input={"filePath": "(multiple files)"},
        status="completed",
    )

    assert metadata["files"] == [
        "src/a.py",
        "src/b.py",
        "/tmp/workspace/src/a.py",
        "/tmp/workspace/src/b.py",
    ]


def test_map_action_to_tool_supports_canonical_patch_file_payload() -> None:
    core = PenguinCore.__new__(PenguinCore)

    mapped_tool, tool_input, metadata = core._map_action_to_tool(
        "patch_file",
        {
            "path": "src/main.py",
            "operation": {
                "type": "replace_lines",
                "start_line": 2,
                "end_line": 2,
                "new_content": "print('hi')",
                "verify": True,
            },
        },
    )

    assert mapped_tool == "edit"
    assert tool_input == {
        "filePath": "src/main.py",
        "startLine": 2,
        "endLine": 2,
        "newContent": "print('hi')",
    }
    assert metadata == {}


def test_map_action_to_tool_supports_canonical_patch_files_payload() -> None:
    core = PenguinCore.__new__(PenguinCore)

    mapped_tool, tool_input, metadata = core._map_action_to_tool(
        "patch_files",
        {
            "apply": True,
            "operations": [
                {
                    "path": "src/a.py",
                    "operation": {
                        "type": "delete_lines",
                        "start_line": 1,
                        "end_line": 1,
                    },
                },
                {
                    "path": "src/b.py",
                    "operation": {
                        "type": "insert_lines",
                        "after_line": 1,
                        "new_content": "x",
                    },
                },
            ],
        },
    )

    assert mapped_tool == "edit"
    assert tool_input == {"filePath": "(multiple files)", "apply": True}
    assert metadata["files"] == ["src/a.py", "src/b.py"]


def test_map_action_result_metadata_extracts_todos_for_todowrite() -> None:
    core = PenguinCore.__new__(PenguinCore)
    result = (
        "[\n"
        "  {\n"
        '    "id": "todo_1",\n'
        '    "content": "Implement todo endpoint",\n'
        '    "status": "pending",\n'
        '    "priority": "high"\n'
        "  }\n"
        "]"
    )

    metadata = core._map_action_result_metadata(
        "todowrite",
        result,
        existing=None,
        tool_input={"todos": []},
    )

    assert metadata["todos"][0]["id"] == "todo_1"
    assert metadata["todos"][0]["content"] == "Implement todo endpoint"


def test_map_action_result_metadata_promotes_spawn_sub_agent_to_clickable_task_card() -> (
    None
):
    core = PenguinCore.__new__(PenguinCore)

    metadata = core._map_action_result_metadata(
        "spawn_sub_agent",
        "Spawned sub-agent 'smoke_agent' running in background",
        existing={
            "summary": [
                {
                    "id": "smoke_agent",
                    "tool": "subagent",
                    "state": {"status": "running"},
                }
            ]
        },
        tool_input={"subagent_type": "smoke agent"},
        status="completed",
        event_metadata={
            "sessionId": "session_child",
            "title": "Smoke Agent Session",
        },
    )

    assert metadata["sessionId"] == "session_child"
    assert metadata["title"] == "Smoke Agent Session"
    assert metadata["summary"][0]["id"] == "session_child"
    assert metadata["summary"][0]["tool"] == "subagent"
    assert metadata["summary"][0]["state"]["status"] == "completed"
    assert metadata["summary"][0]["state"]["title"] == "Smoke Agent Session"


@pytest.mark.asyncio
async def test_run_agent_prompt_in_session_overrides_parent_execution_scope(
    tmp_path,
) -> None:
    parent_dir = tmp_path / "parent"
    child_dir = tmp_path / "child"
    parent_dir.mkdir()
    child_dir.mkdir()

    child_session = SimpleNamespace(
        id="session_child",
        metadata={"directory": str(child_dir), "agent_mode": "build"},
    )
    conversation_manager = SimpleNamespace(
        get_agent_conversation=lambda _agent_id: SimpleNamespace(session=child_session)
    )

    captured: dict[str, Any] = {}

    async def _process(**kwargs: Any) -> dict[str, Any]:
        captured["kwargs"] = kwargs
        captured["context"] = get_current_execution_context()
        return {"assistant_response": "done"}

    core = PenguinCore.__new__(PenguinCore)
    setattr(core, "conversation_manager", conversation_manager)
    setattr(core, "_opencode_session_directories", {"session_child": str(child_dir)})
    setattr(core, "process", AsyncMock(side_effect=_process))

    with execution_context_scope(
        ExecutionContext(
            session_id="session_parent",
            conversation_id="session_parent",
            agent_id="default",
            agent_mode="build",
            directory=str(parent_dir),
            project_root=str(parent_dir),
            workspace_root=str(parent_dir),
        )
    ):
        runner = getattr(core, "run_agent_prompt_in_session")
        result = await runner("child-agent", "Child prompt")

    assert result["assistant_response"] == "done"
    assert captured["kwargs"]["conversation_id"] == "session_child"
    assert captured["kwargs"]["agent_id"] == "child-agent"
    context = captured["context"]
    assert context is not None
    assert context.session_id == "session_child"
    assert context.conversation_id == "session_child"
    assert context.agent_id == "child-agent"
    assert context.directory == str(child_dir)


@pytest.mark.asyncio
async def test_core_created_tui_adapter_suppresses_live_session_status_events() -> None:
    bus = _EventBus()
    core = PenguinCore.__new__(PenguinCore)

    async def _persist(event_type: str, properties: dict[str, Any]) -> None:
        del event_type, properties

    setattr(core, "event_bus", bus)
    setattr(core, "_persist_opencode_event", _persist)
    setattr(core, "_tui_adapters", {})
    setattr(core, "_opencode_session_directories", {})

    adapter = core._get_tui_adapter("session_busy")
    assert getattr(adapter, "_emit_session_status_events") is False

    part_id = await adapter.on_tool_start("bash", {"command": "pwd"})
    await adapter.on_tool_end(part_id, "ok")

    status_events = [
        payload
        for event_type, payload in bus.events
        if event_type == "opencode_event" and payload.get("type") == "session.status"
    ]
    assert status_events == []


def test_map_action_result_metadata_moves_diff_to_attempted_diff_on_error() -> None:
    core = PenguinCore.__new__(PenguinCore)

    metadata = core._map_action_result_metadata(
        "apply_diff",
        "Error applying diff",
        existing={"diff": "--- a/file.txt\n+++ b/file.txt\n@@\n-old\n+new\n"},
        tool_input={"filePath": "file.txt"},
        status="error",
    )

    assert "diff" not in metadata
    assert metadata["attemptedDiff"].startswith("--- a/file.txt")


@pytest.mark.asyncio
async def test_action_result_with_error_text_is_treated_as_error_status() -> None:
    class _Adapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def on_tool_end(
            self,
            part_id: str,
            output: Any,
            error: Any = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            self.calls.append(
                {
                    "part_id": part_id,
                    "output": output,
                    "error": error,
                    "metadata": metadata or {},
                }
            )

    core = PenguinCore.__new__(PenguinCore)
    adapter = _Adapter()
    setattr(core, "_opencode_tool_parts", {"session_1:call_1": "part_1"})
    setattr(
        core,
        "_opencode_tool_info",
        {
            "session_1:call_1": {
                "metadata": {
                    "diff": "--- a/file.txt\n+++ b/file.txt\n@@\n-old\n+new\n"
                },
                "input": {"filePath": "file.txt"},
                "action": "apply_diff",
            }
        },
    )
    setattr(core, "_opencode_stream_states", {})
    setattr(core, "_get_tui_adapter", lambda _session_id: adapter)

    await core._on_tui_action_result(
        "action_result",
        {
            "session_id": "session_1",
            "id": "call_1",
            "status": "completed",
            "result": "Error parsing diff: Unknown line 13 '+- Item one'",
            "action": "apply_diff",
        },
    )

    assert adapter.calls
    recorded = adapter.calls[-1]
    assert recorded["part_id"] == "part_1"
    assert isinstance(recorded["error"], str)
    assert recorded["error"].startswith("Error parsing diff")
    assert "diff" not in recorded["metadata"]
    assert recorded["metadata"]["attemptedDiff"].startswith("--- a/file.txt")


@pytest.mark.asyncio
async def test_action_result_uses_subagent_task_card_metadata() -> None:
    class _Adapter:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def on_tool_end(
            self,
            part_id: str,
            output: Any,
            error: Any = None,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            self.calls.append(
                {
                    "part_id": part_id,
                    "output": output,
                    "error": error,
                    "metadata": metadata or {},
                }
            )

    core = PenguinCore.__new__(PenguinCore)
    adapter = _Adapter()
    setattr(core, "_opencode_tool_parts", {"session_parent:call_task": "part_task"})
    setattr(
        core,
        "_opencode_tool_info",
        {
            "session_parent:call_task": {
                "metadata": {
                    "summary": [
                        {
                            "id": "smoke_agent",
                            "tool": "subagent",
                            "state": {"status": "running"},
                        }
                    ]
                },
                "input": {
                    "description": "Smoke test only.",
                    "subagent_type": "smoke agent",
                },
                "action": "spawn_sub_agent",
            }
        },
    )
    setattr(core, "_opencode_stream_states", {})
    setattr(core, "_get_tui_adapter", lambda _session_id: adapter)

    await core._on_tui_action_result(
        "action_result",
        {
            "session_id": "session_parent",
            "id": "call_task",
            "status": "completed",
            "result": "Spawned sub-agent 'smoke_agent' running in background",
            "action": "spawn_sub_agent",
            "metadata": {
                "sessionId": "session_child",
                "title": "Smoke Agent Session",
            },
        },
    )

    assert adapter.calls
    recorded = adapter.calls[-1]
    assert recorded["part_id"] == "part_task"
    assert recorded["metadata"]["sessionId"] == "session_child"
    assert recorded["metadata"]["summary"][0]["state"]["status"] == "completed"
    assert recorded["metadata"]["summary"][0]["state"]["title"] == "Smoke Agent Session"


@pytest.mark.asyncio
async def test_abort_session_cancels_tasks_aborts_adapter_and_clears_tool_maps():
    class _EventBus:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def emit(self, event_type: str, data: dict[str, Any]) -> None:
            self.events.append((event_type, data))

    class _Adapter:
        def __init__(self) -> None:
            self.reasons: list[str] = []

        async def abort(self, reason: str = "Tool execution was interrupted") -> bool:
            self.reasons.append(reason)
            return True

    class _StreamManager:
        def get_active_agents(self) -> list[str]:
            return []

        def abort(self, agent_id: str | None = None) -> list[Any]:
            _ = agent_id
            return []

    async def _sleep_forever() -> None:
        await asyncio.sleep(60)

    pending_task = asyncio.create_task(_sleep_forever())

    core = PenguinCore.__new__(PenguinCore)
    bus = _EventBus()
    adapter = _Adapter()

    setattr(core, "event_bus", bus)
    setattr(core, "_stream_manager", _StreamManager())
    setattr(core, "emit_ui_event", lambda *_args, **_kwargs: None)
    setattr(core, "_get_tui_adapter", lambda _session_id: adapter)
    setattr(core, "_opencode_abort_sessions", set())
    setattr(core, "_opencode_process_tasks", {"session_abort": {pending_task}})
    setattr(
        core,
        "_opencode_stream_states",
        {
            "session_abort": {
                "active": False,
                "stream_id": "stream_1",
                "message_id": "msg_1",
                "part_id": "part_1",
            }
        },
    )
    setattr(
        core,
        "_opencode_tool_parts",
        {
            "session_abort:call_1": "part_tool",
            "session_other:call_2": "part_other",
        },
    )
    setattr(
        core,
        "_opencode_tool_info",
        {
            "session_abort:call_1": {"tool": "bash"},
            "session_other:call_2": {"tool": "read"},
        },
    )

    aborted = await core.abort_session("session_abort")

    assert aborted is True
    assert adapter.reasons == ["Tool execution was interrupted"]

    with pytest.raises(asyncio.CancelledError):
        await pending_task

    stream_state = core._opencode_stream_states["session_abort"]
    assert stream_state["active"] is False
    assert stream_state["stream_id"] is None
    assert stream_state["part_id"] is None

    assert "session_abort:call_1" not in core._opencode_tool_parts
    assert "session_abort:call_1" not in core._opencode_tool_info
    assert "session_other:call_2" in core._opencode_tool_parts
    assert "session_other:call_2" in core._opencode_tool_info

    status_events = [
        payload
        for event_type, payload in bus.events
        if event_type == "opencode_event" and payload.get("type") == "session.status"
    ]
    assert status_events
    assert status_events[-1]["properties"]["sessionID"] == "session_abort"
    assert status_events[-1]["properties"]["status"]["type"] == "idle"


class _SessionManager:
    def __init__(self, session: Session):
        self.sessions: dict[str, tuple[Session, bool]] = {session.id: (session, False)}
        self.session_index: dict[str, dict[str, Any]] = {
            session.id: {
                "created_at": session.created_at,
                "last_active": session.last_active,
                "title": session.metadata.get("title", ""),
            }
        }
        self._save_calls: int = 0

    def load_session(self, session_id: str) -> Session | None:
        item = self.sessions.get(session_id)
        if item is None:
            return None
        return item[0]

    def mark_session_modified(self, session_id: str) -> None:
        item = self.sessions.get(session_id)
        if item is not None:
            self.sessions[session_id] = (item[0], True)

    def save_session(self, session: Session) -> bool:
        self._save_calls += 1
        self.sessions[session.id] = (session, False)
        return True


@pytest.mark.asyncio
async def test_todo_updated_event_persists_and_emits_opencode_event() -> None:
    session = Session(id="session_todo")
    manager = _SessionManager(session)
    conversation_manager = SimpleNamespace(
        session_manager=manager,
        agent_session_managers={"default": manager},
    )
    emitted: list[tuple[str, dict[str, Any]]] = []

    class _EventBus:
        async def emit(self, event_type: str, data: dict[str, Any]) -> None:
            emitted.append((event_type, data))

    core = PenguinCore.__new__(PenguinCore)
    setattr(core, "conversation_manager", conversation_manager)
    setattr(core, "event_bus", _EventBus())
    setattr(core, "_opencode_session_directories", {session.id: "/tmp/project"})

    await core._on_tui_todo_updated(
        "todo.updated",
        {
            "sessionID": session.id,
            "todos": [
                {
                    "id": "todo_1",
                    "content": "Implement todo parity",
                    "status": "in_progress",
                    "priority": "high",
                }
            ],
        },
    )

    assert session.metadata[TODO_KEY][0]["content"] == "Implement todo parity"
    assert emitted
    event_type, payload = emitted[-1]
    assert event_type == "opencode_event"
    assert payload["type"] == "todo.updated"
    assert payload["properties"]["sessionID"] == session.id
    assert payload["properties"]["todos"][0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_persist_opencode_events_replays_tool_parts_in_order() -> None:
    session = Session(id="session_track_a")
    manager = _SessionManager(session)
    conversation_manager = SimpleNamespace(
        session_manager=manager,
        agent_session_managers={"default": manager},
    )

    core = PenguinCore.__new__(PenguinCore)
    setattr(core, "conversation_manager", conversation_manager)
    setattr(
        core, "model_config", SimpleNamespace(model="openai/gpt-5", provider="openai")
    )
    setattr(
        core,
        "runtime_config",
        SimpleNamespace(active_root="/tmp/project", project_root="/tmp/project"),
    )
    setattr(core, "_opencode_session_directories", {session.id: "/tmp/project"})

    await core._persist_opencode_event(
        "message.updated",
        {
            "id": "msg_1",
            "sessionID": session.id,
            "role": "assistant",
            "time": {"created": 1},
            "parentID": "root",
            "modelID": "openai/gpt-5",
            "providerID": "openai",
            "mode": "chat",
            "agent": "default",
            "path": {"cwd": "/tmp/project", "root": "/tmp/project"},
            "cost": 0,
            "tokens": {
                "input": 0,
                "output": 0,
                "reasoning": 0,
                "cache": {"read": 0, "write": 0},
            },
        },
    )
    await core._persist_opencode_event(
        "message.part.updated",
        {
            "part": {
                "id": "part_text",
                "sessionID": session.id,
                "messageID": "msg_1",
                "type": "text",
                "text": "working on it",
            }
        },
    )
    await core._persist_opencode_event(
        "message.part.updated",
        {
            "part": {
                "id": "part_tool",
                "sessionID": session.id,
                "messageID": "msg_1",
                "type": "tool",
                "tool": "edit",
                "callID": "call_1",
                "state": {
                    "status": "completed",
                    "input": {"filePath": "src/app.py"},
                    "metadata": {
                        "diff": "--- a/src/app.py\n+++ b/src/app.py\n@@\n-old\n+new\n"
                    },
                    "time": {"start": 1, "end": 2},
                },
            }
        },
    )

    transcript = session.metadata.get(TRANSCRIPT_KEY)
    assert isinstance(transcript, dict)
    assert transcript.get("order") == ["msg_1"]

    message_entry = transcript.get("messages", {}).get("msg_1")
    assert isinstance(message_entry, dict)
    assert message_entry.get("part_order") == ["part_text", "part_tool"]
    assert manager._save_calls >= 1

    rows = get_session_messages(core, session.id)
    assert rows is not None
    assert len(rows) == 1
    assert [part["id"] for part in rows[0]["parts"]] == ["part_text", "part_tool"]


@pytest.mark.asyncio
async def test_persist_opencode_event_uses_session_model_metadata_for_new_entry() -> (
    None
):
    session = Session(id="session_track_model_meta")
    session.metadata["_opencode_provider_id_v1"] = "openrouter"
    session.metadata["_opencode_model_id_v1"] = "z-ai/glm-5-turbo"
    session.metadata["_opencode_variant_v1"] = "high"
    manager = _SessionManager(session)
    conversation_manager = SimpleNamespace(
        session_manager=manager,
        agent_session_managers={"default": manager},
    )

    core = PenguinCore.__new__(PenguinCore)
    setattr(core, "conversation_manager", conversation_manager)
    setattr(
        core,
        "model_config",
        SimpleNamespace(model="z-ai/glm-4.7", provider="openrouter"),
    )
    setattr(
        core,
        "runtime_config",
        SimpleNamespace(active_root="/tmp/project", project_root="/tmp/project"),
    )
    setattr(core, "_opencode_session_directories", {session.id: "/tmp/project"})

    await core._persist_opencode_event(
        "message.part.updated",
        {
            "part": {
                "id": "part_text",
                "sessionID": session.id,
                "messageID": "msg_1",
                "type": "text",
                "text": "hello",
            }
        },
    )

    transcript = session.metadata.get(TRANSCRIPT_KEY)
    assert isinstance(transcript, dict)
    message_entry = transcript.get("messages", {}).get("msg_1")
    assert isinstance(message_entry, dict)
    info = message_entry.get("info")
    assert isinstance(info, dict)
    assert info["providerID"] == "openrouter"
    assert info["modelID"] == "z-ai/glm-5-turbo"
    assert info["variant"] == "high"
