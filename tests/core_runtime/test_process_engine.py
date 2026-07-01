"""Tests for Engine process dispatch helpers."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime import process_engine


class _Engine:
    def __init__(self) -> None:
        self.run_task = AsyncMock(return_value={"status": "task"})
        self.run_response = AsyncMock(return_value={"status": "response"})
        self.run_single_turn = AsyncMock(return_value={"status": "single"})


def _owner() -> SimpleNamespace:
    return SimpleNamespace(engine=_Engine())


def _conversation_manager() -> SimpleNamespace:
    return SimpleNamespace(
        conversation=SimpleNamespace(session=SimpleNamespace(id="session-1"))
    )


async def _run_dispatch(
    owner: SimpleNamespace,
    *,
    context: dict[str, Any] | None = None,
    multi_step: bool = True,
    stream_callback: Any = None,
    trace_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] | None = None,
) -> Any:
    if trace_calls is None:
        trace_calls = []
    return await process_engine.run_engine_process(
        owner,
        message="hello",
        image_paths=["image.png"],
        max_iterations=3,
        context=context,
        multi_step=multi_step,
        streaming=True,
        stream_callback=stream_callback,
        engine_stream_callback="engine-stream-callback",
        agent_id="agent-1",
        api_client_override="api-override",
        model_config_override="model-override",
        conversation_manager=_conversation_manager(),
        execution_context=SimpleNamespace(request_id="request-1"),
        request_session_id="request-session",
        scoped_conversation_id="conversation-1",
        trace_log_info=lambda *args, **kwargs: trace_calls.append((args, kwargs)),
    )


@pytest.mark.asyncio
async def test_run_engine_process_dispatches_formal_task() -> None:
    owner = _owner()
    trace_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    result = await _run_dispatch(
        owner,
        context={"task_mode": True, "task_id": "task-1"},
        trace_calls=trace_calls,
    )

    assert result == {"status": "task"}
    owner.engine.run_task.assert_awaited_once_with(
        task_prompt="hello",
        image_paths=["image.png"],
        max_iterations=3,
        task_context={"task_mode": True, "task_id": "task-1"},
        message_callback=None,
        agent_id="agent-1",
        api_client_override="api-override",
        model_config_override="model-override",
    )
    owner.engine.run_response.assert_not_awaited()
    assert trace_calls[0][0][5] is True


@pytest.mark.asyncio
async def test_run_engine_process_bridges_formal_task_assistant_messages() -> None:
    owner = _owner()
    callback_messages: list[str] = []
    delivered = threading.Event()

    def stream_callback(message: str) -> None:
        callback_messages.append(message)
        delivered.set()

    await _run_dispatch(
        owner,
        context={"task_mode": True},
        stream_callback=stream_callback,
    )

    message_callback = owner.engine.run_task.await_args.kwargs["message_callback"]
    assert message_callback is not None
    await message_callback("ignored", "tool")
    await message_callback("visible", "assistant")
    await asyncio.to_thread(delivered.wait, 1)

    assert callback_messages == ["visible"]


@pytest.mark.asyncio
async def test_run_engine_process_dispatches_multi_step_response() -> None:
    owner = _owner()
    trace_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    result = await _run_dispatch(
        owner,
        context={"task_mode": False},
        trace_calls=trace_calls,
    )

    assert result == {"status": "response"}
    owner.engine.run_response.assert_awaited_once_with(
        prompt="hello",
        image_paths=["image.png"],
        max_iterations=3,
        streaming=True,
        stream_callback="engine-stream-callback",
        agent_id="agent-1",
        api_client_override="api-override",
        model_config_override="model-override",
    )
    owner.engine.run_task.assert_not_awaited()
    assert trace_calls[0][0][5] is False


@pytest.mark.asyncio
async def test_run_engine_process_dispatches_single_turn() -> None:
    owner = _owner()
    trace_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    result = await _run_dispatch(
        owner,
        multi_step=False,
        trace_calls=trace_calls,
    )

    assert result == {"status": "single"}
    owner.engine.run_single_turn.assert_awaited_once_with(
        "hello",
        image_paths=["image.png"],
        streaming=True,
        stream_callback="engine-stream-callback",
        agent_id="agent-1",
        api_client_override="api-override",
        model_config_override="model-override",
    )
    owner.engine.run_task.assert_not_awaited()
    owner.engine.run_response.assert_not_awaited()
    assert trace_calls == []
