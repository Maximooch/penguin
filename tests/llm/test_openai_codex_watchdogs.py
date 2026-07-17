"""Deterministic Codex header, idle, total, partial, and cancellation watchdogs."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any, AsyncIterator, ClassVar

import pytest

from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.api_client import APIClient
from penguin.llm.contracts import (
    ErrorCategory,
    LLMCallStatus,
    LLMProviderError,
    ProviderRequestStatus,
)
from penguin.llm.model_config import ModelConfig
from penguin.llm.runtime import call_with_retry

from .codex_oauth_fixtures import (
    FakeResponse,
    SDKClient,
    codex_adapter,
    codex_completed,
    codex_function_call_lines,
    codex_sse,
    codex_text_delta,
    install_oauth_codex_test_auth,
)


class _BlockingHeaderContext:
    """Stream context that never returns response headers."""

    async def __aenter__(self) -> FakeResponse:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        return False


class _ResponseContext:
    """Track response-context release for success, failure, and cancellation."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.exited = 0

    async def __aenter__(self) -> Any:
        return self.response

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        self.exited += 1
        return False


class _BlockingExitContext(_ResponseContext):
    """A response context whose transport cleanup never completes."""

    def __init__(self, response: Any) -> None:
        super().__init__(response)
        self.cancelled = 0

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        self.exited += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return False


class _CancellationIgnoringExitContext(_BlockingExitContext):
    """A broken transport cleanup that keeps running after cancellation."""

    def __init__(self, response: Any) -> None:
        super().__init__(response)
        self.release = asyncio.Event()
        self.finished = asyncio.Event()

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        self.exited += 1
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled += 1
        self.finished.set()
        return False


class _Client:
    """Minimal AsyncClient replacement returning one configured stream context."""

    def __init__(self, context: Any, *, timeout: Any) -> None:
        self.context = context
        self.timeout = timeout

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        return False

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        return self.context


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    context: Any,
) -> list[_Client]:
    """Install deterministic OAuth auth, timeouts, and one fake transport."""

    install_oauth_codex_test_auth(monkeypatch)
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", SDKClient)
    monkeypatch.setenv("PENGUIN_CODEX_HEADER_TIMEOUT_SECONDS", "0.03")
    monkeypatch.setenv("PENGUIN_CODEX_IDLE_TIMEOUT_SECONDS", "0.03")
    monkeypatch.setenv("PENGUIN_CODEX_TOTAL_TIMEOUT_SECONDS", "0.08")
    monkeypatch.setenv("PENGUIN_STREAM_CALLBACK_TIMEOUT_SECONDS", "0.03")
    monkeypatch.setenv("PENGUIN_STREAM_CLEANUP_TIMEOUT_SECONDS", "0.03")
    clients: list[_Client] = []

    def factory(*, timeout: Any) -> _Client:
        client = _Client(context, timeout=timeout)
        clients.append(client)
        return client

    monkeypatch.setattr("penguin.llm.adapters.openai.httpx.AsyncClient", factory)
    return clients


class _BlockingLinesResponse:
    status_code = 200
    headers: ClassVar[dict[str, str]] = {}

    async def aiter_lines(self) -> AsyncIterator[str]:
        await asyncio.Event().wait()
        if False:  # pragma: no cover - establishes this as an async generator
            yield ""


class _ContinuousLinesResponse:
    status_code = 200
    headers: ClassVar[dict[str, str]] = {}

    async def aiter_lines(self) -> AsyncIterator[str]:
        while True:
            await asyncio.sleep(0.005)
            yield codex_sse({"type": "response.created"})


class _PartialThenBlockResponse:
    status_code = 200
    headers: ClassVar[dict[str, str]] = {}

    def __init__(self, lines: list[str], entered: asyncio.Event | None = None) -> None:
        self.lines = lines
        self.entered = entered

    async def aiter_lines(self) -> AsyncIterator[str]:
        for line in self.lines:
            yield line
        if self.entered is not None:
            self.entered.set()
        await asyncio.Event().wait()


class _BlockingErrorBodyResponse:
    """An HTTP error response whose body never finishes downloading."""

    status_code = 503
    headers: ClassVar[dict[str, str]] = {}

    async def aread(self) -> bytes:
        await asyncio.Event().wait()
        return b""


