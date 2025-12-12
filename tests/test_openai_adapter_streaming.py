from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.model_config import ModelConfig


@dataclass(frozen=True)
class _DummyStreamEvent:
    """Minimal stream event shape used by OpenAIAdapter streaming."""

    type: str
    delta: str = ""


class _DummyResponseStream:
    """Async context manager + iterator that mimics OpenAI SDK response streams."""

    def __init__(self, *, deltas: list[str], final_text: str) -> None:
        self._events: list[_DummyStreamEvent] = [
            _DummyStreamEvent(type="response.output_text.delta", delta=d)
            for d in deltas
        ]
        self._idx = 0
        self._final_text = final_text

    async def __aenter__(self) -> _DummyResponseStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object | None,
    ) -> bool:
        return False

    def __aiter__(self) -> _DummyResponseStream:
        return self

    async def __anext__(self) -> _DummyStreamEvent:
        if self._idx >= len(self._events):
            raise StopAsyncIteration
        ev = self._events[self._idx]
        self._idx += 1
        return ev

    async def get_final_response(self) -> Any:
        return SimpleNamespace(output_text=self._final_text)


class _DummyResponses:
    """Stub for `client.responses` used by OpenAIAdapter."""

    def __init__(self) -> None:
        self.last_stream_kwargs: dict[str, Any] | None = None

    def stream(self, **kwargs: Any) -> _DummyResponseStream:
        self.last_stream_kwargs = dict(kwargs)
        return _DummyResponseStream(deltas=["hel", "lo"], final_text="hello")


class _DummyOpenAIClient:
    """Stub for the OpenAI SDK client on the adapter."""

    def __init__(self) -> None:
        self.responses = _DummyResponses()
        self.api_key = "sk-test"
        self.base_url = "https://example.invalid/v1"


@pytest.mark.asyncio
async def test_openai_adapter_streaming_ignores_stream_options() -> None:
    """Ensure Chat Completions `stream_options` is not forwarded to Responses API."""

    model_config = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=True,
    )
    adapter = OpenAIAdapter(model_config)
    adapter.client = _DummyOpenAIClient()  # type: ignore[assignment]

    result = await adapter.get_response(
        [{"role": "user", "content": "hi"}],
        stream=True,
        stream_options={"include_usage": True},
    )

    assert result == "hello"
    assert adapter.client.responses.last_stream_kwargs is not None
    assert "stream_options" not in adapter.client.responses.last_stream_kwargs
