"""OpenRouter direct-stream usage recovery regressions."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import httpx
import pytest

from penguin.llm.contracts import (
    ErrorCategory,
    FinishReason,
    LLMProviderError,
    ProviderRequestStatus,
)
from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


class _DirectStreamResponse:
    def __init__(
        self,
        lines: list[str],
        *,
        headers: dict[str, str] | None = None,
        status_code: int = 200,
    ) -> None:
        self._lines = lines
        self.status_code = status_code
        self.headers: dict[str, str] = dict(headers or {})

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _DirectStreamContext:
    def __init__(self, response: _DirectStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _DirectStreamResponse:
        return self._response

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any | None,
    ) -> bool:
        del exc_type, exc, tb
        return False


class _DirectStreamClient:
    def __init__(
        self,
        lines: list[str],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._lines = lines
        self._headers = headers

    def stream(
        self, method: str, url: str, headers: dict[str, str], json: dict[str, Any]
    ) -> _DirectStreamContext:
        del method, url, headers, json
        return _DirectStreamContext(
            _DirectStreamResponse(self._lines, headers=self._headers)
        )


def test_extract_generation_id_from_chunk_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium",
        )
    )

    assert (
        gateway._extract_generation_id_from_chunk({"generation_id": "gen-123"})
        == "gen-123"
    )
    assert gateway._extract_generation_id_from_chunk({"id": "gen-456"}) == "gen-456"
    assert gateway._extract_generation_id_from_chunk({"id": "chatcmpl-1"}) is None


@pytest.mark.asyncio
async def test_direct_stream_interrupt_recovers_usage_from_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="high",
            interrupt_on_action=True,
        )
    )

    stream_chunk = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "delta": {"content": "I will check. <execute>pwd</execute>"},
                "finish_reason": None,
            }
        ],
    }
    stream_lines = [f"data: {json.dumps(stream_chunk)}", "data: [DONE]"]
    generation_payload = {
        "data": {
            "id": "gen-test-123",
            "tokens_prompt": 8164,
            "tokens_completion": 0,
            "native_tokens_reasoning": 0,
            "native_tokens_cached": 0,
            "usage": 0,
            "total_cost": 0,
        }
    }

    class _StreamResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers: dict[str, str] = {
                "x-openrouter-generation-id": "gen-test-123"
            }

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self):
            for line in stream_lines:
                yield line

    class _StreamContext:
        def __init__(self, response: _StreamResponse) -> None:
            self._response = response

        async def __aenter__(self) -> _StreamResponse:
            return self._response

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: Any | None,
        ) -> bool:
            del exc_type, exc, tb
            return False

    class _GetResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.content = json.dumps(generation_payload).encode("utf-8")

        def json(self) -> dict[str, Any]:
            return generation_payload

    class _Client:
        def __init__(self) -> None:
            self.get_calls = 0

        def stream(
            self, method: str, url: str, headers: dict[str, str], json: dict[str, Any]
        ):
            del method, url, headers, json
            return _StreamContext(_StreamResponse())

        async def get(
            self,
            url: str,
            headers: dict[str, str],
            params: dict[str, str],
            timeout: Any,
        ) -> _GetResponse:
            del url, headers, params, timeout
            self.get_calls += 1
            return _GetResponse()

    chunks: list[tuple[str, str]] = []

    async def _callback(chunk: str, message_type: str = "assistant") -> None:
        chunks.append((chunk, message_type))

    client = _Client()
    result = await gateway._handle_streaming_response(
        client=cast(Any, client),
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        params={"model": gateway.model_config.model, "messages": []},
        stream_callback=cast(Any, _callback),
    )

    assert "<execute>pwd</execute>" in result
    assert chunks
    assert client.get_calls == 1

    usage = gateway.get_last_usage()
    assert usage["input_tokens"] == 8164
    assert usage["output_tokens"] == 0
    assert usage["reasoning_tokens"] == 0
    assert usage["cache_read_tokens"] == 0
    assert usage["total_tokens"] == 8164


@pytest.mark.asyncio
async def test_direct_stream_midstream_error_preserves_partial_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium",
        )
    )
    gateway._start_request_lifecycle(messages=[], stream=True)

    partial_chunk = {
        "id": "chatcmpl-test",
        "choices": [{"delta": {"content": "partial answer"}, "finish_reason": None}],
    }
    error_chunk = {
        "id": "chatcmpl-test",
        "choices": [{"delta": {}, "finish_reason": "error"}],
        "error": {
            "code": "server_error",
            "message": "synthetic direct stream error",
            "metadata": {"provider_name": "fixture-provider"},
        },
    }
    lines = [
        f"data: {json.dumps(partial_chunk)}",
        f"data: {json.dumps(error_chunk)}",
    ]
    chunks: list[tuple[str, str]] = []

    async def _callback(chunk: str, message_type: str = "assistant") -> None:
        chunks.append((chunk, message_type))

    result = await gateway._handle_streaming_response(
        client=cast(Any, _DirectStreamClient(lines)),
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        params={"model": gateway.model_config.model, "messages": []},
        stream_callback=cast(Any, _callback),
    )

    assert result == (
        "partial answer\n\n"
        "[Error: Stream interrupted by fixture-provider: "
        "synthetic direct stream error]"
    )
    assert chunks == [("partial answer", "assistant")]
    assert gateway.get_last_finish_reason() == FinishReason.ERROR
    assert gateway.has_pending_tool_call() is False

    last_error = gateway.get_last_error()
    assert last_error is not None
    assert last_error.message == "synthetic direct stream error"
    assert last_error.finish_reason == FinishReason.ERROR

    lifecycle = gateway.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status == ProviderRequestStatus.FAILED
    assert lifecycle.error is last_error


@pytest.mark.asyncio
async def test_direct_stream_incomplete_tool_call_releases_pending_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium",
            interrupt_on_tool_call=True,
        )
    )
    gateway._start_request_lifecycle(messages=[], stream=True)

    tool_chunk = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_incomplete",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"README.md"}',
                            },
                        }
                    ]
                },
                "finish_reason": None,
            }
        ],
    }

    result = await gateway._handle_streaming_response(
        client=cast(Any, _DirectStreamClient([f"data: {json.dumps(tool_chunk)}"])),
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        params={"model": gateway.model_config.model, "messages": []},
        stream_callback=None,
    )

    assert result == (
        "[Error: OpenRouter stream ended before finish_reason (output_state=tool_call)]"
    )
    assert gateway.get_last_finish_reason() == FinishReason.ERROR
    assert gateway.has_pending_tool_call() is False
    assert gateway.get_and_clear_pending_tool_calls() == []

    last_error = gateway.get_last_error()
    assert last_error is not None
    assert last_error.category == ErrorCategory.NETWORK
    assert last_error.retryable is True

    lifecycle = gateway.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status == ProviderRequestStatus.DISCONNECTED
    assert lifecycle.error is last_error


@pytest.mark.asyncio
async def test_sdk_stream_stall_returns_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PENGUIN_OPENROUTER_STREAM_CHUNK_TIMEOUT_SECONDS", "0.01")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="z-ai/glm-5-turbo",
            provider="openrouter",
            client_preference="openrouter",
            streaming_enabled=True,
        )
    )

    class _HangingStream:
        def __init__(self) -> None:
            self.closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(3600)
            raise StopAsyncIteration

        async def aclose(self) -> None:
            self.closed = True

    async def _create_completion(**kwargs: Any):
        del kwargs
        return stream

    stream = _HangingStream()
    gateway.client.chat.completions.create = _create_completion  # type: ignore[attr-defined]

    async def _callback(*_args: Any) -> None:
        return None

    with pytest.raises(LLMProviderError) as raised:
        await gateway.get_response(
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
            stream_callback=_callback,
        )

    assert raised.value.error.category is ErrorCategory.TIMEOUT
    assert raised.value.error.retryable is True
    assert raised.value.error.provider_data["stage"] == "sdk_stream_timeout"
    assert stream.closed is True
    lifecycle = gateway.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status is ProviderRequestStatus.DISCONNECTED
    assert lifecycle.error is raised.value.error


@pytest.mark.asyncio
async def test_sdk_stream_close_deadline_detaches_ignored_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung async close cannot hold the timeout path indefinitely."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PENGUIN_OPENROUTER_STREAM_CLOSE_TIMEOUT_SECONDS", "0.01")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="z-ai/glm-5-turbo",
            provider="openrouter",
            client_preference="openrouter",
        )
    )
    release = asyncio.Event()
    entered = asyncio.Event()
    finished = asyncio.Event()

    class _CancellationIgnoringClose:
        def __init__(self) -> None:
            self.cancelled = 0

        async def aclose(self) -> None:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                await release.wait()
            finally:
                finished.set()

    stream = _CancellationIgnoringClose()
    try:
        await asyncio.wait_for(gateway._close_sdk_stream(stream), timeout=0.5)
        assert entered.is_set()
        assert stream.cancelled == 1
    finally:
        release.set()
        await asyncio.wait_for(finished.wait(), timeout=0.5)


@pytest.mark.asyncio
async def test_direct_stream_stall_returns_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PENGUIN_OPENROUTER_STREAM_CHUNK_TIMEOUT_SECONDS", "0.01")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium",
        )
    )

    class _StreamResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers: dict[str, str] = {}
            self.closed = False

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self):
            await asyncio.sleep(3600)
            if False:
                yield ""

        async def aclose(self) -> None:
            self.closed = True

    class _StreamContext:
        def __init__(self, response: _StreamResponse) -> None:
            self._response = response

        async def __aenter__(self) -> _StreamResponse:
            return self._response

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: Any | None,
        ) -> bool:
            del exc_type, exc, tb
            return False

    class _Client:
        def __init__(self) -> None:
            self.response = _StreamResponse()

        def stream(
            self, method: str, url: str, headers: dict[str, str], json: dict[str, Any]
        ):
            del method, url, headers, json
            return _StreamContext(self.response)

    class _PoolContext:
        async def __aenter__(self) -> _Client:
            return client

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: Any | None,
        ) -> bool:
            del exc_type, exc, tb
            return False

    class _Pool:
        def client_context(self, _base_url: str) -> _PoolContext:
            return _PoolContext()

    client = _Client()
    from penguin.llm.api_client import ConnectionPoolManager

    monkeypatch.setattr(
        ConnectionPoolManager,
        "get_instance",
        classmethod(lambda _cls: _Pool()),
    )

    async def _callback(*_args: Any) -> None:
        return None

    with pytest.raises(LLMProviderError) as raised:
        await gateway.get_response(
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
            stream_callback=_callback,
        )

    assert raised.value.error.category is ErrorCategory.TIMEOUT
    assert raised.value.error.retryable is True
    assert raised.value.error.provider_data["stage"] == "direct_stream_timeout"
    assert client.response.closed is True
    lifecycle = gateway.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status is ProviderRequestStatus.DISCONNECTED
    assert lifecycle.error is raised.value.error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("timeout_type", "expected_stage"),
    [
        (httpx.ReadTimeout, "direct_read_timeout"),
        (httpx.ConnectTimeout, "direct_connect_timeout"),
    ],
)
async def test_direct_transport_timeout_is_typed_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
    timeout_type: type[httpx.TimeoutException],
    expected_stage: str,
) -> None:
    """Pool-entry transport timeouts stay typed through the reasoning path."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium",
        )
    )

    class _TimeoutContext:
        async def __aenter__(self) -> Any:
            raise timeout_type("synthetic direct transport timeout")

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: Any | None,
        ) -> bool:
            del exc_type, exc, tb
            return False

    class _Pool:
        def client_context(self, _base_url: str) -> _TimeoutContext:
            return _TimeoutContext()

    from penguin.llm.api_client import ConnectionPoolManager

    monkeypatch.setattr(
        ConnectionPoolManager,
        "get_instance",
        classmethod(lambda _cls: _Pool()),
    )

    async def _callback(*_args: Any) -> None:
        return None

    with pytest.raises(LLMProviderError) as raised:
        await gateway.get_response(
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
            stream_callback=_callback,
        )

    assert raised.value.error.category is ErrorCategory.TIMEOUT
    assert raised.value.error.retryable is True
    assert raised.value.error.provider_data["stage"] == expected_stage
    assert raised.value.error.provider_data["partial_output"] == ""
    lifecycle = gateway.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status is ProviderRequestStatus.DISCONNECTED
    assert lifecycle.error is raised.value.error


