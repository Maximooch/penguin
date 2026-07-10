"""Regression tests for Anthropic streaming callback contract."""

from __future__ import annotations

import asyncio
import logging

import pytest

from penguin.llm.adapters.anthropic import AnthropicAdapter
from penguin.llm.contracts import ErrorCategory, ProviderRequestStatus
from penguin.llm.model_config import ModelConfig


class _Delta:
    def __init__(self, delta_type: str, text: str = "", thinking: str = "") -> None:
        self.type = delta_type
        self.text = text
        self.thinking = thinking


class _Chunk:
    def __init__(self, chunk_type: str, delta: _Delta | None = None) -> None:
        self.type = chunk_type
        self.delta = delta


class _FinalMessage:
    stop_reason = "end_turn"
    usage = {"input_tokens": 1, "output_tokens": 2}

    def model_dump(self):
        return {
            "stop_reason": self.stop_reason,
            "usage": self.usage,
        }


class _FakeStream:
    def __init__(self, chunks: list[_Chunk]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def get_final_message(self):
        return _FinalMessage()


class _FakeMessages:
    def __init__(self, stream: _FakeStream) -> None:
        self._stream = stream

    async def create(self, **_: object):
        return self._stream


class _FakeAsyncClient:
    def __init__(self, stream: _FakeStream) -> None:
        self.messages = _FakeMessages(stream)


def _build_adapter(stream: _FakeStream) -> AnthropicAdapter:
    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.async_client = _FakeAsyncClient(stream)
    adapter.logger = logging.getLogger(__name__)
    adapter.model_config = ModelConfig(
        model="claude-test",
        provider="anthropic",
        client_preference="native",
    )
    adapter._last_request_lifecycle = None
    return adapter


@pytest.mark.asyncio
async def test_anthropic_stream_awaits_async_two_arg_callback() -> None:
    stream = _FakeStream(
        [
            _Chunk("content_block_delta", _Delta("text_delta", text="hello ")),
            _Chunk("content_block_delta", _Delta("text_delta", text="world")),
            _Chunk("message_stop"),
        ]
    )
    adapter = _build_adapter(stream)
    received: list[tuple[str, str]] = []

    async def callback(chunk: str, message_type: str) -> None:
        received.append((chunk, message_type))

    response = await adapter._handle_streaming({"stream": True}, callback)

    assert response == "hello world"
    assert received == [
        ("hello ", "assistant"),
        ("world", "assistant"),
    ]


@pytest.mark.asyncio
async def test_anthropic_stream_emits_thinking_delta_as_reasoning() -> None:
    stream = _FakeStream(
        [
            _Chunk(
                "content_block_delta",
                _Delta("thinking_delta", thinking="reasoning..."),
            ),
            _Chunk("content_block_delta", _Delta("text_delta", text="answer")),
            _Chunk("message_stop"),
        ]
    )
    adapter = _build_adapter(stream)
    received: list[tuple[str, str]] = []

    async def callback(chunk: str, message_type: str) -> None:
        received.append((chunk, message_type))

    response = await adapter._handle_streaming({"stream": True}, callback)

    assert response == "answer"
    assert received[0] == ("reasoning...", "reasoning")
    assert received[1] == ("answer", "assistant")


@pytest.mark.asyncio
async def test_anthropic_partial_stream_cancellation_is_terminal_and_propagates() -> (
    None
):
    """Cancellation must not turn already-delivered text into a success."""

    entered = asyncio.Event()

    class _PartialThenBlockStream(_FakeStream):
        def __init__(self) -> None:
            super().__init__(
                [_Chunk("content_block_delta", _Delta("text_delta", "partial"))]
            )

        async def __anext__(self):
            if self._chunks:
                return await super().__anext__()
            entered.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    adapter = _build_adapter(_PartialThenBlockStream())
    task = asyncio.create_task(
        adapter.get_response(
            [{"role": "user", "content": "hello"}],
            stream=True,
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=0.5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    error = adapter.get_last_error()
    assert error is not None
    assert error.category is ErrorCategory.RUNTIME
    assert error.retryable is False
    assert error.provider_data["partial_output"] == "partial"
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status is ProviderRequestStatus.CANCELLED
    assert lifecycle.error is error
