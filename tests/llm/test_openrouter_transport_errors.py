"""Classification of unexpected transport exceptions in the OpenRouter adapter.

Mid-stream upstream disconnects often surface as httpx/asyncio exceptions whose
``str()`` is empty. Text-based categorization then falls through to RUNTIME
(non-retryable), so the engine stops instead of replaying a reasoning-only
partial. These tests pin type-based classification.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from penguin.llm.adapters.openrouter import OpenRouterGateway
from penguin.llm.contracts import ErrorCategory
from penguin.llm.provider_transform import build_llm_error
from penguin.llm.runtime import should_retry_provider_failure


@pytest.mark.parametrize(
    ("exc", "category"),
    [
        (httpx.ReadError(""), ErrorCategory.NETWORK),
        (httpx.RemoteProtocolError(""), ErrorCategory.NETWORK),
        (httpx.ConnectError(""), ErrorCategory.NETWORK),
        (httpx.ReadTimeout(""), ErrorCategory.TIMEOUT),
        (asyncio.TimeoutError(), ErrorCategory.TIMEOUT),
    ],
)
def test_blank_transport_errors_are_retryable(
    exc: BaseException, category: ErrorCategory
) -> None:
    message, resolved = OpenRouterGateway._describe_unexpected_error(exc)

    assert resolved is category
    assert type(exc).__name__ in message
    error = build_llm_error(message=message, provider="openrouter", category=resolved)
    assert error.retryable is True


def test_non_transport_error_keeps_text_classification() -> None:
    message, resolved = OpenRouterGateway._describe_unexpected_error(
        ValueError("boom")
    )

    assert resolved is None
    assert "boom" in message
    error = build_llm_error(message=message, provider="openrouter", category=resolved)
    assert error.category is ErrorCategory.RUNTIME
    assert error.retryable is False


@pytest.mark.parametrize(
    ("streamed_assistant_chunk", "pending_tool_call", "expected"),
    [
        (False, False, True),  # reasoning-only partial: safe to replay
        (True, False, False),  # visible text already streamed: don't duplicate
        (False, True, False),  # tool call in flight: don't replay
    ],
)
def test_blank_disconnect_replay_policy(
    streamed_assistant_chunk: bool, pending_tool_call: bool, expected: bool
) -> None:
    message, category = OpenRouterGateway._describe_unexpected_error(
        httpx.ReadError("")
    )
    error = build_llm_error(message=message, provider="openrouter", category=category)

    assert (
        should_retry_provider_failure(
            provider_error=error,
            response=f"[Error: {message}]",
            streamed_assistant_chunk=streamed_assistant_chunk,
            pending_tool_call=pending_tool_call,
        )
        is expected
    )