@pytest.mark.asyncio
async def test_codex_header_wait_is_bounded_and_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stream that never returns headers becomes a typed retryable timeout."""

    clients = _install_transport(monkeypatch, _BlockingHeaderContext())
    adapter = codex_adapter()

    with pytest.raises(LLMProviderError) as raised:
        await asyncio.wait_for(
            adapter.get_response(
                [{"role": "user", "content": "hello"}],
                stream=True,
            ),
            timeout=1.0,
        )

    assert raised.value.error.category is ErrorCategory.TIMEOUT
    assert raised.value.error.retryable is True
    assert raised.value.error.provider_data["stage"] == "stream_header_timeout"
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status is ProviderRequestStatus.DISCONNECTED
    assert clients[0].timeout.read == 0.03


@pytest.mark.asyncio
async def test_codex_chunk_idle_wait_is_bounded_and_releases_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Headers without a first/next line trigger the idle watchdog."""

    context = _ResponseContext(_BlockingLinesResponse())
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()

    with pytest.raises(LLMProviderError) as raised:
        await adapter.get_response([{"role": "user", "content": "hello"}], stream=True)

    assert raised.value.error.category is ErrorCategory.TIMEOUT
    assert raised.value.error.provider_data["stage"] == "stream_idle_timeout"
    assert context.exited == 1


@pytest.mark.asyncio
async def test_codex_total_deadline_fires_despite_continuous_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heartbeat-like provider events cannot extend the total attempt forever."""

    context = _ResponseContext(_ContinuousLinesResponse())
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()

    with pytest.raises(LLMProviderError) as raised:
        await adapter.get_response([{"role": "user", "content": "hello"}], stream=True)

    assert raised.value.error.provider_data["stage"] == "stream_total_timeout"
    assert context.exited == 1


@pytest.mark.asyncio
async def test_partial_text_survives_timeout_and_forbids_automatic_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Terminal diagnostics preserve partial text without replaying it."""

    context = _ResponseContext(
        _PartialThenBlockResponse([codex_text_delta("partial answer")])
    )
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()
    chunks: list[str] = []

    async def callback(chunk: str, _message_type: str) -> None:
        chunks.append(chunk)

    with pytest.raises(LLMProviderError) as raised:
        await adapter.get_response(
            [{"role": "user", "content": "hello"}],
            stream=True,
            stream_callback=callback,
        )

    assert chunks == ["partial answer"]
    assert raised.value.error.provider_data["partial_output"] == "partial answer"
    assert raised.value.error.provider_data["partial_output_chars"] == 14
    assert raised.value.error.provider_data["partial_tool_call"] is False
    assert context.exited == 1


@pytest.mark.asyncio
async def test_api_client_returns_partial_text_in_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API client does not replace useful partial output with an error string."""

    context = _ResponseContext(_PartialThenBlockResponse([codex_text_delta("partial")]))
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()
    api_client = APIClient(adapter.model_config)
    api_client.client_handler = adapter

    result = await api_client.get_response_result(
        [{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert result.status is LLMCallStatus.RETRYABLE_ERROR
    assert result.text == "partial"
    assert result.error is not None
    assert result.error.provider_data["stage"] == "stream_idle_timeout"


@pytest.mark.asyncio
async def test_api_client_records_streamed_assistant_chunks_on_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The typed result records output delivered before a failed stream."""

    context = _ResponseContext(_PartialThenBlockResponse([codex_text_delta("partial")]))
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()
    api_client = APIClient(adapter.model_config)
    api_client.client_handler = adapter

    async def callback(_chunk: str, _message_type: str) -> None:
        return None

    result = await api_client.get_response_result(
        [{"role": "user", "content": "hello"}],
        stream=True,
        stream_callback=callback,
    )

    assert result.status is LLMCallStatus.RETRYABLE_ERROR
    assert result.streamed_assistant_chunks is True