@pytest.mark.asyncio
async def test_direct_wrapped_timeout_is_typed_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy-wrapped timeout cannot fall back to a legacy error string."""

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium",
        )
    )

    class _TimeoutContext:
        async def __aenter__(self) -> Any:
            raise RuntimeError("proxy timeout while opening direct stream")

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: Any | None,
        ) -> bool:
            del exc_type, exc, tb
            return False

    class _Pool:
        def client_context(self, _base_url: str) -> _TimeoutContext:
            return _TimeoutContext()

    from penguin.llm.api_client import ConnectionPoolManager

    monkeypatch.setattr(
        ConnectionPoolManager,
        "get_instance",
        classmethod(lambda _cls: _Pool()),
    )

    async def _callback(*_args: Any) -> None:
        return None

    with pytest.raises(LLMProviderError) as raised:
        await gateway.get_response(
            messages=[{"role": "user", "content": "hello"}],
            stream=True,
            stream_callback=_callback,
        )

    assert raised.value.error.category is ErrorCategory.TIMEOUT
    assert raised.value.error.retryable is True
    assert raised.value.error.provider_data["stage"] == "direct_wrapped_timeout"
    assert raised.value.error.provider_data["partial_output"] == ""
    lifecycle = gateway.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status is ProviderRequestStatus.DISCONNECTED
    assert lifecycle.error is raised.value.error
