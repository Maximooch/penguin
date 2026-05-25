"""Tests for OpenCode stream event bridge helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import stream_events


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