@pytest.mark.asyncio
async def test_api_client_preserves_partial_tool_guard_after_adapter_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed tool state survives adapter cleanup so runtime cannot replay it."""

    context = _ResponseContext(
        _PartialThenBlockResponse(codex_function_call_lines(call_id="call_partial")[:2])
    )
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()
    api_client = APIClient(adapter.model_config)
    api_client.client_handler = adapter

    result = await api_client.get_response_result(
        [{"role": "user", "content": "read"}],
        stream=False,
    )

    assert result.status is LLMCallStatus.RETRYABLE_ERROR
    assert result.pending_tool_call is True
    assert adapter.has_pending_tool_call() is False


@pytest.mark.asyncio
async def test_partial_tool_state_is_reported_then_released_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out native call blocks replay but cannot poison the next turn."""

    tool_lines = [
        codex_sse(
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "id": "item-1",
                    "call_id": "call-1",
                    "name": "read_file",
                    "arguments": "",
                },
            }
        ),
        codex_sse(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "item-1",
                "delta": '{"path":"README.md"}',
            }
        ),
    ]
    context = _ResponseContext(_PartialThenBlockResponse(tool_lines))
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()

    with pytest.raises(LLMProviderError) as raised:
        await adapter.get_response([{"role": "user", "content": "read"}], stream=True)

    assert raised.value.error.provider_data["partial_tool_call"] is True
    assert adapter.has_pending_tool_call() is False
    assert context.exited == 1


@pytest.mark.asyncio
async def test_cancellation_releases_partial_tool_and_stream_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation clears provider tool state and closes the HTTP stream."""

    entered = asyncio.Event()
    response = _PartialThenBlockResponse(
        [
            codex_sse(
                {
                    "type": "response.output_item.added",
                    "item": {
                        "type": "function_call",
                        "id": "item-1",
                        "call_id": "call-1",
                        "name": "read_file",
                        "arguments": "",
                    },
                }
            )
        ],
        entered,
    )
    context = _ResponseContext(response)
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()
    task = asyncio.create_task(
        adapter.get_response([{"role": "user", "content": "read"}], stream=True)
    )
    await asyncio.wait_for(entered.wait(), timeout=0.5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert adapter.has_pending_tool_call() is False
    assert (
        adapter.get_last_request_lifecycle().status is ProviderRequestStatus.CANCELLED
    )
    assert context.exited == 1


@pytest.mark.asyncio
async def test_response_completed_terminates_text_stream_without_done_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Responses terminal event is sufficient even if `[DONE]` never arrives."""

    context = _ResponseContext(
        _PartialThenBlockResponse(
            [codex_text_delta("complete answer"), codex_completed("resp_text")]
        )
    )
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()

    result = await asyncio.wait_for(
        adapter.get_response([{"role": "user", "content": "hello"}], stream=True),
        timeout=0.5,
    )

    assert result == "complete answer"
    assert context.exited == 1
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status is ProviderRequestStatus.COMPLETED


@pytest.mark.asyncio
async def test_response_completed_terminates_tool_stream_without_done_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed native tool call does not wait indefinitely for `[DONE]`."""

    lines = [
        *codex_function_call_lines(call_id="call_terminal"),
        codex_completed("resp_tool"),
    ]
    context = _ResponseContext(_PartialThenBlockResponse(lines))
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()

    result = await asyncio.wait_for(
        adapter.get_response([{"role": "user", "content": "read"}], stream=True),
        timeout=0.5,
    )

    assert result == ""
    assert context.exited == 1
    assert adapter.has_pending_tool_call() is True
    assert adapter.get_and_clear_pending_tool_calls()[0]["call_id"] == "call_terminal"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "expected_category", "expected_retryable"),
    [
        ("invalid_request_error", ErrorCategory.BAD_REQUEST, False),
        ("server_error", ErrorCategory.PROVIDER_UNAVAILABLE, True),
    ],
)
async def test_codex_sse_error_uses_provider_retryability_taxonomy(
    monkeypatch: pytest.MonkeyPatch,
    error_type: str,
    expected_category: ErrorCategory,
    expected_retryable: bool,
) -> None:
    """Permanent SSE failures are not replayed; transient server failures are."""

    context = _ResponseContext(
        FakeResponse(
            200,
            lines=[
                codex_sse(
                    {
                        "type": "response.failed",
                        "response": {
                            "error": {
                                "type": error_type,
                                "code": error_type,
                                "message": "synthetic failure",
                            }
                        },
                    }
                )
            ],
        )
    )
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()

    with pytest.raises(LLMProviderError) as raised:
        await adapter.get_response([{"role": "user", "content": "hello"}], stream=True)

    assert raised.value.error.category is expected_category
    assert raised.value.error.retryable is expected_retryable
    assert context.exited == 1


@pytest.mark.asyncio
async def test_total_deadline_bounds_http_error_body_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled error body cannot escape the absolute attempt deadline."""

    context = _ResponseContext(_BlockingErrorBodyResponse())
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()

    with pytest.raises(LLMProviderError) as raised:
        await asyncio.wait_for(
            adapter.get_response([{"role": "user", "content": "hello"}], stream=True),
            timeout=0.5,
        )

    assert raised.value.error.provider_data["stage"] == "stream_total_timeout"
    assert context.exited == 1


