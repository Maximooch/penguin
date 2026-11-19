"""A provider request's lifecycle status moves through one guarded function."""

from __future__ import annotations

import asyncio
import itertools

import httpx
import pytest

from penguin.llm.contracts import (
    ErrorCategory,
    FinishReason,
    LLMError,
    LLMRequestLifecycle,
    ProviderRequestStatus,
    next_request_status,
)
from tests.llm.test_link_runtime_recovery import make_provider

S = ProviderRequestStatus
FINAL = {S.COMPLETED, S.CANCELLED}
ENDED = {S.DISCONNECTED, S.FAILED}
ACTIVE = {S.PENDING, S.RUNNING, S.STREAMING}


def _lifecycle(status: ProviderRequestStatus) -> LLMRequestLifecycle:
    return LLMRequestLifecycle(
        request_id="req", provider="p", model="m", status=status, started_at=1.0
    )


def test_a_final_status_never_changes() -> None:
    for current, requested in itertools.product(FINAL, S):
        assert next_request_status(current, requested) is current


def test_a_failed_attempt_can_only_be_retried() -> None:
    for current, requested in itertools.product(ENDED, S):
        expected = requested if requested in {current, S.RETRYING} else current
        assert next_request_status(current, requested) is expected


def test_only_a_failed_attempt_is_retried() -> None:
    for current in ACTIVE:
        assert next_request_status(current, S.RETRYING) is current
        for requested in set(S) - {S.RETRYING}:
            assert next_request_status(current, requested) is requested


def test_a_retry_ends_cancelled_or_failed() -> None:
    for requested in S:
        expected = (
            requested
            if requested in {S.RETRYING, S.CANCELLED, S.FAILED}
            else S.RETRYING
        )
        assert next_request_status(S.RETRYING, requested) is expected


def test_advance_ignores_a_refused_transition_entirely() -> None:
    lifecycle = _lifecycle(S.RUNNING)
    error = LLMError(message="boom", category=ErrorCategory.RUNTIME)
    assert lifecycle.advance(S.FAILED, error=error, now=5.0) is True
    assert lifecycle.ended_at == 5.0

    applied = lifecycle.advance(
        S.STREAMING, finish_reason=FinishReason.STOP, event_type="late", now=9.0
    )

    assert applied is False
    assert lifecycle.status is S.FAILED
    assert lifecycle.ended_at == 5.0
    assert lifecycle.finish_reason is None
    assert lifecycle.last_event_type is None
    assert lifecycle.error is error


def test_finish_picks_the_status_from_the_error() -> None:
    network = LLMError(message="reset", category=ErrorCategory.NETWORK)
    runtime = LLMError(message="bad", category=ErrorCategory.RUNTIME)

    for error, expected in ((network, S.DISCONNECTED), (runtime, S.FAILED)):
        lifecycle = _lifecycle(S.STREAMING)
        lifecycle.finish(error=error, finish_reason=FinishReason.ERROR)
        assert lifecycle.status is expected
        assert lifecycle.error is error

    lifecycle = _lifecycle(S.STREAMING)
    lifecycle.finish(error=None, finish_reason=FinishReason.STOP)
    assert lifecycle.status is S.COMPLETED
    assert lifecycle.finish_reason is FinishReason.STOP


@pytest.mark.asyncio
async def test_link_marks_the_attempt_retrying_while_it_waits_to_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiting = asyncio.Event()

    async def backoff(_seconds: float) -> None:
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("penguin.llm.providers.link.provider.asyncio.sleep", backoff)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("broker down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = make_provider(client)
        task = asyncio.create_task(
            provider.get_response([{"role": "user", "content": "hi"}])
        )
        await asyncio.wait_for(waiting.wait(), 1)

        assert provider.get_last_request_lifecycle().status is S.RETRYING

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert provider.get_last_request_lifecycle().status is S.CANCELLED
