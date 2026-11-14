"""The OpenAI adapter never re-sends a request whose stream already produced output.

Retrying is the runtime's job (``call_with_retry``), which refuses to replay a
request once assistant text has streamed. An adapter-level fallback that
re-requests would bypass that guard and show the answer twice.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.contracts import ErrorCategory, LLMProviderError
from penguin.llm.model_config import ModelConfig


class _Stream:
    def __init__(self, events: list[Any], error: BaseException) -> None:
        self._events = list(events)
        self._error = error

    async def __aenter__(self) -> _Stream:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> Any:
        if not self._events:
            raise self._error
        return self._events.pop(0)


class _Responses:
    def __init__(self, stream: _Stream) -> None:
        self._stream = stream

    def stream(self, **_kwargs: Any) -> _Stream:
        return self._stream


def _adapter(
    monkeypatch: pytest.MonkeyPatch, stream: _Stream
) -> tuple[OpenAIAdapter, list[dict[str, Any]]]:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )
    adapter = OpenAIAdapter(
        ModelConfig(
            model="gpt-5.2",
            provider="openai",
            client_preference="native",
            api_key="sk-test",
            streaming_enabled=True,
        )
    )
    adapter.client = SimpleNamespace(  # type: ignore[assignment]
        responses=_Responses(stream),
        api_key="sk-test",
        base_url="https://example.invalid/v1",
    )
    http_requests: list[dict[str, Any]] = []

    async def _http(params: dict[str, Any], _callback: Any) -> str:
        http_requests.append(params)
        return "from http"

    monkeypatch.setattr(adapter, "_stream_with_http", _http)
    return adapter, http_requests


def _delta(text: str) -> Any:
    return SimpleNamespace(type="response.output_text.delta", delta=text)


@pytest.mark.asyncio
async def test_a_stream_that_drops_after_output_is_not_re_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, http_requests = _adapter(
        monkeypatch,
        _Stream([_delta("partial")], httpx.ReadError("connection reset")),
    )
    chunks: list[tuple[str, str]] = []

    async def on_chunk(chunk: str, message_type: str) -> None:
        chunks.append((chunk, message_type))

    with pytest.raises(LLMProviderError) as raised:
        await adapter.get_response(
            [{"role": "user", "content": "hi"}],
            stream=True,
            stream_callback=on_chunk,
        )

    assert http_requests == []
    assert chunks == [("partial", "assistant")]
    assert raised.value.error.category is ErrorCategory.NETWORK
    assert raised.value.error.retryable is True
    assert adapter.has_pending_tool_call() is False


@pytest.mark.asyncio
async def test_an_sdk_that_cannot_stream_still_falls_back_to_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, http_requests = _adapter(
        monkeypatch,
        _Stream([], TypeError("unexpected keyword argument 'service_tier'")),
    )

    result = await adapter.get_response(
        [{"role": "user", "content": "hi"}], stream=True
    )

    assert result == "from http"
    assert len(http_requests) == 1