@pytest.mark.asyncio
async def test_total_deadline_bounds_stream_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A callback's own longer timeout cannot extend the provider deadline."""

    context = _ResponseContext(_PartialThenBlockResponse([codex_text_delta("partial")]))
    _install_transport(monkeypatch, context)
    monkeypatch.setenv("PENGUIN_STREAM_CALLBACK_TIMEOUT_SECONDS", "10")
    adapter = codex_adapter()

    async def blocking_callback(_chunk: str, _message_type: str) -> None:
        await asyncio.Event().wait()

    with pytest.raises(LLMProviderError) as raised:
        await asyncio.wait_for(
            adapter.get_response(
                [{"role": "user", "content": "hello"}],
                stream=True,
                stream_callback=blocking_callback,
            ),
            timeout=0.5,
        )

    assert raised.value.error.provider_data["stage"] == "stream_total_timeout"
    assert raised.value.error.provider_data["partial_output"] == "partial"
    assert context.exited == 1


@pytest.mark.asyncio
async def test_total_deadline_bounds_stream_context_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transport that hangs while closing is abandoned at the attempt deadline."""

    context = _BlockingExitContext(
        FakeResponse(
            200,
            lines=[codex_text_delta("done"), codex_completed("resp_done")],
        )
    )
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()

    with pytest.raises(LLMProviderError) as raised:
        await asyncio.wait_for(
            adapter.get_response([{"role": "user", "content": "hello"}], stream=True),
            timeout=0.5,
        )

    assert raised.value.error.provider_data["stage"] == "stream_cleanup_timeout"
    assert raised.value.error.provider_data["partial_output"] == "done"
    assert context.exited == 1
    assert context.cancelled == 1
    assert (
        adapter.get_last_request_lifecycle().status
        is ProviderRequestStatus.DISCONNECTED
    )


@pytest.mark.asyncio
async def test_cleanup_deadline_survives_transport_ignoring_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleanup coroutine cannot hold the provider call after its deadline."""

    context = _CancellationIgnoringExitContext(
        FakeResponse(
            200,
            lines=[codex_text_delta("done"), codex_completed("resp_done")],
        )
    )
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()
    started = time.monotonic()

    try:
        with pytest.raises(LLMProviderError) as raised:
            await asyncio.wait_for(
                adapter.get_response(
                    [{"role": "user", "content": "hello"}],
                    stream=True,
                ),
                timeout=0.5,
            )

        assert time.monotonic() - started < 0.5
        assert raised.value.error.provider_data["stage"] == "stream_cleanup_timeout"
        assert context.cancelled == 1
    finally:
        context.release.set()
        await asyncio.wait_for(context.finished.wait(), timeout=0.5)


