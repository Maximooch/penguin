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
    part: Any = None
    item: Any = None
    item_id: str = ""


class _DummyResponseStream:
    """Async context manager + iterator that mimics OpenAI SDK response streams."""

    def __init__(
        self,
        *,
        deltas: list[str] | None = None,
        final_text: str,
        events: list[_DummyStreamEvent] | None = None,
    ) -> None:
        if events is not None:
            self._events = list(events)
        else:
            self._events = [
                _DummyStreamEvent(type="response.output_text.delta", delta=d)
                for d in (deltas or [])
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


class _DummyResponsesNoDelta(_DummyResponses):
    def stream(self, **kwargs: Any) -> _DummyResponseStream:
        self.last_stream_kwargs = dict(kwargs)
        return _DummyResponseStream(deltas=[], final_text="final-only")


class _DummyResponsesWithReasoning(_DummyResponses):
    def stream(self, **kwargs: Any) -> _DummyResponseStream:
        self.last_stream_kwargs = dict(kwargs)
        return _DummyResponseStream(
            events=[
                _DummyStreamEvent(
                    type="response.reasoning_summary_text.delta",
                    delta="thinking...",
                ),
                _DummyStreamEvent(type="response.output_text.delta", delta="answer"),
            ],
            final_text="answer",
        )


class _DummyResponsesWithToolCall(_DummyResponses):
    def stream(self, **kwargs: Any) -> _DummyResponseStream:
        self.last_stream_kwargs = dict(kwargs)
        return _DummyResponseStream(
            events=[
                _DummyStreamEvent(
                    type="response.output_item.added",
                    item={
                        "type": "function_call",
                        "id": "item_1",
                        "call_id": "call_1",
                        "name": "read_file",
                        "arguments": "",
                    },
                ),
                _DummyStreamEvent(
                    type="response.function_call_arguments.delta",
                    item_id="item_1",
                    delta='{"path":"README.md"}',
                ),
                _DummyStreamEvent(
                    type="response.output_item.done",
                    item={
                        "type": "function_call",
                        "id": "item_1",
                        "call_id": "call_1",
                        "name": "read_file",
                        "arguments": '{"path":"README.md"}',
                        "status": "completed",
                    },
                ),
            ],
            final_text="",
        )


class _DummyOpenAIClient:
    """Stub for the OpenAI SDK client on the adapter."""

    def __init__(self) -> None:
        self.responses = _DummyResponses()
        self.api_key = "sk-test"
        self.base_url = "https://example.invalid/v1"


@pytest.mark.asyncio
async def test_openai_adapter_streaming_ignores_stream_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure Chat Completions `stream_options` is not forwarded to Responses API."""
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )

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


@pytest.mark.asyncio
async def test_openai_adapter_streaming_emits_callback_for_final_only_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )

    model_config = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=True,
    )
    adapter = OpenAIAdapter(model_config)
    adapter.client = _DummyOpenAIClient()  # type: ignore[assignment]
    adapter.client.responses = _DummyResponsesNoDelta()

    chunks: list[tuple[str, str]] = []

    async def on_chunk(chunk: str, message_type: str) -> None:
        chunks.append((chunk, message_type))

    result = await adapter.get_response(
        [{"role": "user", "content": "hi"}],
        stream=True,
        stream_callback=on_chunk,
    )

    assert result == "final-only"
    assert chunks == [("final-only", "assistant")]


@pytest.mark.asyncio
async def test_openai_adapter_streaming_maps_reasoning_summary_to_reasoning_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )

    model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=True,
        reasoning_enabled=True,
        reasoning_effort="medium",
    )
    adapter = OpenAIAdapter(model_config)
    adapter.client = _DummyOpenAIClient()  # type: ignore[assignment]
    adapter.client.responses = _DummyResponsesWithReasoning()

    chunks: list[tuple[str, str]] = []

    async def on_chunk(chunk: str, message_type: str) -> None:
        chunks.append((chunk, message_type))

    result = await adapter.get_response(
        [{"role": "user", "content": "hi"}],
        stream=True,
        stream_callback=on_chunk,
    )

    assert result == "answer"
    assert ("thinking...", "reasoning") in chunks
    assert ("answer", "assistant") in chunks
    assert adapter.client.responses.last_stream_kwargs is not None
    reasoning = adapter.client.responses.last_stream_kwargs.get("reasoning")
    assert isinstance(reasoning, dict)
    assert reasoning.get("summary") == "auto"


def test_openai_adapter_uses_oauth_access_token_when_api_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "oauth-access-token")
    monkeypatch.setenv("OPENAI_ACCOUNT_ID", "acct_test_123")

    class _Client:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str | None = None,
            default_headers: dict[str, str] | None = None,
        ) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.default_headers = default_headers
            self.responses = _DummyResponses()

    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", _Client)

    model_config = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key=None,
        streaming_enabled=True,
    )
    adapter = OpenAIAdapter(model_config)

    assert adapter.client.api_key == "oauth-access-token"  # type: ignore[attr-defined]
    assert adapter.client.default_headers == {  # type: ignore[attr-defined]
        "OpenAI-Account": "acct_test_123"
    }


def test_openai_adapter_normalizes_codex_oauth_display_model_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )

    model_config = ModelConfig(
        model="openai/GPT-5.4-Mini",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
    )
    adapter = OpenAIAdapter(model_config)

    assert adapter._codex_model_for_oauth("openai/GPT-5.4-Mini") == (
        "gpt-5.4-mini",
        False,
    )


@pytest.mark.asyncio
async def test_openai_adapter_streaming_captures_function_calls_without_leaking_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )

    model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=True,
        interrupt_on_tool_call=True,
    )
    adapter = OpenAIAdapter(model_config)
    adapter.client = _DummyOpenAIClient()  # type: ignore[assignment]
    adapter.client.responses = _DummyResponsesWithToolCall()

    chunks: list[tuple[str, str]] = []

    async def on_chunk(chunk: str, message_type: str) -> None:
        chunks.append((chunk, message_type))

    result = await adapter.get_response(
        [{"role": "user", "content": "hi"}],
        stream=True,
        stream_callback=on_chunk,
    )

    assert result == ""
    assert chunks == []
    assert adapter.get_and_clear_last_tool_call() == {
        "item_id": "item_1",
        "call_id": "call_1",
        "name": "read_file",
        "arguments": '{"path":"README.md"}',
    }
    assert adapter.get_and_clear_last_tool_call() is None
