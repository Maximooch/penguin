"""Tests for process streaming helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime import process_streaming


class _Engine:
    default_agent_id = "default-agent"

    def __init__(self) -> None:
        self.prime_calls: list[tuple[str, Any]] = []

    def prime_scoped_conversation_manager(
        self,
        agent_id: str,
        conversation_manager: Any,
    ) -> None:
        self.prime_calls.append((agent_id, conversation_manager))


def _owner() -> SimpleNamespace:
    owner = SimpleNamespace(engine=_Engine())
    owner._resolve_stream_scope_id = lambda execution_context, agent_id: (
        f"scope:{agent_id or 'default'}"
    )
    owner._handle_stream_chunk = AsyncMock()
    return owner


def test_prepare_engine_process_context_resolves_execution_context_and_primes() -> None:
    owner = _owner()
    conversation_manager = SimpleNamespace()
    execution_context = SimpleNamespace(
        conversation_id="conversation-1",
        session_id="session-1",
    )

    context = process_streaming.prepare_engine_process_context(
        owner,
        conversation_manager=conversation_manager,
        conversation_id="fallback-conversation",
        agent_id="agent-1",
        streaming=True,
        stream_callback=None,
        execution_context=execution_context,
        log=logging.getLogger(__name__),
    )

    assert context.scoped_conversation_id == "conversation-1"
    assert context.scoped_session_id == "session-1"
    assert context.stream_scope_id == "scope:agent-1"
    assert owner.engine.prime_calls == [("agent-1", conversation_manager)]


@pytest.mark.asyncio
async def test_engine_stream_callback_routes_internal_stream_scope() -> None:
    owner = _owner()
    conversation_manager = SimpleNamespace()
    execution_context = SimpleNamespace(
        conversation_id="conversation-1",
        session_id="session-1",
    )

    context = process_streaming.prepare_engine_process_context(
        owner,
        conversation_manager=conversation_manager,
        conversation_id=None,
        agent_id="agent-1",
        streaming=True,
        stream_callback=None,
        execution_context=execution_context,
        log=logging.getLogger(__name__),
    )

    assert context.stream_callback is not None
    await context.stream_callback("hello", "reasoning")

    owner._handle_stream_chunk.assert_awaited_once_with(
        "hello",
        message_type="reasoning",
        agent_id="agent-1",
        stream_scope_id="scope:agent-1",
        session_id="session-1",
        conversation_id="conversation-1",
    )


def test_prepare_engine_process_context_falls_back_to_active_session() -> None:
    owner = _owner()
    conversation_manager = SimpleNamespace(
        get_current_session=lambda: SimpleNamespace(id="active-session")
    )

    context = process_streaming.prepare_engine_process_context(
        owner,
        conversation_manager=conversation_manager,
        conversation_id=None,
        agent_id=None,
        streaming=False,
        stream_callback=None,
        execution_context=None,
        log=logging.getLogger(__name__),
    )

    assert context.scoped_conversation_id == "active-session"
    assert context.scoped_session_id == "active-session"
    assert context.stream_callback is None
    assert owner.engine.prime_calls == [("default-agent", conversation_manager)]


@pytest.mark.asyncio
async def test_combined_callback_forwards_to_sync_external_callback_with_type() -> None:
    owner = _owner()
    external_calls: list[tuple[str, str]] = []

    def external_callback(chunk: str, message_type: str) -> None:
        external_calls.append((chunk, message_type))

    context = process_streaming.prepare_engine_process_context(
        owner,
        conversation_manager=SimpleNamespace(),
        conversation_id="conversation-1",
        agent_id="agent-1",
        streaming=True,
        stream_callback=external_callback,
        execution_context=None,
        log=logging.getLogger(__name__),
    )

    assert context.stream_callback is not None
    await context.stream_callback("chunk", "tool_output")

    owner._handle_stream_chunk.assert_awaited_once()
    assert external_calls == [("chunk", "tool_output")]


@pytest.mark.asyncio
async def test_combined_callback_forwards_to_async_external_callback_without_type() -> (
    None
):
    owner = _owner()
    external_calls: list[str] = []

    async def external_callback(chunk: str) -> None:
        external_calls.append(chunk)

    context = process_streaming.prepare_engine_process_context(
        owner,
        conversation_manager=SimpleNamespace(),
        conversation_id="conversation-1",
        agent_id="agent-1",
        streaming=True,
        stream_callback=external_callback,
        execution_context=None,
        log=logging.getLogger(__name__),
    )

    assert context.stream_callback is not None
    await context.stream_callback("chunk", "reasoning")

    owner._handle_stream_chunk.assert_awaited_once()
    assert external_calls == ["chunk"]


@pytest.mark.asyncio
async def test_combined_callback_logs_external_failures_after_internal_stream(
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner = _owner()

    def external_callback(_chunk: str) -> None:
        raise RuntimeError("callback failed")

    context = process_streaming.prepare_engine_process_context(
        owner,
        conversation_manager=SimpleNamespace(),
        conversation_id="conversation-1",
        agent_id="agent-1",
        streaming=True,
        stream_callback=external_callback,
        execution_context=None,
        log=logging.getLogger(__name__),
    )

    assert context.stream_callback is not None
    with caplog.at_level(logging.ERROR):
        await context.stream_callback("chunk", "assistant")

    owner._handle_stream_chunk.assert_awaited_once()
    assert "Error in external stream_callback: callback failed" in caplog.text
