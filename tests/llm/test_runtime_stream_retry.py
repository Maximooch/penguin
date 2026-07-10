"""Tests for provider runtime stream retry boundaries."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import Any

import pytest

from penguin.llm import runtime as runtime_module
from penguin.llm.contracts import (
    ErrorCategory,
    LLMCallResult,
    LLMCallStatus,
    LLMError,
    LLMProviderError,
)
from penguin.llm.runtime import call_with_retry
from penguin.utils.errors import LLMEmptyResponseError


class _ResultClient:
    def __init__(
        self,
        results: list[dict[str, Any]],
        *,
        client_handler: Any | None = None,
    ) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []
        self.client_handler = client_handler or object()

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
            streamed_assistant_chunks=bool(
                result.get("streamed_assistant_chunks", False)
            ),
            pending_tool_call=bool(result.get("pending_tool_call", False)),
            provider_data=dict(result.get("provider_data") or {}),
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
    delays: list[float] = []

    async def collect(chunk: str, message_type: str = "assistant") -> None:
        streamed.append((chunk, message_type))

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    result = await call_with_retry(
        api_client=client,
        messages=[{"role": "user", "content": "hi"}],
        streaming=True,
        stream_callback=collect,
        extra_kwargs={},
        retry_sleep=fake_sleep,
        retry_random=lambda: 0.5,
    )

    assert result == "recovered answer"
    assert [call["stream"] for call in client.calls] == [True, False]
    assert streamed == [
        ("thinking", "reasoning"),
        ("recovered answer", "assistant"),
    ]
    assert delays == [0.25]


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


@pytest.mark.asyncio
async def test_call_with_retry_does_not_replay_when_tool_call_is_pending() -> None:
    class _PendingToolHandler:
        def has_pending_tool_call(self) -> bool:
            return True

    retryable_error = _retryable_stream_error()
    client = _ResultClient(
        [
            {
                "text": "Error: LLM network request failed. Diagnostic ID: first",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": retryable_error,
            },
            {"text": "unsafe duplicate"},
        ],
        client_handler=_PendingToolHandler(),
    )

    with pytest.raises(LLMProviderError):
        await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "call tool"}],
            streaming=True,
            stream_callback=lambda *_args: None,
            extra_kwargs={},
        )

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_call_with_retry_uses_error_partial_tool_marker_after_state_release() -> (
    None
):
    """Provider diagnostics prohibit replay after the adapter clears tool state."""

    retryable_error = _retryable_stream_error()
    retryable_error.provider_data["partial_tool_call"] = True
    client = _ResultClient(
        [
            {
                "text": "Error: timed out",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": retryable_error,
            },
            {"text": "unsafe duplicate"},
        ]
    )

    with pytest.raises(LLMProviderError):
        await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "call tool"}],
            streaming=False,
            stream_callback=None,
            extra_kwargs={},
        )

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_call_with_retry_marks_automatic_retry_exhaustion() -> None:
    """The terminal provider error distinguishes replay exhaustion from attempt one."""

    first_error = _retryable_stream_error()
    second_error = _retryable_stream_error()
    client = _ResultClient(
        [
            {
                "text": "Error: first disconnect",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": first_error,
            },
            {
                "text": "Error: second disconnect",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": second_error,
            },
        ]
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    with pytest.raises(LLMProviderError) as raised:
        await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "retry safely"}],
            streaming=True,
            stream_callback=lambda *_args: None,
            extra_kwargs={},
            retry_sleep=fake_sleep,
            retry_random=lambda: 0.5,
        )

    assert [call["stream"] for call in client.calls] == [True, False]
    assert delays == [0.25]
    assert raised.value.error.retryable is True
    assert raised.value.error.provider_data["automatic_retry_exhausted"] is True
    assert raised.value.error.provider_data["attempts"] == 2


@pytest.mark.asyncio
async def test_call_with_retry_never_starts_attempt_three_after_retry_is_empty() -> (
    None
):
    """An empty second attempt exhausts the two-attempt policy."""

    client = _ResultClient(
        [
            {
                "text": "Error: first disconnect",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": _retryable_stream_error(),
            },
            {"text": ""},
            {"text": "forbidden third attempt"},
        ]
    )

    with pytest.raises(LLMEmptyResponseError):
        await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "retry once"}],
            streaming=False,
            stream_callback=None,
            extra_kwargs={},
            retry_sleep=lambda _delay: _completed_awaitable(),
            retry_random=lambda: 0.5,
        )

    assert len(client.calls) == 2


async def _completed_awaitable() -> None:
    """Provide a no-op awaitable for retry timing tests."""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "typed_guard", ["pending_tool_call", "streamed_assistant_chunks"]
)
async def test_call_with_retry_uses_typed_attempt_replay_guards(
    typed_guard: str,
) -> None:
    """Adapter-reported output/tool facts forbid replay after mutable state clears."""

    first: dict[str, Any] = {
        "text": "Error: first disconnect",
        "status": LLMCallStatus.RETRYABLE_ERROR,
        "error": _retryable_stream_error(),
        typed_guard: True,
    }
    client = _ResultClient([first, {"text": "unsafe duplicate"}])

    with pytest.raises(LLMProviderError):
        await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "do not replay"}],
            streaming=False,
            stream_callback=None,
            extra_kwargs={},
        )

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_call_with_retry_honors_retry_after_without_jitter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry-After is a provider minimum, not a jitterable backoff hint."""

    monkeypatch.setenv("PENGUIN_PROVIDER_RETRY_MAX_SECONDS", "5")
    error = _retryable_stream_error()
    error.retry_after_seconds = 1.25
    client = _ResultClient(
        [
            {
                "text": "Error: rate limited",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": error,
            },
            {"text": "recovered"},
        ]
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    result = await call_with_retry(
        api_client=client,
        messages=[{"role": "user", "content": "retry safely"}],
        streaming=False,
        stream_callback=None,
        extra_kwargs={},
        retry_sleep=fake_sleep,
        retry_random=lambda: 0.0,
    )

    assert result == "recovered"
    assert delays == [1.25]


@pytest.mark.asyncio
async def test_call_with_retry_surfaces_retry_after_above_wait_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Penguin does not violate a Retry-After it is unwilling to wait for."""

    monkeypatch.setenv("PENGUIN_PROVIDER_RETRY_MAX_SECONDS", "5")
    error = _retryable_stream_error()
    error.retry_after_seconds = 30.0
    client = _ResultClient(
        [
            {
                "text": "Error: rate limited",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": error,
            },
            {"text": "unsafe early retry"},
        ]
    )
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    with pytest.raises(LLMProviderError) as raised:
        await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "surface throttling"}],
            streaming=False,
            stream_callback=None,
            extra_kwargs={},
            retry_sleep=fake_sleep,
        )

    assert len(client.calls) == 1
    assert delays == []
    assert raised.value.error.retry_after_seconds == 30.0


@pytest.mark.asyncio
async def test_call_with_retry_rejects_nonfinite_backoff_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NaN and infinity cannot disable the finite retry watchdog."""

    monkeypatch.setenv("PENGUIN_PROVIDER_RETRY_BASE_SECONDS", "inf")
    monkeypatch.setenv("PENGUIN_PROVIDER_RETRY_MAX_SECONDS", "nan")
    monkeypatch.setenv("PENGUIN_PROVIDER_RETRY_JITTER_FRACTION", "inf")
    client = _ResultClient([{"text": ""}, {"text": "recovered"}])
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    result = await call_with_retry(
        api_client=client,
        messages=[{"role": "user", "content": "retry safely"}],
        streaming=False,
        stream_callback=None,
        extra_kwargs={},
        retry_sleep=fake_sleep,
        retry_random=lambda: 0.5,
    )

    assert result == "recovered"
    assert delays == [0.25]
    assert math.isfinite(delays[0])


@pytest.mark.asyncio
async def test_call_with_retry_counts_adapter_network_fallback_against_global_cap() -> (
    None
):
    """Two physical sends inside one adapter call leave no runtime replay budget."""

    client = _ResultClient(
        [
            {
                "text": "Error: both transports failed",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": _retryable_stream_error(),
                "provider_data": {"network_attempts": 2},
            },
            {"text": "forbidden third send"},
        ]
    )

    with pytest.raises(LLMProviderError) as raised:
        await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "cap sends"}],
            streaming=False,
            stream_callback=None,
            extra_kwargs={},
        )

    assert len(client.calls) == 1
    assert raised.value.error.provider_data["automatic_retry_exhausted"] is True
    assert raised.value.error.provider_data["attempts"] == 2


