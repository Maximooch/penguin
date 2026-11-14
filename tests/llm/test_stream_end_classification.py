"""Every adapter decides how a provider stream ended with one shared rule."""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.llm.adapters import anthropic as anthropic_adapter
from penguin.llm.adapters import openai as openai_adapter
from penguin.llm.adapters.litellm import LiteLLMGateway
from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.contracts import ErrorCategory, FinishReason
from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway
from penguin.llm.stream_end import (
    StreamEnd,
    classify_stream_end,
    finish_reason_for,
    is_stream_failure,
    keeps_tool_calls,
    responses_incomplete_reason,
    stream_output_state,
)
from tests.llm.codex_oauth_fixtures import (
    FakeResponse,
    FakeStreamContext,
    codex_sse,
    codex_text_delta,
)
from tests.llm.test_anthropic_stream_callback_contract import (
    _build_adapter,
    _Chunk,
    _Delta,
    _FakeStream,
)
from tests.llm.test_openrouter_usage_recovery import _DirectStreamClient

# --- the pure rule ---------------------------------------------------------

_EARLY = (None, FinishReason.LENGTH, FinishReason.CONTENT_FILTER)


def _all_inputs() -> list[dict[str, Any]]:
    flags = itertools.product([False, True], repeat=5)
    return [
        {
            "cancelled": cancelled,
            "saw_error": saw_error,
            "saw_terminal": saw_terminal,
            "pending_tool": pending_tool,
            "has_text": has_text,
            "stopped_early": early,
        }
        for cancelled, saw_error, saw_terminal, pending_tool, has_text in flags
        for early in _EARLY
    ]


def test_failures_outrank_everything_else() -> None:
    for inputs in _all_inputs():
        end = classify_stream_end(**inputs)
        if inputs["cancelled"]:
            assert end is StreamEnd.CANCELLED
        elif inputs["saw_error"]:
            assert end is StreamEnd.PROVIDER_ERROR
        elif not inputs["saw_terminal"]:
            assert end is StreamEnd.INCOMPLETE
        else:
            assert not is_stream_failure(end)


def test_tool_calls_survive_only_a_clean_tool_call_end() -> None:
    for inputs in _all_inputs():
        end = classify_stream_end(**inputs)
        clean = (
            not inputs["cancelled"]
            and not inputs["saw_error"]
            and inputs["saw_terminal"]
            and inputs["stopped_early"] is None
            and inputs["pending_tool"]
        )
        assert keeps_tool_calls(end) is clean


def test_finish_reason_follows_the_outcome() -> None:
    assert finish_reason_for(StreamEnd.TEXT) is FinishReason.STOP
    assert finish_reason_for(StreamEnd.EMPTY) is FinishReason.STOP
    assert finish_reason_for(StreamEnd.TOOL_CALLS) is FinishReason.TOOL_CALLS
    assert finish_reason_for(StreamEnd.TRUNCATED) is FinishReason.LENGTH
    assert finish_reason_for(StreamEnd.FILTERED) is FinishReason.CONTENT_FILTER
    for end in StreamEnd:
        assert (finish_reason_for(end) is FinishReason.ERROR) is is_stream_failure(end)


def test_output_state_and_incomplete_reason() -> None:
    assert stream_output_state(pending_tool=True, has_text=True) == "tool_call"
    assert stream_output_state(pending_tool=False, has_text=True) == "text"
    assert stream_output_state(pending_tool=False, has_text=False) == "empty"
    assert (
        responses_incomplete_reason(
            {"incomplete_details": {"reason": "content_filter"}}
        )
        is FinishReason.CONTENT_FILTER
    )
    assert (
        responses_incomplete_reason(
            {"incomplete_details": {"reason": "max_output_tokens"}}
        )
        is FinishReason.LENGTH
    )
    assert responses_incomplete_reason(None) is FinishReason.LENGTH


# --- OpenAI: response.incomplete is a cut-off answer, not a dropped stream --


class _Http:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def stream(self, *_args: Any, **_kwargs: Any) -> FakeStreamContext:
        return FakeStreamContext(FakeResponse(200, lines=self._lines))


class _Pool:
    def __init__(self, lines: list[str]) -> None:
        self._http = _Http(lines)

    async def get_client(self, _base_url: str) -> _Http:
        return self._http


def _openai(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> OpenAIAdapter:
    monkeypatch.setattr(
        openai_adapter.ConnectionPoolManager,
        "get_instance",
        classmethod(lambda cls: _Pool(lines)),
    )
    return OpenAIAdapter(
        ModelConfig(
            model="gpt-5.6-sol",
            provider="openai",
            client_preference="native",
            api_key="sk-test",
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("max_output_tokens", FinishReason.LENGTH),
        ("content_filter", FinishReason.CONTENT_FILTER),
    ],
)
async def test_openai_http_incomplete_response_returns_the_cut_off_text(
    monkeypatch: pytest.MonkeyPatch, reason: str, expected: FinishReason
) -> None:
    adapter = _openai(
        monkeypatch,
        [
            codex_text_delta("cut off he"),
            codex_sse(
                {
                    "type": "response.incomplete",
                    "response": {
                        "incomplete_details": {"reason": reason},
                        "usage": {"input_tokens": 3, "output_tokens": 4},
                    },
                }
            ),
        ],
    )

    text = await adapter._stream_with_http({"model": "gpt-5.6-sol", "input": []}, None)

    assert text == "cut off he"
    assert adapter.get_last_finish_reason() is expected
    assert adapter.get_last_error() is None
    assert adapter.has_pending_tool_call() is False


# --- OpenRouter: a mid-stream error discards the tool call being built ------


def _tool_chunk() -> dict[str, Any]:
    return {
        "id": "chatcmpl-test",
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_partial",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"path":"a.py","content":"impor',
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ],
    }


