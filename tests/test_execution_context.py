"""Tests for request-scoped execution context propagation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.core import PenguinCore
from penguin.llm.stream_handler import AgentStreamingStateManager
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    get_current_execution_context,
)
from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionExecutor


def test_execution_context_scope_sets_and_resets(tmp_path: Path):
    directory = tmp_path / "project"
    directory.mkdir()

    assert get_current_execution_context() is None

    with execution_context_scope(
        ExecutionContext(session_id="s1", directory=str(directory))
    ):
        current = get_current_execution_context()
        assert current is not None
        assert current.session_id == "s1"
        assert current.directory is not None
        assert Path(current.directory).resolve() == directory.resolve()

    assert get_current_execution_context() is None


def test_tool_manager_resolves_root_from_execution_context(tmp_path: Path):
    default_root = tmp_path / "default"
    scoped_root = tmp_path / "scoped"
    default_root.mkdir()
    scoped_root.mkdir()

    manager = ToolManager.__new__(ToolManager)
    manager._file_root = str(default_root)

    assert Path(manager._resolve_file_root({})).resolve() == default_root.resolve()

    with execution_context_scope(
        ExecutionContext(session_id="s2", directory=str(scoped_root))
    ):
        assert Path(manager._resolve_file_root({})).resolve() == scoped_root.resolve()


@pytest.mark.asyncio
async def test_execution_context_propagates_to_thread(tmp_path: Path):
    directory = tmp_path / "thread"
    directory.mkdir()

    with execution_context_scope(
        ExecutionContext(session_id="s3", directory=str(directory))
    ):
        from_thread = await asyncio.to_thread(get_current_execution_context)

    assert from_thread is not None
    assert from_thread.session_id == "s3"


def test_stream_scope_prefers_execution_context_agent(tmp_path: Path):
    directory = tmp_path / "scope"
    directory.mkdir()

    core = PenguinCore.__new__(PenguinCore)
    setattr(
        core,
        "conversation_manager",
        type(
            "_ConversationManager",
            (),
            {"current_agent_id": "default"},
        )(),
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="session_scope",
            conversation_id="session_scope",
            agent_id="penguin",
            directory=str(directory),
        )
    ) as context:
        resolved = core._resolve_stream_scope_id(context, agent_id=None)

    assert resolved == "session_scope:penguin"


def test_action_executor_execute_code_uses_scoped_directory(tmp_path: Path):
    scoped = tmp_path / "scoped"
    scoped.mkdir()

    class _ToolManager:
        def __init__(self):
            self.calls: list[tuple[str, dict[str, Any], str | None]] = []

        def execute_code(self, code: str, cwd: str | None = None) -> str:
            raise AssertionError(
                "ActionExecutor should use execute_tool for code_execution"
            )

        def execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
            context = get_current_execution_context()
            directory = context.directory if context else None
            self.calls.append((tool_name, tool_input, directory))
            return directory or ""

    tool_manager = _ToolManager()
    executor = ActionExecutor(
        tool_manager=tool_manager,  # type: ignore[arg-type]
        task_manager=cast(Any, SimpleNamespace()),
    )

    with execution_context_scope(
        ExecutionContext(session_id="s-code", directory=str(scoped))
    ):
        result = executor._execute_code("print('hi')")

    assert tool_manager.calls
    tool_name, tool_input, call_directory = tool_manager.calls[-1]
    assert tool_name == "code_execution"
    assert tool_input["code"] == "print('hi')"
    assert call_directory == str(scoped)
    assert result == str(scoped)


@pytest.mark.asyncio
async def test_stream_chunk_prefers_explicit_session_hints() -> None:
    events: list[tuple[str, dict]] = []

    async def _emit(event_type: str, data: dict) -> None:
        events.append((event_type, data))

    class _ConversationManager:
        current_agent_id = "cadence_agent"

        @staticmethod
        def get_current_session():
            return type("_Session", (), {"id": "test-session-112-cadence"})()

    core = PenguinCore.__new__(PenguinCore)
    setattr(core, "conversation_manager", _ConversationManager())
    setattr(core, "_stream_manager", AgentStreamingStateManager())
    setattr(core, "_runmode_stream_callback", None)
    setattr(core, "emit_ui_event", _emit)
    core_any: Any = core

    await core_any._handle_stream_chunk(
        "tuxford stream payload content",
        message_type="assistant",
        agent_id="tuxford_agent",
        stream_scope_id="test-session-110-tuxford:tuxford_agent",
        session_id="test-session-110-tuxford",
        conversation_id="test-session-110-tuxford",
    )

    stream_events = [
        payload
        for event_type, payload in events
        if event_type == "stream_chunk" and isinstance(payload, dict)
    ]
    assert stream_events
    assert stream_events[-1].get("session_id") == "test-session-110-tuxford"
    assert stream_events[-1].get("conversation_id") == "test-session-110-tuxford"


@pytest.mark.asyncio
async def test_finalize_streaming_uses_explicit_session_scope() -> None:
    events: list[tuple[str, dict]] = []

    async def _emit(event_type: str, data: dict) -> None:
        events.append((event_type, data))

    class _Conversation:
        def __init__(self):
            self.messages = []

        def add_message(self, **kwargs):
            self.messages.append(kwargs)

    class _ConversationManager:
        def __init__(self):
            self.current_agent_id = "cadence_agent"
            self.conversation = _Conversation()
            self._by_agent: dict[str, _Conversation] = {}

        def get_agent_conversation(self, agent_id: str):
            if agent_id not in self._by_agent:
                self._by_agent[agent_id] = _Conversation()
            return self._by_agent[agent_id]

        @staticmethod
        def get_current_session():
            return type("_Session", (), {"id": "test-session-112-cadence"})()

    core = PenguinCore.__new__(PenguinCore)
    setattr(core, "conversation_manager", _ConversationManager())
    setattr(core, "_stream_manager", AgentStreamingStateManager())
    setattr(core, "_runmode_stream_callback", None)
    setattr(core, "emit_ui_event", _emit)
    core_any: Any = core

    core_any._stream_manager.handle_chunk(
        "cadence stream payload content",
        agent_id="test-session-112-cadence:cadence_agent",
        message_type="assistant",
    )
    core_any._stream_manager.handle_chunk(
        "tuxford stream payload content",
        agent_id="test-session-110-tuxford:tuxford_agent",
        message_type="assistant",
    )

    finalized = core_any.finalize_streaming_message(
        agent_id="tuxford_agent",
        session_id="test-session-110-tuxford",
        conversation_id="test-session-110-tuxford",
    )

    await asyncio.sleep(0)

    assert finalized is not None
    assert "tuxford" in finalized["content"]
    assert core_any._stream_manager.is_agent_active(
        "test-session-112-cadence:cadence_agent"
    )
    final_events = [
        payload
        for event_type, payload in events
        if event_type == "stream_chunk"
        and isinstance(payload, dict)
        and payload.get("is_final")
    ]
    assert final_events
    assert final_events[-1].get("session_id") == "test-session-110-tuxford"