@pytest.mark.asyncio
async def test_cancellation_uses_short_awaited_cleanup_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation drains the canceled cleanup task before ownership returns."""

    entered = asyncio.Event()
    context = _BlockingExitContext(_PartialThenBlockResponse([], entered))
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()
    task = asyncio.create_task(
        adapter.get_response([{"role": "user", "content": "hello"}], stream=True)
    )
    await asyncio.wait_for(entered.wait(), timeout=0.5)
    started = time.monotonic()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.5)

    assert time.monotonic() - started < 0.5
    assert context.exited == 1
    assert context.cancelled == 1


def test_codex_watchdog_rejects_nonfinite_timeout_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Infinity and NaN fall back to finite operator defaults."""

    install_oauth_codex_test_auth(monkeypatch)
    monkeypatch.setenv("PENGUIN_CODEX_CONNECT_TIMEOUT_SECONDS", "inf")
    monkeypatch.setenv("PENGUIN_CODEX_HEADER_TIMEOUT_SECONDS", "nan")
    monkeypatch.setenv("PENGUIN_CODEX_IDLE_TIMEOUT_SECONDS", "-inf")
    monkeypatch.setenv("PENGUIN_CODEX_TOTAL_TIMEOUT_SECONDS", "inf")
    monkeypatch.setenv("PENGUIN_STREAM_CALLBACK_TIMEOUT_SECONDS", "nan")
    monkeypatch.setenv("PENGUIN_STREAM_CLEANUP_TIMEOUT_SECONDS", "inf")
    watchdog = codex_adapter()._codex_watchdog_config()

    assert watchdog.connect_seconds == 30.0
    assert watchdog.header_seconds == 45.0
    assert watchdog.idle_seconds == 120.0
    assert watchdog.total_seconds == 900.0
    assert watchdog.callback_seconds == 30.0
    assert watchdog.cleanup_seconds == 2.0


@pytest.mark.asyncio
async def test_legacy_api_response_does_not_return_failure_partial_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the typed API exposes partial text alongside its failure status."""

    context = _ResponseContext(_PartialThenBlockResponse([codex_text_delta("partial")]))
    _install_transport(monkeypatch, context)
    adapter = codex_adapter()
    api_client = APIClient(adapter.model_config)
    api_client.client_handler = adapter

    legacy_text = await api_client.get_response(
        [{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert legacy_text.startswith("Error:")
    assert legacy_text != "partial"
    typed_result = api_client.get_last_response_result()
    assert typed_result is not None
    assert typed_result.status is LLMCallStatus.RETRYABLE_ERROR
    assert typed_result.text == "partial"


@pytest.mark.asyncio
async def test_real_partial_output_timeout_forbids_runtime_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter's real partial marker blocks the runtime's one safe replay."""

    context = _ResponseContext(_PartialThenBlockResponse([codex_text_delta("partial")]))
    clients = _install_transport(monkeypatch, context)
    adapter = codex_adapter()
    api_client = APIClient(adapter.model_config)
    api_client.client_handler = adapter

    with pytest.raises(LLMProviderError) as raised:
        await call_with_retry(
            api_client=api_client,
            messages=[{"role": "user", "content": "hello"}],
            streaming=False,
            stream_callback=None,
            extra_kwargs={},
        )

    assert raised.value.error.provider_data["partial_output"] == "partial"
    assert len(clients) == 1