@pytest.mark.asyncio
async def test_initial_sync_stream_callback_is_offloaded_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocking sync callback cannot freeze the initial provider attempt."""

    monkeypatch.setenv("PENGUIN_STREAM_CALLBACK_TIMEOUT_SECONDS", "0.02")
    client = _ResultClient([{"callback": ("answer", "assistant"), "text": "answer"}])
    release = threading.Event()
    entered = threading.Event()

    def blocking_callback(_chunk: str, _message_type: str) -> None:
        entered.set()
        release.wait(timeout=1.0)

    started = time.monotonic()
    try:
        result = await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "hello"}],
            streaming=True,
            stream_callback=blocking_callback,
            extra_kwargs={},
        )
    finally:
        release.set()

    assert result == "answer"
    assert entered.is_set()
    assert time.monotonic() - started < 0.5


@pytest.mark.asyncio
async def test_replay_sync_stream_callback_is_offloaded_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final replay delivery uses the same callback watchdog as attempt one."""

    monkeypatch.setenv("PENGUIN_STREAM_CALLBACK_TIMEOUT_SECONDS", "0.02")
    client = _ResultClient(
        [
            {
                "text": "Error: transient",
                "status": LLMCallStatus.RETRYABLE_ERROR,
                "error": _retryable_stream_error(),
            },
            {"text": "recovered"},
        ]
    )
    release = threading.Event()
    entered = threading.Event()

    def blocking_callback(_chunk: str, _message_type: str) -> None:
        entered.set()
        release.wait(timeout=1.0)

    started = time.monotonic()
    try:
        result = await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "hello"}],
            streaming=True,
            stream_callback=blocking_callback,
            extra_kwargs={},
            retry_sleep=lambda _delay: _completed_awaitable(),
        )
    finally:
        release.set()

    assert result == "recovered"
    assert entered.is_set()
    assert time.monotonic() - started < 0.5


