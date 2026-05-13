from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable, cast

from penguin.llm.contracts import FinishReason
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
    error: Any = None


class OpenAIResponse:
    def __init__(
        self,
        *,
        output_text: str,
        usage: dict[str, Any] | None = None,
        response_id: str = "resp-test",
    ) -> None:
        self.id = response_id
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
        if isinstance(event, BaseException):
            raise event
        return event

    async def get_final_response(self) -> OpenAIResponse:
        return self._final_response


class OpenAIResponsesStub:
    def __init__(
        self,
        *,
        stream_response: OpenAIResponseStream | list[OpenAIResponseStream],
        create_response: OpenAIResponse,
    ) -> None:
        self.stream_responses = (
            list(stream_response)
            if isinstance(stream_response, list)
            else [stream_response]
        )
        self.stream_response = self.stream_responses[0]
        self.create_response = create_response
        self.last_stream_kwargs: dict[str, Any] | None = None
        self.last_create_kwargs: dict[str, Any] | None = None

    def stream(self, **kwargs: Any) -> OpenAIResponseStream:
        self.last_stream_kwargs = dict(kwargs)
        if not self.stream_responses:
            raise AssertionError("No queued OpenAI stream response")
        self.stream_response = self.stream_responses.pop(0)
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
        self,
        chunk_type: str,
        delta: AnthropicStreamDelta | None = None,
        *,
        content_block: Any = None,
        index: int = 0,
        error: Any = None,
    ) -> None:
        self.type = chunk_type
        self.delta = delta
        self.content_block = content_block
        self.index = index
        self.error = error


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
        response_id: str = "msg-test",
    ) -> None:
        self.id = response_id
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
        chunk = self._chunks.pop(0)
        if isinstance(chunk, BaseException):
            raise chunk
        return chunk

    async def get_final_message(self) -> AnthropicResponse:
        return self._final_message


class AnthropicMessagesStub:
    def __init__(
        self,
        *,
        stream_response: AnthropicStream | list[AnthropicStream],
        create_response: AnthropicResponse,
    ) -> None:
        self.stream_responses = (
            list(stream_response)
            if isinstance(stream_response, list)
            else [stream_response]
        )
        self.stream_response = self.stream_responses[0]
        self.create_response = create_response
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = dict(kwargs)
        if kwargs.get("stream"):
            if not self.stream_responses:
                raise AssertionError("No queued Anthropic stream response")
            self.stream_response = self.stream_responses.pop(0)
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
        if isinstance(chunk, BaseException):
            raise chunk
        return chunk


class OpenRouterCompletionsStub:
    def __init__(self, *, stream_response: Any | list[Any], create_response: Any) -> None:
        self.stream_responses = (
            list(stream_response)
            if isinstance(stream_response, list)
            else [stream_response]
        )
        self.stream_response = self.stream_responses[0]
        self.create_response = create_response
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = dict(kwargs)
        if kwargs.get("stream"):
            if not self.stream_responses:
                raise AssertionError("No queued OpenRouter stream response")
            self.stream_response = self.stream_responses.pop(0)
            return self.stream_response
        return self.create_response


class OpenRouterClientStub:
    def __init__(self, *, stream_response: Any | list[Any], create_response: Any) -> None:
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
    error: dict[str, Any] | None = None,
) -> Any:
    return SimpleNamespace(
        id="chatcmpl-test",
        model=model,
        error=error,
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
    stream_event_sequences: Iterable[Iterable[OpenAIStreamEvent]] | None = None,
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
    event_sequences = (
        list(stream_event_sequences)
        if stream_event_sequences is not None
        else [stream_events]
    )
    responses = OpenAIResponsesStub(
        stream_response=[
            OpenAIResponseStream(
                events=events,
                final_response=OpenAIResponse(output_text=final_text, usage=usage),
            )
            for events in event_sequences
        ],
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
    interrupt_on_tool_call: bool = False,
    stream_chunk_sequences: Iterable[Iterable[AnthropicStreamChunk]] | None = None,
) -> AnthropicAdapter:
    config = ModelConfig(
        model="claude-sonnet-4-6",
        provider="anthropic",
        client_preference="native",
        api_key="sk-ant",
        streaming_enabled=True,
        reasoning_enabled=reasoning_enabled,
        reasoning_effort="medium" if reasoning_enabled else None,
        interrupt_on_tool_call=interrupt_on_tool_call,
    )
    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.model_config = config
    adapter.logger = logging.getLogger(__name__)
    adapter._last_usage = {}
    adapter._last_error = None
    adapter._last_finish_reason = FinishReason.UNKNOWN
    adapter._last_reasoning = ""
    adapter._last_tool_call = None
    adapter._pending_tool_calls = []
    adapter._tool_use_accs = {}
    adapter._last_request_lifecycle = None
    chunk_sequences = (
        list(stream_chunk_sequences)
        if stream_chunk_sequences is not None
        else [stream_chunks]
    )
    adapter.async_client = cast(
        Any,
        SimpleNamespace(
            messages=AnthropicMessagesStub(
                stream_response=[
                    AnthropicStream(
                        chunks=chunks,
                        final_message=AnthropicResponse(text=final_text, usage=usage),
                    )
                    for chunks in chunk_sequences
                ],
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
    model_id: str = "openai/gpt-4.1-mini",
    stream_chunk_sequences: Iterable[Iterable[Any]] | None = None,
) -> OpenRouterGateway:
    chunk_sequences = (
        list(stream_chunk_sequences)
        if stream_chunk_sequences is not None
        else [stream_chunks]
    )
    stream_response = [OpenRouterStream(chunks) for chunks in chunk_sequences]
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
    monkeypatch.setattr("penguin.llm.adapters.openrouter.AsyncOpenAI", _ClientFactory)

    gateway = OpenRouterGateway(
        ModelConfig(
            model=model_id,
            provider="openrouter",
            client_preference="openrouter",
            api_key="sk-or-v1-fixture",
            streaming_enabled=True,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort="medium" if reasoning_enabled else None,
            interrupt_on_tool_call=interrupt_on_tool_call,
        )
    )

    if reasoning_enabled:

        async def _direct_api_call_with_reasoning(
            request_params: dict[str, Any],
            reasoning_config: dict[str, Any],
            use_streaming: bool,
            stream_callback: Any,
        ) -> str:
            del request_params, reasoning_config
            full_content = ""
            for chunk in stream_chunks:
                choice = chunk.choices[0] if chunk.choices else {}
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason")
                if finish_reason:
                    gateway._set_last_finish_reason(finish_reason)
                reasoning_delta = delta.get("reasoning")
                if reasoning_delta:
                    gateway._append_reasoning(reasoning_delta)
                    if use_streaming and stream_callback:
                        await stream_callback(reasoning_delta, "reasoning")
                content_delta = delta.get("content")
                if content_delta:
                    full_content += content_delta
                    if use_streaming and stream_callback:
                        await stream_callback(content_delta, "assistant")
                tool_calls_delta = delta.get("tool_calls")
                if tool_calls_delta and interrupt_on_tool_call:
                    gateway._store_tool_call(tool_calls_delta)
                    return full_content
                gateway._set_last_usage(getattr(chunk, "usage", None))
            if (
                not gateway.get_last_finish_reason()
                or gateway.get_last_finish_reason() == FinishReason.UNKNOWN
            ):
                gateway._set_last_finish_reason(FinishReason.STOP)
            return full_content or final_text

        gateway._direct_api_call_with_reasoning = _direct_api_call_with_reasoning  # type: ignore[method-assign]
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
