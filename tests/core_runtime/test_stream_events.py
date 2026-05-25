"""Tests for OpenCode stream event bridge helpers."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import stream_events
from penguin.llm.stream_handler import AgentStreamingStateManager
from penguin.system.state import MessageCategory


class _Adapter:
    def __init__(self) -> None:
        self.starts: list[dict[str, Any]] = []
        self.chunks: list[tuple[str, str, str, str]] = []
        self.ends: list[tuple[str, str]] = []
        self._active_parts: dict[str, dict[str, Any]] = {}

    async def on_stream_start(
        self,
        *,
        agent_id: str = "default",
        model_id: str | None = None,
        provider_id: str | None = None,
        variant: str | None = None,
    ) -> tuple[str, str]:
        message_id = f"msg_{len(self.starts) + 1}"
        part_id = f"part_{len(self.starts) + 1}"
        self.starts.append(
            {
                "agent_id": agent_id,
                "model_id": model_id,
                "provider_id": provider_id,
                "variant": variant,
            }
        )
        self._active_parts[part_id] = {"content": {"text": ""}}
        return message_id, part_id

    async def on_stream_chunk(
        self,
        message_id: str,
        part_id: str,
        chunk: str,
        message_type: str,
    ) -> None:
        self.chunks.append((message_id, part_id, chunk, message_type))
        if chunk:
            self._active_parts[part_id]["content"]["text"] += chunk

    async def on_stream_end(self, message_id: str, part_id: str) -> None:
        self.ends.append((message_id, part_id))


class _Owner:
    def __init__(self, adapter: _Adapter) -> None:
        self.adapter = adapter
        self._opencode_stream_states: dict[str, dict[str, Any]] = {}
        self._opencode_message_adapters: dict[str, _Adapter] = {}

    def _get_tui_adapter(self, session_id: str) -> _Adapter:
        del session_id
        return self.adapter

    def _resolve_opencode_model_state(self, session_id: str) -> dict[str, str]:
        del session_id
        return {
            "modelID": "gpt-5.4",
            "providerID": "openai",
            "variant": "high",
        }


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


def test_should_emit_final_content_detects_existing_part_text() -> None:
    adapter = _Adapter()
    adapter._active_parts["part_1"] = {"content": {"text": "already streamed"}}

    assert stream_events.active_part_text(adapter, "part_1") == "already streamed"
    assert (
        stream_events.should_emit_final_content(adapter, "part_1", "final content")
        is False
    )
    assert (
        stream_events.should_emit_final_content(
            adapter,
            "part_missing",
            "final content",
        )
        is True
    )


def test_filter_internal_markers_removes_private_protocol_text_without_mutation() -> (
    None
):
    payload = {
        "content": "visible <execute>hidden</execute>",
        "chunk": "<system-reminder>hide</system-reminder> keep",
        "content_so_far": "a <internal>b</internal> c",
        "message": "done </finish_response>",
        "other": "<execute>preserved outside filtered fields</execute>",
    }

    filtered = stream_events.filter_internal_markers_from_event(payload)

    assert filtered is not payload
    assert payload["content"] == "visible <execute>hidden</execute>"
    assert filtered == {
        "content": "visible",
        "chunk": "keep",
        "content_so_far": "a  c",
        "message": "done",
        "other": "<execute>preserved outside filtered fields</execute>",
    }


def test_filter_internal_markers_returns_original_when_unchanged() -> None:
    payload = {"chunk": "plain text", "count": 3}

    filtered = stream_events.filter_internal_markers_from_event(payload)

    assert filtered is payload


def test_resolve_stream_scope_id_prefers_execution_context_session_and_agent() -> None:
    context = SimpleNamespace(
        session_id="session_1",
        conversation_id="conversation_1",
        agent_id="context-agent",
    )
    manager = SimpleNamespace(current_agent_id="manager-agent")

    scope_id = stream_events.resolve_stream_scope_id(
        conversation_manager=manager,
        execution_context=context,
        agent_id=None,
    )

    assert scope_id == "session_1:context-agent"


def test_resolve_stream_scope_id_falls_back_to_conversation_and_manager_agent() -> None:
    context = SimpleNamespace(
        session_id=None,
        conversation_id="conversation_1",
        agent_id=None,
    )
    manager = SimpleNamespace(current_agent_id="manager-agent")

    scope_id = stream_events.resolve_stream_scope_id(
        conversation_manager=manager,
        execution_context=context,
        agent_id=None,
    )

    assert scope_id == "conversation_1:manager-agent"


def test_resolve_stream_scope_id_uses_default_without_context_or_manager_agent() -> (
    None
):
    scope_id = stream_events.resolve_stream_scope_id(
        conversation_manager=SimpleNamespace(current_agent_id=None),
        execution_context=None,
        agent_id=None,
    )

    assert scope_id == "default"


@pytest.mark.asyncio
async def test_emit_opencode_session_status_shapes_and_scopes_event() -> None:
    owner = SimpleNamespace(event_bus=_EventBus())

    await stream_events.emit_opencode_session_status(
        owner,
        " session_1 ",
        "busy",
        info={"task_id": "task_1"},
    )
    await stream_events.emit_opencode_session_status(owner, " ", "idle")

    assert owner.event_bus.events == [
        (
            "opencode_event",
            {
                "type": "session.status",
                "properties": {
                    "sessionID": "session_1",
                    "status": {"type": "busy"},
                    "info": {"task_id": "task_1"},
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_abort_session_cancels_tasks_cleans_scoped_state_and_emits_idle() -> None:
    class _AbortAdapter:
        def __init__(self) -> None:
            self.reasons: list[str] = []

        async def abort(self, reason: str) -> bool:
            self.reasons.append(reason)
            return True

    class _StreamManager:
        def get_active_agents(self) -> list[str]:
            return ["session_1:agent-a", "session_2:agent-b"]

        def abort(self, agent_id: str) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(
                    event_type="stream_chunk",
                    data={"agent_id": agent_id, "aborted": True},
                )
            ]

    async def _sleep_forever() -> None:
        await asyncio.sleep(60)

    pending_task = asyncio.create_task(_sleep_forever())
    adapter = _AbortAdapter()
    owner = SimpleNamespace(
        event_bus=_EventBus(),
        _get_tui_adapter=lambda _session_id: adapter,
        _stream_manager=_StreamManager(),
        _opencode_abort_sessions=set(),
        _opencode_process_tasks={"session_1": {pending_task}},
        _opencode_stream_states={
            "session_1": {
                "active": True,
                "stream_id": "stream_1",
                "message_id": "msg_1",
                "part_id": "part_1",
            }
        },
        _opencode_tool_parts={
            "session_1:call_1": "part_tool",
            "session_2:call_2": "part_other",
        },
        _opencode_tool_info={
            "session_1:call_1": {"tool": "bash"},
            "session_2:call_2": {"tool": "read"},
        },
    )
    owner.ui_events = []

    async def _emit_ui_event(event_type: str, data: dict[str, Any]) -> None:
        owner.ui_events.append((event_type, data))

    owner.emit_ui_event = _emit_ui_event

    aborted = await stream_events.abort_session(
        owner,
        "session_1",
        logger=logging.getLogger("test.stream_events"),
    )

    assert aborted is True
    assert adapter.reasons == ["Tool execution was interrupted"]
    assert "session_1" in owner._opencode_abort_sessions
    with pytest.raises(asyncio.CancelledError):
        await pending_task

    assert owner._opencode_stream_states["session_1"]["active"] is False
    assert owner._opencode_stream_states["session_1"]["stream_id"] is None
    assert owner._opencode_stream_states["session_1"]["part_id"] is None
    assert "session_1:call_1" not in owner._opencode_tool_parts
    assert "session_1:call_1" not in owner._opencode_tool_info
    assert "session_2:call_2" in owner._opencode_tool_parts
    assert "session_2:call_2" in owner._opencode_tool_info

    assert owner.ui_events == [
        (
            "stream_chunk",
            {
                "agent_id": "session_1:agent-a",
                "aborted": True,
                "session_id": "session_1",
                "conversation_id": "session_1",
            },
        )
    ]
    status_event = owner.event_bus.events[-1][1]
    assert status_event["type"] == "session.status"
    assert status_event["properties"]["sessionID"] == "session_1"
    assert status_event["properties"]["status"]["type"] == "idle"


def test_persist_finalized_message_writes_target_session_store() -> None:
    trace_messages: list[tuple[str, tuple[Any, ...]]] = []
    persisted_messages: list[Any] = []
    session = SimpleNamespace(
        add_message=lambda message: persisted_messages.append(message)
    )
    manager = SimpleNamespace(
        save_session=lambda saved_session: saved_session is session
    )
    owner = SimpleNamespace(
        _find_session_store=lambda session_id: (
            (session, manager) if session_id == "session_1" else (None, None)
        )
    )
    message = SimpleNamespace(
        id="msg_1",
        role="assistant",
        content="persist me",
        metadata={"source": "stream"},
        timestamp="2026-05-25T00:00:00",
        tokens=7,
        agent_id=None,
        recipient_id="user",
        message_type="message",
    )

    saved = stream_events.persist_finalized_message(
        owner,
        agent_id="agent-a",
        session_id=" session_1 ",
        message=message,
        category=MessageCategory.DIALOG,
        trace_log=lambda template, *args: trace_messages.append((template, args)),
    )

    assert saved is True
    assert len(persisted_messages) == 1
    persisted = persisted_messages[0]
    assert persisted.id == "msg_1"
    assert persisted.content == "persist me"
    assert persisted.agent_id == "agent-a"
    assert persisted.recipient_id == "user"
    assert persisted.tokens == 7
    assert trace_messages[-1][1][0] == "session_1"


def test_persist_finalized_message_fails_closed_without_target_store() -> None:
    trace_messages: list[tuple[str, tuple[Any, ...]]] = []
    owner = SimpleNamespace(_find_session_store=lambda _session_id: (None, None))
    message = SimpleNamespace(role="assistant", content="missing")

    saved = stream_events.persist_finalized_message(
        owner,
        agent_id="agent-a",
        session_id="missing_session",
        message=message,
        category=MessageCategory.DIALOG,
        trace_log=lambda template, *args: trace_messages.append((template, args)),
    )

    assert saved is False
    assert trace_messages == [
        (
            "core.stream.persist session=%s agent=%s status=missing_store",
            ("missing_session", "agent-a"),
        )
    ]


@pytest.mark.asyncio
async def test_finalize_streaming_message_persists_and_emits_scoped_final_event() -> (
    None
):
    class _Message:
        def __init__(self) -> None:
            self.role = "assistant"
            self.content = "final response"
            self.metadata = {"source": "stream"}
            self.was_empty = False

        def to_dict(self) -> dict[str, str]:
            return {"content": self.content}

    class _StreamManager:
        def finalize(self, agent_id: str) -> tuple[_Message, list[SimpleNamespace]]:
            assert agent_id == "session_1:agent-a"
            return (
                _Message(),
                [
                    SimpleNamespace(
                        event_type="stream_chunk",
                        data={
                            "chunk": "visible <execute>hidden</execute>",
                            "is_final": True,
                        },
                    )
                ],
            )

        def get_active_agents(self) -> list[str]:
            return []

    persisted: list[dict[str, Any]] = []
    emitted: list[tuple[str, dict[str, Any]]] = []
    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id="default"),
        _stream_manager=_StreamManager(),
        _runmode_stream_callback=None,
    )
    owner._persist_finalized_message = lambda **kwargs: persisted.append(kwargs) or True
    owner._filter_internal_markers_from_event = (
        stream_events.filter_internal_markers_from_event
    )

    async def _emit_ui_event(event_type: str, data: dict[str, Any]) -> None:
        emitted.append((event_type, data))

    owner.emit_ui_event = _emit_ui_event

    result = stream_events.finalize_streaming_message(
        owner,
        agent_id="agent-a",
        session_id="session_1",
        conversation_id="session_1",
        logger=logging.getLogger("test.stream_events"),
    )
    await asyncio.sleep(0)

    assert result == {"content": "final response"}
    assert persisted[0]["agent_id"] == "agent-a"
    assert persisted[0]["session_id"] == "session_1"
    assert persisted[0]["category"] == MessageCategory.DIALOG
    assert emitted == [
        (
            "stream_chunk",
            {
                "chunk": "visible",
                "is_final": True,
                "session_id": "session_1",
                "conversation_id": "session_1",
                "agent_id": "agent-a",
            },
        )
    ]


def test_finalize_streaming_message_falls_back_only_when_unscoped() -> None:
    class _Message:
        def __init__(self) -> None:
            self.role = "assistant"
            self.content = "fallback response"
            self.metadata: dict[str, Any] = {}
            self.was_empty = False

        def to_dict(self) -> dict[str, str]:
            return {"content": self.content}

    class _StreamManager:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def finalize(self, agent_id: str) -> tuple[_Message | None, list[Any]]:
            self.calls.append(agent_id)
            if agent_id == "active-agent":
                return _Message(), []
            return None, []

        def get_active_agents(self) -> list[str]:
            return ["active-agent"]

    stream_manager = _StreamManager()
    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id="default"),
        _stream_manager=stream_manager,
        _runmode_stream_callback=None,
    )
    owner._resolve_stream_scope_id = lambda _context, agent_id: agent_id
    owner._persist_finalized_message = lambda **_kwargs: True

    result = stream_events.finalize_streaming_message(
        owner,
        logger=logging.getLogger("test.stream_events"),
    )

    assert result == {"content": "fallback response"}
    assert stream_manager.calls == ["default", "active-agent"]


@pytest.mark.asyncio
async def test_abort_streaming_message_derives_scope_and_emits_filtered_event() -> None:
    trace_messages: list[tuple[str, tuple[Any, ...]]] = []
    emitted: list[tuple[str, dict[str, Any]]] = []

    class _StreamManager:
        def __init__(self) -> None:
            self.abort_calls: list[str | None] = []

        def abort(self, agent_id: str | None = None) -> list[SimpleNamespace]:
            self.abort_calls.append(agent_id)
            return [
                SimpleNamespace(
                    event_type="stream_interrupted",
                    data={"chunk": "keep <internal>drop</internal>"},
                )
            ]

    stream_manager = _StreamManager()
    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id="ambient-agent"),
        _stream_manager=stream_manager,
    )
    owner._filter_internal_markers_from_event = (
        stream_events.filter_internal_markers_from_event
    )

    async def _emit_ui_event(event_type: str, data: dict[str, Any]) -> None:
        emitted.append((event_type, data))

    owner.emit_ui_event = _emit_ui_event

    aborted = stream_events.abort_streaming_message(
        owner,
        stream_scope_id="session_1:agent-a",
        trace_log=lambda template, *args: trace_messages.append((template, args)),
    )
    await asyncio.sleep(0)

    assert aborted is True
    assert stream_manager.abort_calls == ["session_1:agent-a"]
    assert emitted == [
        (
            "stream_interrupted",
            {
                "chunk": "keep",
                "session_id": "session_1",
                "conversation_id": "session_1",
                "agent_id": "agent-a",
            },
        )
    ]
    assert trace_messages[-1][1][1:5] == (
        "session_1",
        "session_1",
        "agent-a",
        "session_1:agent-a",
    )


def test_abort_streaming_message_returns_false_without_events() -> None:
    class _StreamManager:
        def abort(self, agent_id: str | None = None) -> list[Any]:
            del agent_id
            return []

    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id="default"),
        _stream_manager=_StreamManager(),
    )

    aborted = stream_events.abort_streaming_message(
        owner,
        session_id="session_1",
        conversation_id="session_1",
    )

    assert aborted is False


@pytest.mark.asyncio
async def test_handle_stream_chunk_scopes_filters_and_forwards_runmode() -> None:
    emitted: list[tuple[str, dict[str, Any]]] = []
    callbacks: list[tuple[str, str]] = []

    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id="ambient-agent"),
        _stream_manager=AgentStreamingStateManager(),
        _opencode_abort_sessions=set(),
    )
    owner._filter_internal_markers_from_event = (
        stream_events.filter_internal_markers_from_event
    )

    async def _emit_ui_event(event_type: str, data: dict[str, Any]) -> None:
        emitted.append((event_type, data))

    async def _invoke_runmode_stream_callback(
        chunk: str,
        message_type: str,
    ) -> None:
        callbacks.append((chunk, message_type))

    owner.emit_ui_event = _emit_ui_event
    owner._invoke_runmode_stream_callback = _invoke_runmode_stream_callback

    await stream_events.handle_stream_chunk(
        owner,
        "visible <execute>hidden</execute>",
        message_type="assistant",
        role="assistant",
        agent_id="agent-a",
        stream_scope_id="session_1:agent-a",
        session_id="session_1",
        conversation_id="session_1",
        logger=logging.getLogger(__name__),
    )

    assert emitted
    event_type, payload = emitted[-1]
    assert event_type == "stream_chunk"
    assert payload["chunk"] == "visible"
    assert payload["session_id"] == "session_1"
    assert payload["conversation_id"] == "session_1"
    assert payload["agent_id"] == "agent-a"
    assert callbacks == [("visible", "assistant")]


@pytest.mark.asyncio
async def test_handle_stream_chunk_cancels_aborted_session_before_state_mutation() -> (
    None
):
    emitted: list[tuple[str, dict[str, Any]]] = []

    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id="agent-a"),
        _stream_manager=AgentStreamingStateManager(),
        _opencode_abort_sessions={"session_1"},
    )
    owner._filter_internal_markers_from_event = (
        stream_events.filter_internal_markers_from_event
    )
    owner.emit_ui_event = lambda event_type, data: emitted.append((event_type, data))
    owner._invoke_runmode_stream_callback = lambda _chunk, _message_type: None

    with pytest.raises(asyncio.CancelledError):
        await stream_events.handle_stream_chunk(
            owner,
            "should not emit",
            message_type="assistant",
            role="assistant",
            agent_id="agent-a",
            stream_scope_id="session_1:agent-a",
            session_id="session_1",
            conversation_id="session_1",
            logger=logging.getLogger(__name__),
        )

    assert emitted == []
    assert not owner._stream_manager.is_agent_active("session_1:agent-a")


@pytest.mark.asyncio
async def test_emit_opencode_stream_helpers_route_through_session_adapter() -> None:
    class _Adapter:
        def __init__(self) -> None:
            self.starts: list[tuple[str, str | None, str | None, str | None]] = []
            self.chunks: list[tuple[str, str, str, str]] = []
            self.ends: list[tuple[str, str]] = []

        async def on_stream_start(
            self,
            agent_id: str = "default",
            model_id: str | None = None,
            provider_id: str | None = None,
            variant: str | None = None,
        ) -> tuple[str, str]:
            self.starts.append((agent_id, model_id, provider_id, variant))
            return "msg_1", "part_1"

        async def on_stream_chunk(
            self,
            message_id: str,
            part_id: str,
            chunk: str,
            message_type: str,
        ) -> None:
            self.chunks.append((message_id, part_id, chunk, message_type))

        async def on_stream_end(self, message_id: str, part_id: str) -> None:
            self.ends.append((message_id, part_id))

    adapter = _Adapter()
    model_state_calls: list[dict[str, Any]] = []
    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(get_current_session=lambda: None),
        _opencode_message_adapters={},
        _tui_adapter=adapter,
    )
    owner._get_tui_adapter = lambda session_id: adapter

    def _model_state(**kwargs: Any) -> dict[str, str]:
        model_state_calls.append(kwargs)
        return {
            "modelID": "gpt-5.4",
            "providerID": "openai",
            "variant": "high",
        }

    owner._resolve_opencode_model_state = _model_state

    message_id, part_id = await stream_events.emit_opencode_stream_start(
        owner,
        agent_id="agent-a",
        model_id="requested-model",
        provider_id="requested-provider",
        execution_context=SimpleNamespace(
            session_id="session_1",
            conversation_id="session_1",
        ),
    )
    await stream_events.emit_opencode_stream_chunk(
        owner,
        message_id,
        part_id,
        "hello",
        "assistant",
    )
    await stream_events.emit_opencode_stream_end(owner, message_id, part_id)

    assert (message_id, part_id) == ("msg_1", "part_1")
    assert adapter.starts == [("agent-a", "gpt-5.4", "openai", "high")]
    assert adapter.chunks == [("msg_1", "part_1", "hello", "assistant")]
    assert adapter.ends == [("msg_1", "part_1")]
    assert owner._opencode_message_adapters == {}
    assert model_state_calls == [
        {
            "session_id": "session_1",
            "model_id": "requested-model",
            "provider_id": "requested-provider",
        }
    ]


@pytest.mark.asyncio
async def test_emit_opencode_user_message_with_metadata_uses_model_state() -> None:
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

    adapter = _Adapter()
    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(get_current_session=lambda: None),
        _get_tui_adapter=lambda _session_id: adapter,
        _resolve_opencode_model_state=lambda session_id: {
            "modelID": "gpt-5.4",
            "providerID": "openai",
            "variant": "high",
        },
    )

    message_id = await stream_events.emit_opencode_user_message_with_metadata(
        owner,
        "hello",
        message_id="msg_client_1",
        agent_id="agent-a",
        execution_context=SimpleNamespace(
            session_id="session_1",
            conversation_id="session_1",
        ),
    )

    assert message_id == "msg_client_1"
    assert adapter.calls == [
        {
            "content": "hello",
            "message_id": "msg_client_1",
            "agent_id": "agent-a",
            "model_id": "gpt-5.4",
            "provider_id": "openai",
            "variant": "high",
        }
    ]


@pytest.mark.asyncio
async def test_handle_tui_stream_chunk_starts_tracks_and_finalizes_stream() -> None:
    adapter = _Adapter()
    owner = _Owner(adapter)

    await stream_events.handle_tui_stream_chunk(
        owner,
        "stream_chunk",
        {
            "stream_id": "stream_1",
            "session_id": "session_1",
            "agent_id": "build",
            "chunk": "hello",
        },
        logger=logging.getLogger("test.stream_events"),
    )
    await stream_events.handle_tui_stream_chunk(
        owner,
        "stream_chunk",
        {
            "stream_id": "stream_1",
            "session_id": "session_1",
            "chunk": "",
            "content": "hello",
            "is_final": True,
        },
        logger=logging.getLogger("test.stream_events"),
    )

    assert adapter.starts == [
        {
            "agent_id": "build",
            "model_id": "gpt-5.4",
            "provider_id": "openai",
            "variant": "high",
        }
    ]
    assert ("msg_1", "part_1", "hello", "assistant") in adapter.chunks
    assert adapter.chunks.count(("msg_1", "part_1", "hello", "assistant")) == 1
    assert adapter.ends == [("msg_1", "part_1")]
    assert owner._opencode_message_adapters["msg_1"] is adapter
    assert owner._opencode_stream_states["session_1"] == {
        "active": False,
        "stream_id": None,
        "message_id": "msg_1",
        "part_id": None,
    }


@pytest.mark.asyncio
async def test_handle_tui_stream_chunk_finalizes_active_stream_before_new_id() -> None:
    adapter = _Adapter()
    owner = _Owner(adapter)

    await stream_events.handle_tui_stream_chunk(
        owner,
        "stream_chunk",
        {"stream_id": "stream_1", "session_id": "session_1", "chunk": "one"},
        logger=logging.getLogger("test.stream_events"),
    )
    await stream_events.handle_tui_stream_chunk(
        owner,
        "stream_chunk",
        {"stream_id": "stream_2", "session_id": "session_1", "chunk": "two"},
        logger=logging.getLogger("test.stream_events"),
    )

    assert adapter.ends == [("msg_1", "part_1")]
    assert adapter.starts[1]["agent_id"] == "default"
    assert owner._opencode_stream_states["session_1"]["stream_id"] == "stream_2"
    assert owner._opencode_stream_states["session_1"]["message_id"] == "msg_2"


@pytest.mark.asyncio
async def test_handle_tui_stream_chunk_ignores_inactive_abort_final() -> None:
    adapter = _Adapter()
    owner = _Owner(adapter)
    owner._opencode_stream_states["session_1"] = {
        "active": False,
        "stream_id": "stream_1",
        "message_id": "msg_old",
        "part_id": "part_old",
    }

    await stream_events.handle_tui_stream_chunk(
        owner,
        "stream_chunk",
        {
            "stream_id": "stream_1",
            "session_id": "session_1",
            "chunk": "",
            "is_final": True,
            "aborted": True,
        },
        logger=logging.getLogger("test.stream_events"),
    )

    assert adapter.starts == []
    assert adapter.chunks == []
    assert adapter.ends == []
    assert owner._opencode_stream_states["session_1"]["stream_id"] is None
    assert owner._opencode_stream_states["session_1"]["part_id"] is None
