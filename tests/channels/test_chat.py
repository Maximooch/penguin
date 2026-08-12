from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any

import pytest

from penguin.channels.chat import ChatProcessRequest, execute_chat_turn
from penguin.channels.fake import FakeChannel
from penguin.channels.schema import ChannelAddress, DeliveryRequest
from penguin.core_runtime import process_lifecycle
from penguin.system.execution_context import (
    ExecutionContext,
    get_current_execution_context,
)


class FakeCore:
    def __init__(self) -> None:
        self.active_by_session: dict[str, int] = {}
        self.max_by_session: dict[str, int] = {}
        self.all_active = 0
        self.max_all_active = 0
        self.release = asyncio.Event()
        self.started = asyncio.Queue()
        self.seen_contexts: list[ExecutionContext | None] = []
        self.seen_process_kwargs: list[dict[str, Any]] = []

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        session_id = str(kwargs.get("conversation_id") or "")
        self.active_by_session[session_id] = (
            self.active_by_session.get(session_id, 0) + 1
        )
        self.max_by_session[session_id] = max(
            self.max_by_session.get(session_id, 0),
            self.active_by_session[session_id],
        )
        self.all_active += 1
        self.max_all_active = max(self.max_all_active, self.all_active)
        self.seen_contexts.append(get_current_execution_context())
        self.seen_process_kwargs.append(kwargs)
        await self.started.put(session_id)
        await self.release.wait()
        callback = kwargs.get("stream_callback")
        if callback is not None:
            await callback("hello", "assistant")
        self.active_by_session[session_id] -= 1
        self.all_active -= 1
        return {"assistant_response": session_id, "action_results": []}


def _request(session_id: str, callback: Any = None) -> ChatProcessRequest:
    return ChatProcessRequest(
        input_data={"text": "hi"},
        session_id=session_id,
        execution_context=ExecutionContext(
            session_id=session_id,
            conversation_id=session_id,
            directory=f"/tmp/{session_id}",
            request_id=f"request-{session_id}",
        ),
        stream_callback=callback,
    )


@pytest.mark.asyncio
async def test_same_session_turns_are_serialized_and_tracked() -> None:
    core = FakeCore()
    first = asyncio.create_task(execute_chat_turn(core, _request("one")))
    assert await core.started.get() == "one"
    second = asyncio.create_task(execute_chat_turn(core, _request("one")))
    await asyncio.sleep(0)

    assert core.max_by_session["one"] == 1
    assert len(core._opencode_process_tasks["one"]) == 2

    core.release.set()
    await asyncio.gather(first, second)
    assert core.max_by_session["one"] == 1
    assert core._opencode_process_tasks == {}


@pytest.mark.asyncio
async def test_different_sessions_can_run_concurrently_with_isolated_context() -> None:
    core = FakeCore()
    first = asyncio.create_task(execute_chat_turn(core, _request("one")))
    second = asyncio.create_task(execute_chat_turn(core, _request("two")))
    assert {await core.started.get(), await core.started.get()} == {"one", "two"}

    assert core.max_all_active == 2
    assert {context.session_id for context in core.seen_contexts if context} == {
        "one",
        "two",
    }

    core.release.set()
    await asyncio.gather(first, second)


@pytest.mark.asyncio
async def test_stream_callback_is_forwarded() -> None:
    core = FakeCore()
    chunks: list[tuple[str, str]] = []

    async def callback(chunk: str, message_type: str) -> None:
        chunks.append((chunk, message_type))

    turn = asyncio.create_task(execute_chat_turn(core, _request("one", callback)))
    await core.started.get()
    core.release.set()
    result = await turn

    assert result["assistant_response"] == "one"
    assert chunks == [("hello", "assistant")]


@pytest.mark.asyncio
async def test_cancelled_waiter_is_untracked() -> None:
    core = FakeCore()
    first = asyncio.create_task(execute_chat_turn(core, _request("one")))
    await core.started.get()
    second = asyncio.create_task(execute_chat_turn(core, _request("one")))
    await asyncio.sleep(0)
    second.cancel()

    with pytest.raises(asyncio.CancelledError):
        await second
    assert core._opencode_process_tasks["one"] == {first}

    core.release.set()
    await first
    assert core._opencode_process_tasks == {}


@pytest.mark.asyncio
async def test_runtime_resolver_runs_inside_session_gate() -> None:
    core = FakeCore()
    gate = process_lifecycle.get_session_request_gate(core, "one")
    resolved = asyncio.Event()

    async def resolve_runtime() -> tuple[object, object]:
        assert gate.locked()
        resolved.set()
        return object(), object()

    request = replace(_request("one"), runtime_resolver=resolve_runtime)
    async with gate:
        turn = asyncio.create_task(execute_chat_turn(core, request))
        await asyncio.sleep(0)
        assert not resolved.is_set()

    await resolved.wait()
    await core.started.get()
    core.release.set()
    await turn


@pytest.mark.asyncio
async def test_runtime_resolver_is_serialized_against_session_writer() -> None:
    core = FakeCore()
    gate = process_lifecycle.get_session_request_gate(core, "one")
    resolver_started = asyncio.Event()
    release_resolver = asyncio.Event()
    writer_started = asyncio.Event()
    writer_finished = asyncio.Event()
    model_config = object()
    api_client = object()
    updated_model_config = object()
    runtime = {"model_config": model_config, "api_client": api_client}

    async def resolve_runtime() -> tuple[object, object]:
        resolver_started.set()
        await release_resolver.wait()
        return runtime["model_config"], runtime["api_client"]

    async def write_session_preferences() -> None:
        writer_started.set()
        async with gate:
            runtime["model_config"] = updated_model_config
            writer_finished.set()

    request = replace(_request("one"), runtime_resolver=resolve_runtime)
    turn = asyncio.create_task(execute_chat_turn(core, request))
    await resolver_started.wait()
    writer = asyncio.create_task(write_session_preferences())
    await writer_started.wait()
    await asyncio.sleep(0)
    assert not writer_finished.is_set()

    release_resolver.set()
    await core.started.get()
    assert not writer_finished.is_set()
    assert core.seen_process_kwargs[-1]["model_config_override"] is model_config
    assert core.seen_process_kwargs[-1]["api_client_override"] is api_client

    core.release.set()
    await turn
    await writer
    assert writer_finished.is_set()
    assert runtime["model_config"] is updated_model_config


@pytest.mark.asyncio
async def test_fake_channel_executes_streams_completes_and_delivers() -> None:
    core = FakeCore()
    channel = FakeChannel()
    turn = asyncio.create_task(channel.execute(core, _request("one")))
    await core.started.get()
    core.release.set()

    result = await turn
    delivery = DeliveryRequest(
        delivery_id="delivery-1",
        address=ChannelAddress("fake", "account", "chat"),
        kind="text",
        payload={"text": "done"},
    )
    await channel.deliver(delivery)

    assert result["assistant_response"] == "one"
    assert [(update.text, update.final) for update in channel.streams] == [
        ("hello", False),
        ("one", True),
    ]
    assert channel.deliveries == [delivery]


@pytest.mark.asyncio
async def test_fake_channel_can_cancel_an_active_turn() -> None:
    core = FakeCore()
    channel = FakeChannel()
    turn = asyncio.create_task(channel.execute(core, _request("one")))
    await core.started.get()

    assert channel.cancel_all() == 1
    with pytest.raises(asyncio.CancelledError):
        await turn
    assert channel.cancel_all() == 0