@pytest.mark.asyncio
async def test_initial_async_stream_callback_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled async callback is bounded by the same runtime deadline."""

    monkeypatch.setenv("PENGUIN_STREAM_CALLBACK_TIMEOUT_SECONDS", "0.02")
    client = _ResultClient([{"callback": ("answer", "assistant"), "text": "answer"}])
    entered = asyncio.Event()

    async def blocking_callback(_chunk: str, _message_type: str) -> None:
        entered.set()
        await asyncio.Event().wait()

    started = time.monotonic()
    result = await call_with_retry(
        api_client=client,
        messages=[{"role": "user", "content": "hello"}],
        streaming=True,
        stream_callback=blocking_callback,
        extra_kwargs={},
    )

    assert result == "answer"
    assert entered.is_set()
    assert time.monotonic() - started < 0.5


@pytest.mark.asyncio
async def test_sync_callback_uses_bounded_daemon_worker_and_drops_when_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung sync callback neither uses nor blocks asyncio's default executor."""

    monkeypatch.setenv("PENGUIN_STREAM_CALLBACK_TIMEOUT_SECONDS", "0.02")
    executor = runtime_module._RuntimeDaemonCallbackExecutor()
    monkeypatch.setattr(runtime_module, "_RUNTIME_SYNC_CALLBACK_EXECUTOR", executor)

    def forbidden_to_thread(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("default asyncio executor must not be used")

    monkeypatch.setattr(asyncio, "to_thread", forbidden_to_thread)
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    dropped_called = threading.Event()

    def blocking_callback(_chunk: str, _message_type: str) -> None:
        entered.set()
        release.wait(timeout=1.0)
        finished.set()

    def dropped_callback(_chunk: str, _message_type: str) -> None:
        dropped_called.set()

    try:
        await runtime_module._invoke_runtime_stream_callback(
            blocking_callback,
            "first",
            "assistant",
        )
        assert entered.is_set()
        assert executor._worker is not None
        assert executor._worker.daemon is True

        started = time.monotonic()
        await runtime_module._invoke_runtime_stream_callback(
            dropped_callback,
            "second",
            "assistant",
        )
        assert time.monotonic() - started < 0.1
        assert dropped_called.is_set() is False
    finally:
        release.set()

    for _ in range(50):
        if finished.is_set():
            break
        await asyncio.sleep(0.01)
    assert finished.is_set()


@pytest.mark.asyncio
async def test_legacy_error_string_without_metadata_is_fatal() -> None:
    """A legacy error sentinel can never masquerade as completed model text."""

    class _LegacyClient:
        def __init__(self) -> None:
            self.calls = 0
            self.client_handler = object()

        async def get_response(self, *_args: Any, **_kwargs: Any) -> str:
            self.calls += 1
            return "[Error: legacy transport failed]"

    client = _LegacyClient()

    with pytest.raises(LLMProviderError) as raised:
        await call_with_retry(
            api_client=client,
            messages=[{"role": "user", "content": "hello"}],
            streaming=False,
            stream_callback=None,
            extra_kwargs={},
        )

    assert client.calls == 1
    assert raised.value.error.retryable is False
    assert raised.value.error.category is ErrorCategory.RUNTIME
