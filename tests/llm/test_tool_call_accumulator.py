"""Every adapter gathers streamed tool calls with one accumulator and one rule."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.llm.adapters.anthropic import AnthropicAdapter
from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway
from penguin.llm.tool_call_accumulator import ToolCallAccumulator
from tests.llm.test_anthropic_stream_callback_contract import _FakeAsyncClient
from tests.llm.test_openrouter_usage_recovery import _DirectStreamClient

# --- the rule ----------------------------------------------------------------


def test_a_call_is_not_runnable_until_it_closes() -> None:
    acc = ToolCallAccumulator()
    acc.open_call(0, call_id="call_1", name="write_file")
    acc.append_arguments(0, '{"path":"a.py",')

    assert acc.has_open() is True
    assert acc.has_pending() is False

    acc.append_arguments(0, '"content":"x"}')
    acc.close_call(0)

    assert acc.has_open() is False
    assert acc.drain() == [
        {
            "item_id": None,
            "call_id": "call_1",
            "name": "write_file",
            "arguments": '{"path":"a.py","content":"x"}',
        }
    ]
    assert acc.has_pending() is False


def test_identical_calls_without_ids_stay_separate() -> None:
    acc = ToolCallAccumulator()
    acc.add({"name": "read_file", "arguments": '{"path":"a"}'})
    acc.add({"name": "read_file", "arguments": '{"path":"a"}'})

    assert len(acc.drain()) == 2


def test_a_repeated_id_updates_the_same_call() -> None:
    acc = ToolCallAccumulator()
    acc.add({"item_id": "fc_1", "call_id": "call_1", "name": "f", "arguments": ""})
    acc.add({"item_id": "fc_1", "name": "f", "arguments": '{"a":1}'})

    assert acc.drain() == [
        {"item_id": "fc_1", "call_id": "call_1", "name": "f", "arguments": '{"a":1}'}
    ]


def test_a_call_without_a_name_is_never_runnable() -> None:
    acc = ToolCallAccumulator()
    acc.open_call(0, call_id="call_1")
    acc.close_all()
    acc.add({"call_id": "call_2", "arguments": "{}"})

    assert acc.has_pending() is False
    assert acc.drain() == []


def test_discard_drops_open_and_pending_calls() -> None:
    acc = ToolCallAccumulator()
    acc.add({"call_id": "call_1", "name": "f", "arguments": "{}"})
    acc.open_call(1, call_id="call_2", name="g")
    acc.discard()

    assert acc.has_pending() is False
    assert acc.has_open() is False
    assert acc.drain() == []


def test_closing_with_final_arguments_replaces_the_streamed_ones() -> None:
    acc = ToolCallAccumulator()
    acc.open_call("fc_1", item_id="fc_1", call_id="call_1", name="f")
    acc.append_arguments("fc_1", '{"a":')
    acc.close_call("fc_1", arguments='{"a":2}')

    assert acc.drain()[0]["arguments"] == '{"a":2}'


# --- Anthropic: a tool_use block is runnable only when it has ended ---------


class _Block:
    def __init__(self, block_id: str | None, name: str) -> None:
        self.type = "tool_use"
        self.id = block_id
        self.name = name
        self.input: dict[str, Any] = {}


class _Event:
    def __init__(self, event_type: str, index: int = 0, **fields: Any) -> None:
        self.type = event_type
        self.index = index
        for key, value in fields.items():
            setattr(self, key, value)


def _json_delta(index: int, partial: str) -> _Event:
    return _Event(
        "content_block_delta",
        index,
        delta=SimpleNamespace(type="input_json_delta", partial_json=partial),
    )


class _Stream:
    def __init__(self, events: list[_Event]) -> None:
        self._events = list(events)

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> _Event:
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)


def _anthropic(events: list[_Event]) -> AnthropicAdapter:
    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.async_client = _FakeAsyncClient(cast(Any, _Stream(events)))
    adapter.logger = logging.getLogger(__name__)
    adapter.model_config = cast(Any, SimpleNamespace(model="claude-test"))
    return adapter


@pytest.mark.asyncio
async def test_anthropic_streamed_tool_use_is_one_call_with_full_arguments() -> None:
    adapter = _anthropic(
        [
            _Event("content_block_start", 0, content_block=_Block(None, "read_file")),
            _json_delta(0, '{"path":'),
            _json_delta(0, '"a.py"}'),
            _Event("content_block_stop", 0),
            _Event("content_block_start", 1, content_block=_Block(None, "read_file")),
            _json_delta(1, '{"path":"b.py"}'),
            _Event("content_block_stop", 1),
            _Event("message_stop"),
        ]
    )

    await adapter._handle_streaming({"stream": True}, None)

    calls = adapter.get_and_clear_pending_tool_calls()
    assert [json.loads(call["arguments"]) for call in calls] == [
        {"path": "a.py"},
        {"path": "b.py"},
    ]


@pytest.mark.asyncio
async def test_anthropic_tool_use_still_streaming_is_not_runnable() -> None:
    adapter = _anthropic([])
    adapter._record_tool_use_start(
        _Event("content_block_start", 0, content_block=_Block("toolu_1", "edit"))
    )
    adapter._record_tool_use_delta(_json_delta(0, '{"path":"a.py","con'))

    assert adapter.has_pending_tool_call() is False


# --- OpenRouter: a streamed call without an id is kept once ------------------


@pytest.mark.asyncio
async def test_openrouter_id_less_streamed_calls_are_each_kept_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
        )
    )
    gateway._start_request_lifecycle(messages=[], stream=True)

    def _chunk(delta: dict[str, Any], finish: str | None = None) -> str:
        return "data: " + json.dumps(
            {"id": "c", "choices": [{"delta": delta, "finish_reason": finish}]}
        )

    def _call(index: int, arguments: str, name: str | None = None) -> dict:
        function: dict[str, Any] = {"arguments": arguments}
        if name:
            function["name"] = name
        return {"tool_calls": [{"index": index, "function": function}]}

    lines = [
        _chunk(_call(0, '{"path":', "read_file")),
        _chunk(_call(0, '"a"}')),
        _chunk(_call(1, '{"path":"a"}', "read_file")),
        _chunk({}, "tool_calls"),
        "data: [DONE]",
    ]

    await gateway._handle_streaming_response(
        client=cast(Any, _DirectStreamClient(lines)),
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        params={"model": gateway.model_config.model, "messages": []},
        stream_callback=None,
    )

    calls = gateway.get_and_clear_pending_tool_calls()
    assert [(call["name"], call["arguments"]) for call in calls] == [
        ("read_file", '{"path":"a"}'),
        ("read_file", '{"path":"a"}'),
    ]
