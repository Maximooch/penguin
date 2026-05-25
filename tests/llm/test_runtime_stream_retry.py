"""Tests for provider runtime stream retry boundaries."""

from __future__ import annotations

from typing import Any

import pytest

from penguin.llm.contracts import (
    ErrorCategory,
    LLMCallResult,
    LLMCallStatus,
    LLMError,
    LLMProviderError,
)
from penguin.llm.runtime import call_with_retry


class _ResultClient:
    def __init__(self, results: list[dict[str, Any]]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []
        self.client_handler = object()

    async def get_response_result(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool | None = None,
        stream_callback: Any = None,
        **kwargs: Any,
    ) -> LLMCallResult:
        self.calls.append(
            {
                "messages": messages,
                "stream": stream,
                "stream_callback": stream_callback,
                "kwargs": kwargs,
            }
        )
        result = self.results.pop(0)
        callback = result.get("callback")
        if callback and stream_callback:
            chunk, message_type = callback
            await stream_callback(chunk, message_type)
        return LLMCallResult(
            text=str(result.get("text") or ""),
            status=result.get("status", LLMCallStatus.COMPLETED),
            error=result.get("error"),
        )


def _retryable_stream_error() -> LLMError:
    return LLMError(
        message="stream disconnected",
        category=ErrorCategory.NETWORK,
        retryable=True,
        provider="openai",
        model="gpt-test",
    )


@pytest.mark.asyncio
async def test_call_with_retry_replays_after_reasoning_only_stream_failure() -> None:
    retryable_error = _retryable_stream_error()
    client = _ResultClient(
        [
            {
                "callback": ("thinking", "reasoning"),
                "text": "Error: LLM network request failed. Diagnostic ID: first",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": retryable_error,
            },
            {"text": "recovered answer"},
        ]
    )
    streamed: list[tuple[str, str]] = []

    async def collect(chunk: str, message_type: str = "assistant") -> None:
        streamed.append((chunk, message_type))

    result = await call_with_retry(
        api_client=client,
        messages=[{"role": "user", "content": "hi"}],
        streaming=True,
        stream_callback=collect,
        extra_kwargs={},
    )

    assert result == "recovered answer"
    assert [call["stream"] for call in client.calls] == [True, False]
    assert streamed == [
        ("thinking", "reasoning"),
        ("recovered answer", "assistant"),
    ]


@pytest.mark.asyncio
async def test_call_with_retry_does_not_replay_after_assistant_chunk_failure() -> None:
    retryable_error = _retryable_stream_error()
    client = _ResultClient(
        [
            {
                "callback": ("partial answer", "assistant"),
                "text": "Error: LLM network request failed. Diagnostic ID: first",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": retryable_error,
            },
            {"text": "should not be requested"},
        ]
    )
    streamed: list[tuple[str, str]] = []

    async def collect(chunk: str, message_type: str = "assistant") -> None:
        streamed.append((chunk, message_type))

    with pytest.raises(LLMProviderError):
        await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "hi"}],
            streaming=True,
            stream_callback=collect,
            extra_kwargs={},
        )

    assert len(client.calls) == 1
    assert streamed == [("partial answer", "assistant")]
