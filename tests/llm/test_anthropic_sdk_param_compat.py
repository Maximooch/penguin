"""Regression tests for the Anthropic adapter against the installed SDK surface.

The Anthropic SDK validates ``messages.create()`` keyword arguments client side,
so a request key the installed SDK no longer declares fails every request before
it reaches the provider. ``temperature`` was removed from the Messages API and
silently broke all native Anthropic traffic, so these tests assert the adapter
only forwards keys the installed SDK accepts and that removed sampling controls
are never re-introduced.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.llm.adapters.anthropic import AnthropicAdapter
from penguin.llm.contracts import FinishReason
from penguin.llm.model_config import ModelConfig


def _installed_create_params() -> set[str]:
    """Return the keyword names the installed anthropic SDK accepts."""

    from anthropic.resources.messages import AsyncMessages

    return set(inspect.signature(AsyncMessages.create).parameters)


class _Delta:
    def __init__(self, delta_type: str, text: str = "") -> None:
        self.type = delta_type
        self.text = text


class _Chunk:
    def __init__(self, chunk_type: str, **attrs: Any) -> None:
        self.type = chunk_type
        for key, value in attrs.items():
            setattr(self, key, value)


class _Response:
    content: list[Any] = []
    stop_reason = "end_turn"
    usage: dict[str, Any] = {}

    def model_dump(self) -> dict[str, Any]:
        return {"ok": True}


class _RawStream:
    """Mimics ``messages.create(stream=True)``: no ``get_final_message``."""

    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self) -> "_RawStream":
        return self

    async def __anext__(self) -> Any:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class _Messages:
    def __init__(self, stream: _RawStream) -> None:
        self._stream = stream
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = dict(kwargs)
        if kwargs.get("stream"):
            return self._stream
        return _Response()

    def count_tokens(self, **_: Any) -> Any:
        return SimpleNamespace(input_tokens=42)


def _build_adapter(
    model: str = "claude-opus-5-5",
) -> tuple[AnthropicAdapter, _Messages]:
    config = ModelConfig(
        model=model,
        provider="anthropic",
        client_preference="native",
        api_key="sk-ant",
        streaming_enabled=True,
    )
    stream = _RawStream(
        [
            _Chunk(
                "message_start",
                message=SimpleNamespace(
                    id="msg_1",
                    usage={"input_tokens": 11, "output_tokens": 0},
                ),
            ),
            _Chunk("content_block_delta", delta=_Delta("text_delta", text="hello")),
            _Chunk(
                "message_delta",
                delta=SimpleNamespace(stop_reason="end_turn"),
                usage={"output_tokens": 7},
            ),
            _Chunk("message_stop"),
        ]
    )
    messages = _Messages(stream)
    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.model_config = config
    adapter.async_client = SimpleNamespace(messages=messages)
    adapter.sync_client = SimpleNamespace(
        messages=SimpleNamespace(count_tokens=messages.count_tokens)
    )
    adapter.logger = logging.getLogger(__name__)
    return adapter, messages


@pytest.mark.asyncio
async def test_anthropic_streaming_request_uses_only_installed_sdk_params() -> None:
    adapter, messages = _build_adapter()

    response = await adapter.create_completion(
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )

    assert response == "hello"
    assert messages.last_kwargs is not None
    assert set(messages.last_kwargs) <= _installed_create_params()
    assert messages.last_kwargs["stream"] is True


@pytest.mark.asyncio
async def test_anthropic_non_streaming_request_uses_only_installed_sdk_params() -> None:
    adapter, messages = _build_adapter()

    await adapter.create_completion(
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert messages.last_kwargs is not None
    assert set(messages.last_kwargs) <= _installed_create_params()
    assert messages.last_kwargs["stream"] is False


@pytest.mark.asyncio
async def test_anthropic_never_forwards_sampling_temperature() -> None:
    conversation = [{"role": "user", "content": "hello"}]

    prepared_adapter, _ = _build_adapter()
    prepared = await prepared_adapter.prepare_request(conversation, temperature=0.9)

    non_stream_adapter, non_stream_messages = _build_adapter()
    await non_stream_adapter.create_completion(
        conversation, temperature=0.9, stream=False
    )

    stream_adapter, stream_messages = _build_adapter()
    await stream_adapter.create_completion(conversation, temperature=0.9, stream=True)

    assert "temperature" not in prepared.body
    assert "temperature" not in (non_stream_messages.last_kwargs or {})
    assert "temperature" not in (stream_messages.last_kwargs or {})


@pytest.mark.asyncio
async def test_anthropic_stream_reads_nested_delta_stop_reason_and_usage() -> None:
    adapter, _ = _build_adapter()

    await adapter.create_completion(
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )

    assert adapter.get_last_finish_reason() is FinishReason.STOP
    usage = adapter.get_last_usage()
    assert usage["input_tokens"] == 11
    assert usage["output_tokens"] == 7


def test_anthropic_supports_vision_for_modern_claude_models() -> None:
    adapter, _ = _build_adapter("claude-opus-5-5")
    assert adapter.supports_vision() is True

    legacy_adapter, _ = _build_adapter("claude-instant-1")
    assert legacy_adapter.supports_vision() is False

    other_provider, _ = _build_adapter("gpt-5")
    assert other_provider.supports_vision() is False