class _NativeSDKStream:
    """Controllable native Responses SDK stream for watchdog tests."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.index = 0
        self.exited = 0
        self.final_response_called = False

    async def __aenter__(self) -> "_NativeSDKStream":
        if self.mode == "header":
            await asyncio.Event().wait()
        if self.mode == "enter_error":
            raise RuntimeError("synthetic SDK setup failure")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        self.exited += 1
        return False

    def __aiter__(self) -> "_NativeSDKStream":
        return self

    async def __anext__(self) -> Any:
        if self.mode == "idle":
            await asyncio.Event().wait()
        if self.mode == "continuous":
            await asyncio.sleep(0.005)
            return SimpleNamespace(type="response.created", response=None)
        if self.mode == "completed":
            if self.index == 0:
                self.index += 1
                response = SimpleNamespace(
                    id="resp-native",
                    output_text="native done",
                    output=[],
                    usage={},
                )
                return SimpleNamespace(type="response.completed", response=response)
            await asyncio.Event().wait()
        if self.mode == "partial_error":
            if self.index == 0:
                self.index += 1
                return SimpleNamespace(
                    type="response.output_text.delta",
                    delta="partial native",
                    response=None,
                )
            raise RuntimeError("synthetic SDK disconnect")
        raise StopAsyncIteration

    async def get_final_response(self) -> Any:
        self.final_response_called = True
        await asyncio.Event().wait()


class _NativeResponses:
    def __init__(self, contexts: list[_NativeSDKStream]) -> None:
        self.contexts = list(contexts)
        self.send_count = 0

    def stream(self, **_kwargs: Any) -> _NativeSDKStream:
        self.send_count += 1
        return self.contexts.pop(0)


class _NativeHTTP:
    def __init__(self, contexts: list[Any]) -> None:
        self.contexts = list(contexts)
        self.send_count = 0

    def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        self.send_count += 1
        return self.contexts.pop(0)


class _NativePool:
    def __init__(self, http: _NativeHTTP) -> None:
        self.http = http

    async def get_client(self, _base_url: str) -> _NativeHTTP:
        return self.http


class _BlockingNativePool:
    async def get_client(self, _base_url: str) -> _NativeHTTP:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def _native_adapter(monkeypatch: pytest.MonkeyPatch) -> OpenAIAdapter:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )
    monkeypatch.setenv("PENGUIN_CODEX_HEADER_TIMEOUT_SECONDS", "0.02")
    monkeypatch.setenv("PENGUIN_CODEX_IDLE_TIMEOUT_SECONDS", "0.02")
    monkeypatch.setenv("PENGUIN_CODEX_TOTAL_TIMEOUT_SECONDS", "0.06")
    monkeypatch.setenv("PENGUIN_STREAM_CLEANUP_TIMEOUT_SECONDS", "0.02")
    return OpenAIAdapter(
        ModelConfig(
            model="gpt-5.4",
            provider="openai",
            client_preference="native",
            api_key="sk-test",
            streaming_enabled=True,
        )
    )


def _install_native_http_pool(
    monkeypatch: pytest.MonkeyPatch,
    contexts: list[Any],
) -> _NativeHTTP:
    from penguin.llm.api_client import ConnectionPoolManager

    http = _NativeHTTP(contexts)
    pool = _NativePool(http)
    monkeypatch.setattr(
        ConnectionPoolManager,
        "get_instance",
        classmethod(lambda _cls: pool),
    )
    return http


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "mode", "expected_stage"),
    [
        ("sdk", "header", "stream_header_timeout"),
        ("sdk", "idle", "stream_idle_timeout"),
        ("sdk", "continuous", "stream_total_timeout"),
        ("http", "header", "stream_header_timeout"),
        ("http", "idle", "stream_idle_timeout"),
        ("http", "continuous", "stream_total_timeout"),
    ],
)
async def test_native_openai_stream_watchdogs_cover_sdk_and_http_fallback(
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
    mode: str,
    expected_stage: str,
) -> None:
    adapter = _native_adapter(monkeypatch)
    if mode == "continuous":
        # Keep the idle deadline above the total deadline so scheduler jitter
        # cannot change which watchdog this fixture is proving.
        monkeypatch.setenv("PENGUIN_CODEX_IDLE_TIMEOUT_SECONDS", "0.2")

    if transport == "sdk":
        stream = _NativeSDKStream(mode)
        adapter.client = SimpleNamespace(
            responses=_NativeResponses([stream]),
            api_key="sk-test",
            base_url="https://example.invalid/v1",
        )
        request = adapter._stream_with_sdk({}, None)
    else:
        if mode == "header":
            context: Any = _BlockingHeaderContext()
        elif mode == "idle":
            context = _ResponseContext(_BlockingLinesResponse())
        else:
            context = _ResponseContext(_ContinuousLinesResponse())
        _install_native_http_pool(monkeypatch, [context])
        request = adapter._stream_with_http({}, None)

    with pytest.raises(LLMProviderError) as raised:
        await asyncio.wait_for(request, timeout=0.5)

    assert raised.value.error.provider_data["stage"] == expected_stage


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["sdk", "http"])
async def test_native_response_completed_does_not_wait_for_blocking_tail(
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
) -> None:
    adapter = _native_adapter(monkeypatch)

    if transport == "sdk":
        stream = _NativeSDKStream("completed")
        adapter.client = SimpleNamespace(
            responses=_NativeResponses([stream]),
            api_key="sk-test",
            base_url="https://example.invalid/v1",
        )
        request = adapter._stream_with_sdk({}, None)
    else:
        response = _PartialThenBlockResponse(
            [
                codex_sse(
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp-http",
                            "output_text": "http done",
                        },
                    }
                )
            ]
        )
        _install_native_http_pool(monkeypatch, [_ResponseContext(response)])
        request = adapter._stream_with_http({}, None)

    result = await asyncio.wait_for(request, timeout=0.5)

    assert result == ("native done" if transport == "sdk" else "http done")
    if transport == "sdk":
        assert stream.final_response_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["sdk", "http"])
async def test_native_final_callback_obeys_total_attempt_deadline(
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
) -> None:
    """Terminal response delivery cannot escape the provider total watchdog."""

    adapter = _native_adapter(monkeypatch)

    async def blocking_callback(_chunk: str, _message_type: str) -> None:
        await asyncio.Event().wait()

    if transport == "sdk":
        adapter.client = SimpleNamespace(
            responses=_NativeResponses([_NativeSDKStream("completed")]),
            api_key="sk-test",
            base_url="https://example.invalid/v1",
        )
        request = adapter._stream_with_sdk({}, blocking_callback)
        expected_partial = "native done"
    else:
        response = _PartialThenBlockResponse(
            [
                codex_sse(
                    {
                        "type": "response.completed",
                        "response": {
                            "id": "resp-http",
                            "output_text": "http done",
                        },
                    }
                )
            ]
        )
        _install_native_http_pool(monkeypatch, [_ResponseContext(response)])
        request = adapter._stream_with_http({}, blocking_callback)
        expected_partial = "http done"

    with pytest.raises(LLMProviderError) as raised:
        await asyncio.wait_for(request, timeout=0.5)

    assert raised.value.error.provider_data["stage"] == "stream_total_timeout"
    assert raised.value.error.provider_data["partial_output"] == expected_partial


@pytest.mark.asyncio
async def test_native_http_pool_acquisition_obeys_total_attempt_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wedged shared-client lookup cannot hang the HTTP fallback."""

    from penguin.llm.api_client import ConnectionPoolManager

    adapter = _native_adapter(monkeypatch)
    pool = _BlockingNativePool()
    monkeypatch.setattr(
        ConnectionPoolManager,
        "get_instance",
        classmethod(lambda _cls: pool),
    )

    with pytest.raises(LLMProviderError) as raised:
        await asyncio.wait_for(adapter._stream_with_http({}, None), timeout=0.5)

    assert raised.value.error.provider_data["stage"] == "stream_total_timeout"


