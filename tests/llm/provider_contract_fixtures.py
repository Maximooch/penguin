from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable, cast

from penguin.llm.adapters.anthropic import AnthropicAdapter
from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


@dataclass(frozen=True)
class OpenAIStreamEvent:
    type: str
    delta: str = ""
    part: Any = None
    item: Any = None
    item_id: str = ""


class OpenAIResponse:
    def __init__(
        self,
        *,
        output_text: str,
        usage: dict[str, Any] | None = None,
    ) -> None:
        self.output_text = output_text
        self.usage = dict(usage or {})


class OpenAIResponseStream:
    def __init__(
        self,
        *,
        events: Iterable[OpenAIStreamEvent],
        final_response: OpenAIResponse,
    ) -> None:
        self._events = list(events)
        self._final_response = final_response
        self._idx = 0

    async def __aenter__(self) -> "OpenAIResponseStream":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        return False

    def __aiter__(self) -> "OpenAIResponseStream":
        return self

    async def __anext__(self) -> OpenAIStreamEvent:
        if self._idx >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._idx]
        self._idx += 1
        return event

    async def get_final_response(self) -> OpenAIResponse:
        return self._final_response


class OpenAIResponsesStub:
    def __init__(
        self,
        *,
        stream_response: OpenAIResponseStream,
        create_response: OpenAIResponse,
    ) -> None:
        self.stream_response = stream_response
        self.create_response = create_response
        self.last_stream_kwargs: dict[str, Any] | None = None
        self.last_create_kwargs: dict[str, Any] | None = None

    def stream(self, **kwargs: Any) -> OpenAIResponseStream:
        self.last_stream_kwargs = dict(kwargs)
        return self.stream_response

    async def create(self, **kwargs: Any) -> OpenAIResponse:
        self.last_create_kwargs = dict(kwargs)
        return self.create_response


class OpenAIClientStub:
    def __init__(self, responses: OpenAIResponsesStub) -> None:
        self.responses = responses
        self.api_key = "sk-live-test"
        self.base_url = "https://example.invalid/v1"
        self.default_headers: dict[str, str] = {}


class AnthropicStreamDelta:
    def __init__(self, delta_type: str, *, text: str = "", thinking: str = "") -> None:
        self.type = delta_type
        self.text = text
        self.thinking = thinking


class AnthropicStreamChunk:
    def __init__(
        self, chunk_type: str, delta: AnthropicStreamDelta | None = None
    ) -> None:
        self.type = chunk_type
        self.delta = delta


class AnthropicCountResponse:
    def __init__(self, input_tokens: int) -> None:
        self.input_tokens = input_tokens


class AnthropicUsage:
    def __init__(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class AnthropicResponse:
    def __init__(
        self,
        *,
        text: str,
        usage: AnthropicUsage,
        stop_reason: str = "end_turn",
    ) -> None:
        self.content = [SimpleNamespace(type="text", text=text)]
        self.stop_reason = stop_reason
        self.usage = usage

    def model_dump(self) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": self.content[0].text}],
            "stop_reason": self.stop_reason,
            "usage": vars(self.usage),
        }


class AnthropicStream:
    def __init__(
        self,
        *,
        chunks: Iterable[AnthropicStreamChunk],
        final_message: AnthropicResponse,
    ) -> None:
        self._chunks = list(chunks)
        self._final_message = final_message

    def __aiter__(self) -> "AnthropicStream":
        return self

    async def __anext__(self) -> AnthropicStreamChunk:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def get_final_message(self) -> AnthropicResponse:
        return self._final_message


class AnthropicMessagesStub:
    def __init__(
        self,
        *,
        stream_response: AnthropicStream,
        create_response: AnthropicResponse,
    ) -> None:
        self.stream_response = stream_response
        self.create_response = create_response
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = dict(kwargs)
        if kwargs.get("stream"):
            return self.stream_response
        return self.create_response


class AnthropicSyncMessagesStub:
    def count_tokens(self, **kwargs: Any) -> AnthropicCountResponse:
        del kwargs
        return AnthropicCountResponse(42)


class OpenRouterStream:
    def __init__(self, chunks: Iterable[Any]) -> None:
        self._chunks = list(chunks)
        self._idx = 0

    def __aiter__(self) -> "OpenRouterStream":
        return self

    async def __anext__(self) -> Any:
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


class OpenRouterCompletionsStub:
    def __init__(self, *, stream_response: Any, create_response: Any) -> None:
        self.stream_response = stream_response
        self.create_response = create_response
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = dict(kwargs)
        if kwargs.get("stream"):
            return self.stream_response
        return self.create_response


