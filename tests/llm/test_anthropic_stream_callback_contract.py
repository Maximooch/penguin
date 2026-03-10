"""Regression tests for Anthropic streaming callback contract."""

from __future__ import annotations

import logging

import pytest

from penguin.llm.adapters.anthropic import AnthropicAdapter


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