@pytest.mark.asyncio
async def test_partial_sdk_output_prevents_http_and_runtime_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _native_adapter(monkeypatch)
    responses = _NativeResponses([_NativeSDKStream("partial_error")])
    adapter.client = SimpleNamespace(
        responses=responses,
        api_key="sk-test",
        base_url="https://example.invalid/v1",
    )
    http = _install_native_http_pool(monkeypatch, [])
    api_client = APIClient(adapter.model_config)
    api_client.client_handler = adapter

    with pytest.raises(LLMProviderError) as raised:
        await call_with_retry(
            api_client=api_client,
            messages=[{"role": "user", "content": "hello"}],
            streaming=True,
            stream_callback=lambda *_args: None,
            extra_kwargs={},
        )

    assert raised.value.error.provider_data["partial_output"] == "partial native"
    assert responses.send_count == 1
    assert http.send_count == 0


@pytest.mark.asyncio
async def test_sdk_to_http_fallback_consumes_global_two_send_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _native_adapter(monkeypatch)
    responses = _NativeResponses([_NativeSDKStream("enter_error")])
    adapter.client = SimpleNamespace(
        responses=responses,
        api_key="sk-test",
        base_url="https://example.invalid/v1",
    )
    http = _install_native_http_pool(
        monkeypatch,
        [_ResponseContext(FakeResponse(200, lines=[]))],
    )
    api_client = APIClient(adapter.model_config)
    api_client.client_handler = adapter

    with pytest.raises(LLMProviderError) as raised:
        await call_with_retry(
            api_client=api_client,
            messages=[{"role": "user", "content": "hello"}],
            streaming=True,
            stream_callback=lambda *_args: None,
            extra_kwargs={},
        )

    assert responses.send_count == 1
    assert http.send_count == 1
    assert raised.value.error.provider_data["attempts"] == 2