class OpenRouterClientStub:
    def __init__(self, *, stream_response: Any, create_response: Any) -> None:
        self.chat = SimpleNamespace(
            completions=OpenRouterCompletionsStub(
                stream_response=stream_response,
                create_response=create_response,
            )
        )
        self.base_url = "https://openrouter.ai/api/v1"
        self.api_key = "sk-or-v1-fixture"


def make_openrouter_chunk(
    *,
    model: str,
    content: str | None = None,
    reasoning: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    finish_reason: str | None = None,
    usage: dict[str, Any] | None = None,
) -> Any:
    return SimpleNamespace(
        id="chatcmpl-test",
        model=model,
        choices=[
            {
                "delta": {
                    "content": content,
                    "reasoning": reasoning,
                    "tool_calls": tool_calls,
                },
                "finish_reason": finish_reason,
            }
        ],
        usage=usage,
    )


def build_openai_handler(
    *,
    provider: str,
    stream_events: Iterable[OpenAIStreamEvent],
    final_text: str,
    usage: dict[str, Any],
    interrupt_on_tool_call: bool = False,
    reasoning_enabled: bool = False,
) -> OpenAIAdapter:
    config = ModelConfig(
        model="gpt-5.4",
        provider=provider,
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=True,
        interrupt_on_tool_call=interrupt_on_tool_call,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort="medium" if reasoning_enabled else None,
    )
    adapter_cls = OpenAIAdapter if provider == "openai" else OpenAICompatibleAdapter
    adapter = adapter_cls(config)
    responses = OpenAIResponsesStub(
        stream_response=OpenAIResponseStream(
            events=stream_events,
            final_response=OpenAIResponse(output_text=final_text, usage=usage),
        ),
        create_response=OpenAIResponse(output_text=final_text, usage=usage),
    )
    adapter.client = OpenAIClientStub(responses)  # type: ignore[assignment]
    return adapter


def build_anthropic_handler(
    *,
    stream_chunks: Iterable[AnthropicStreamChunk],
    final_text: str,
    usage: AnthropicUsage,
    reasoning_enabled: bool = False,
) -> AnthropicAdapter:
    config = ModelConfig(
        model="claude-sonnet-4-6",
        provider="anthropic",
        client_preference="native",
        api_key="sk-ant",
        streaming_enabled=True,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort="medium" if reasoning_enabled else None,
    )
    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.model_config = config
    adapter.logger = logging.getLogger(__name__)
    adapter._last_usage = {}
    adapter.async_client = cast(
        Any,
        SimpleNamespace(
            messages=AnthropicMessagesStub(
                stream_response=AnthropicStream(
                    chunks=stream_chunks,
                    final_message=AnthropicResponse(text=final_text, usage=usage),
                ),
                create_response=AnthropicResponse(text=final_text, usage=usage),
            )
        ),
    )
    adapter.sync_client = cast(
        Any,
        SimpleNamespace(messages=AnthropicSyncMessagesStub()),
    )
    return adapter


def build_openrouter_handler(
    monkeypatch: Any,
    *,
    stream_chunks: Iterable[Any],
    final_text: str,
    usage: dict[str, Any],
    reasoning_enabled: bool = False,
    interrupt_on_tool_call: bool = False,
) -> OpenRouterGateway:
    stream_response = OpenRouterStream(stream_chunks)
    create_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=final_text,
                    reasoning="",
                    tool_calls=[],
                ),
                finish_reason="stop",
            )
        ],
        usage=usage,
        error=None,
    )

    class _ClientFactory:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key
            self.chat = SimpleNamespace(
                completions=OpenRouterCompletionsStub(
                    stream_response=stream_response,
                    create_response=create_response,
                )
            )

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fixture")
    monkeypatch.setattr("penguin.llm.openrouter_gateway.AsyncOpenAI", _ClientFactory)

    gateway = OpenRouterGateway(
        ModelConfig(
            model="openai/gpt-4o",
            provider="openrouter",
            client_preference="openrouter",
            api_key="sk-or-v1-fixture",
            streaming_enabled=True,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort="medium" if reasoning_enabled else None,
            interrupt_on_tool_call=interrupt_on_tool_call,
        )
    )
    return gateway


OPENAI_USAGE = {
    "input_tokens": 10,
    "output_tokens": 4,
    "output_tokens_details": {"reasoning_tokens": 2},
    "total_tokens": 14,
}

ANTHROPIC_USAGE = AnthropicUsage(input_tokens=11, output_tokens=5)

OPENROUTER_USAGE = {
    "prompt_tokens": 12,
    "completion_tokens": 6,
    "completion_tokens_details": {"reasoning_tokens": 3},
    "total_tokens": 18,
}
