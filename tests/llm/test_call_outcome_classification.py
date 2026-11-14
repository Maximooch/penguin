"""A provider attempt's outcome is classified by one rule everywhere."""

from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from penguin.llm.contracts import (
    ErrorCategory,
    LLMCallStatus,
    LLMError,
    LLMRequestLifecycle,
    ProviderRequestStatus,
    classify_call_outcome,
)
from penguin.llm.runtime import _get_response_result

S = ProviderRequestStatus
RETRYABLE = LLMError(message="reset", category=ErrorCategory.NETWORK, retryable=True)
FATAL = LLMError(message="denied", category=ErrorCategory.AUTH, retryable=False)


def test_cancellation_wins_over_any_error() -> None:
    for error in (None, RETRYABLE, FATAL):
        assert (
            classify_call_outcome(lifecycle_status=S.CANCELLED, error=error)
            is LLMCallStatus.CANCELLED
        )


def test_an_error_is_never_a_completed_call() -> None:
    for status, error in itertools.product(
        [None, *set(S) - {S.CANCELLED}], (RETRYABLE, FATAL)
    ):
        expected = (
            LLMCallStatus.RETRYABLE_ERROR
            if error.retryable
            else LLMCallStatus.FATAL_ERROR
        )
        assert classify_call_outcome(lifecycle_status=status, error=error) is expected


def test_a_failed_request_without_an_error_is_still_a_failure() -> None:
    for status in (S.DISCONNECTED, S.FAILED, S.RETRYING):
        assert (
            classify_call_outcome(lifecycle_status=status, error=None)
            is LLMCallStatus.FATAL_ERROR
        )
    for status in (None, S.PENDING, S.RUNNING, S.STREAMING, S.COMPLETED):
        assert (
            classify_call_outcome(lifecycle_status=status, error=None)
            is LLMCallStatus.COMPLETED
        )


class _PlainClient:
    """An API client without typed results, as some callers pass."""

    def __init__(
        self, status: ProviderRequestStatus, error: Optional[LLMError]
    ) -> None:
        self._lifecycle = LLMRequestLifecycle(
            request_id="req", provider="p", model="m", status=status, error=error
        )
        self._error = error

    async def get_response(self, *_args: Any, **_kwargs: Any) -> str:
        return "partial"

    def get_last_error(self) -> Optional[LLMError]:
        return self._error

    def get_last_request_lifecycle(self) -> LLMRequestLifecycle:
        return self._lifecycle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (S.CANCELLED, LLMCallStatus.CANCELLED),
        (S.FAILED, LLMCallStatus.FATAL_ERROR),
        (S.COMPLETED, LLMCallStatus.COMPLETED),
    ],
)
async def test_runtime_fallback_uses_the_same_rule(
    status: ProviderRequestStatus, expected: LLMCallStatus
) -> None:
    result = await _get_response_result(
        api_client=_PlainClient(status, None),
        messages=[],
        stream=False,
        stream_callback=None,
        extra_kwargs={},
    )

    assert result.status is expected


@pytest.mark.asyncio
async def test_runtime_fallback_reads_the_handler_lifecycle() -> None:
    handler = _PlainClient(S.CANCELLED, None)
    client = SimpleNamespace(client_handler=handler, get_response=handler.get_response)

    result = await _get_response_result(
        api_client=client,
        messages=[],
        stream=False,
        stream_callback=None,
        extra_kwargs={},
    )

    assert result.status is LLMCallStatus.CANCELLED