@pytest.mark.asyncio
async def test_openrouter_midstream_error_drops_the_partial_tool_call(
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
    error_chunk = {
        "id": "chatcmpl-test",
        "choices": [{"delta": {}, "finish_reason": "error"}],
        "error": {
            "code": "server_error",
            "message": "upstream died",
            "metadata": {"provider_name": "fixture-provider"},
        },
    }
    lines = [
        f"data: {json.dumps(_tool_chunk())}",
        f"data: {json.dumps(error_chunk)}",
    ]

    await gateway._handle_streaming_response(
        client=cast(Any, _DirectStreamClient(lines)),
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        params={"model": gateway.model_config.model, "messages": []},
        stream_callback=None,
    )

    assert gateway.get_last_finish_reason() is FinishReason.ERROR
    assert gateway.has_pending_tool_call() is False
    assert gateway.get_and_clear_pending_tool_calls() == []
    error = gateway.get_last_error()
    assert error is not None
    assert error.message == "upstream died"


# --- LiteLLM: a failed or cancelled stream is not a short answer -----------


class _LiteLLMStream:
    def __init__(self, chunks: list[str], then: BaseException) -> None:
        self._chunks = list(chunks)
        self._then = then

    def __aiter__(self) -> _LiteLLMStream:
        return self

    async def __anext__(self) -> Any:
        if not self._chunks:
            raise self._then
        text = self._chunks.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
        )


def _litellm_gateway(stream: _LiteLLMStream) -> LiteLLMGateway:
    gateway = LiteLLMGateway.__new__(LiteLLMGateway)
    gateway.model_config = cast(
        Any, SimpleNamespace(model="openai/gpt-test", provider="openai")
    )
    gateway._last_error = None

    async def _acompletion(**_kwargs: Any) -> _LiteLLMStream:
        return stream

    gateway._litellm = SimpleNamespace(acompletion=_acompletion)
    return gateway


@pytest.mark.asyncio
async def test_litellm_stream_failure_is_raised_not_returned() -> None:
    gateway = _litellm_gateway(_LiteLLMStream(["partial"], RuntimeError("boom")))
    seen: list[str] = []

    with pytest.raises(RuntimeError, match="boom"):
        await gateway._handle_streaming({}, seen.append, "req")

    assert seen == ["partial"]


@pytest.mark.asyncio
async def test_litellm_stream_cancellation_propagates() -> None:
    gateway = _litellm_gateway(_LiteLLMStream(["partial"], asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        await gateway._handle_streaming({}, None, "req")


# --- Anthropic: no fixed cap on stream length; errors stay out of the text --


@pytest.mark.asyncio
async def test_anthropic_long_stream_is_not_cut_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Each clock reading is 20 s after the last: the stream takes minutes.
    clock = itertools.count(0.0, 20.0)
    monkeypatch.setattr(
        anthropic_adapter, "time", SimpleNamespace(time=lambda: next(clock))
    )
    adapter = _build_adapter(
        _FakeStream(
            [
                _Chunk("content_block_delta", _Delta("text_delta", text="a long ")),
                _Chunk("content_block_delta", _Delta("text_delta", text="answer")),
                _Chunk("message_stop"),
            ]
        )
    )

    text = await adapter._handle_streaming({"stream": True}, None)

    assert text == "a long answer"
    assert adapter.get_last_error() is None
    assert adapter.get_last_finish_reason() is FinishReason.STOP


class _FailingStream(_FakeStream):
    def __init__(self, chunks: list[_Chunk], error: Exception) -> None:
        super().__init__(chunks)
        self._error = error

    async def __anext__(self) -> _Chunk:
        if not self._chunks:
            raise self._error
        return self._chunks.pop(0)


@pytest.mark.asyncio
async def test_anthropic_stream_exception_is_not_streamed_as_assistant_text() -> None:
    adapter = _build_adapter(
        _FailingStream(
            [_Chunk("content_block_delta", _Delta("text_delta", text="partial"))],
            TimeoutError("read timed out"),
        )
    )
    adapter.logger = logging.getLogger(__name__)
    adapter.model_config = cast(Any, SimpleNamespace(model="claude-test"))
    received: list[tuple[str, str]] = []

    async def callback(chunk: str, message_type: str) -> None:
        received.append((chunk, message_type))

    await adapter._handle_streaming({"stream": True}, callback)

    assert received == [("partial", "assistant")]
    error = adapter.get_last_error()
    assert error is not None
    assert error.category == ErrorCategory.TIMEOUT
    assert error.retryable is True
    assert adapter.get_last_finish_reason() is FinishReason.ERROR
    assert adapter.has_pending_tool_call() is False
