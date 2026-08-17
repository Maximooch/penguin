from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from penguin.llm.contracts import (
    FinishReason,
    LLMProviderError,
    ProviderRequestStatus,
)
from penguin.llm.model_config import ModelConfig
from penguin.llm.providers.link import (
    LinkInferenceContext,
    LinkProvider,
    LinkProviderConfig,
)

if TYPE_CHECKING:
    from penguin.llm.providers.link.provider import LinkProtocol


def _context(workspace_id: str = "workspace-1") -> LinkInferenceContext:
    return LinkInferenceContext(
        workspace_id=workspace_id,
        user_id=f"user-{workspace_id}",
        session_id=f"session-{workspace_id}",
        agent_id="agent-1",
        run_id=f"run-{workspace_id}",
        requested_model_id="openai/gpt-5.4-nano",
    )


def _model() -> ModelConfig:
    return ModelConfig(
        model="openai/gpt-5.4-nano",
        provider="openrouter",
        client_preference="link",
        max_output_tokens=128,
    )


def _provider(
    handler: Any,
    *,
    context: LinkInferenceContext | None = None,
    protocol: str = "responses",
) -> LinkProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    config = LinkProviderConfig(
        base_url="http://link.test/api/v1",
        service_token="service-secret",
        protocol=cast("LinkProtocol", protocol),
    )
    return LinkProvider(
        model_config=_model(),
        context=context or _context(),
        config=config,
        http_client=client,
    )


def test_transient_context_omits_persisted_identity_headers() -> None:
    context = LinkInferenceContext(
        workspace_id="workspace-1",
        user_id="user-1",
        run_id="run-1",
        requested_model_id="openai/gpt-5.4-nano",
    )

    headers = context.headers("request-1")

    assert "X-Link-Session-Id" not in headers
    assert "X-Link-Agent-Id" not in headers


def test_context_includes_workos_organization_header() -> None:
    context = LinkInferenceContext(
        workspace_id="workspace-1",
        user_id="user-1",
        workos_organization_id="org_01M06XBYP88CD1MHHSRGWTC2BA",
        run_id="run-1",
        requested_model_id="openai/gpt-5.4-nano",
    )

    headers = context.headers("request-1")

    assert (
        headers["X-Link-WorkOS-Organization-Id"]
        == "org_01M06XBYP88CD1MHHSRGWTC2BA"
    )


def test_context_rejects_one_sided_persisted_identity() -> None:
    with pytest.raises(ValueError, match="supplied together"):
        LinkInferenceContext(
            workspace_id="workspace-1",
            user_id="user-1",
            session_id="session-1",
            run_id="run-1",
            requested_model_id="openai/gpt-5.4-nano",
        )


@pytest.mark.asyncio
async def test_responses_request_has_attribution_without_provider_key() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        captured["timeout"] = request.extensions.get("timeout")
        return httpx.Response(
            200,
            headers={
                "X-Link-Inference-Request-Id": request.headers[
                    "X-Link-Inference-Request-Id"
                ],
                "X-Link-Meter-Event-Key": "inference:request-1",
            },
            json={
                "id": "response-1",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "hello"}],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            },
        )

    provider = _provider(handler)
    result = await provider.get_response(
        [{"role": "user", "content": "hi"}],
        max_output_tokens=32,
    )

    assert result == "hello"
    assert captured["headers"]["x-link-workspace-id"] == "workspace-1"
    assert captured["headers"]["x-link-service-auth"] == "service-secret"
    assert (
        captured["headers"]["x-link-request-id"]
        == captured["headers"]["x-link-inference-request-id"]
    )
    assert "authorization" not in captured["headers"]
    assert "openrouter" not in captured["headers"]
    assert captured["body"]["max_output_tokens"] == 32
    assert captured["timeout"]["read"] == 300.0
    assert provider.get_last_usage()["input_tokens"] == 10
    assert provider.get_last_request_lifecycle().status == (
        ProviderRequestStatus.COMPLETED
    )


@pytest.mark.asyncio
async def test_responses_request_omits_provider_hosted_web_search() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "status": "completed",
                "output_text": "ok",
                "usage": {},
            },
        )

    provider = _provider(handler)
    result = await provider.get_response(
        [{"role": "user", "content": "hi"}],
        tools=[
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file.",
                "parameters": {"type": "object", "properties": {}},
            },
            {"type": "web_search"},
        ],
    )

    assert result == "ok"
    assert captured["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]


@pytest.mark.asyncio
async def test_responses_request_replays_assistant_history_as_output_item() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "response-2",
                "status": "completed",
                "output_text": "goodbye",
                "usage": {},
            },
        )

    provider = _provider(handler)
    result = await provider.get_response(
        [
            {"role": "user", "content": "Reply with exactly: hello"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "Reply with exactly: goodbye"},
        ],
    )

    assert result == "goodbye"
    assert captured["input"][1] == {
        "type": "message",
        "id": "msg_link_history_1",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "hello"}],
    }


@pytest.mark.asyncio
async def test_chat_stream_preserves_text_reasoning_tools_and_usage() -> None:
    async def callback(text: str, message_type: str) -> None:
        chunks.append((message_type, text))

    chunks: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        events = [
            {"id": "gen-1", "choices": [{"delta": {"reasoning": "think "}}]},
            {"id": "gen-1", "choices": [{"delta": {"content": "hello"}}]},
            {
                "id": "gen-1",
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":',
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
            {
                "id": "gen-1",
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": '"a"}'},
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "total_tokens": 25,
                },
            },
        ]
        body = "data: malformed-optional-frame\n\n"
        body += "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        body += "data: [DONE]\n\n"
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    provider = _provider(handler, protocol="chat_completions")
    result = await provider.get_response(
        [{"role": "user", "content": "hi"}],
        max_output_tokens=32,
        stream=True,
        stream_callback=callback,
        tools=[{"type": "function", "function": {"name": "read_file"}}],
    )

    assert result == "hello"
    assert chunks == [("reasoning", "think "), ("assistant", "hello")]
    assert provider.get_last_reasoning() == "think "
    assert provider.get_last_usage()["total_tokens"] == 25
    assert provider.get_and_clear_pending_tool_calls() == [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "read_file",
                "arguments": '{"path":"a"}',
            },
        }
    ]


@pytest.mark.asyncio
async def test_concurrent_providers_do_not_share_link_context() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.headers["X-Link-Workspace-Id"],
                request.headers["X-Link-Request-Id"],
            )
        )
        return httpx.Response(
            200,
            json={"id": "r", "status": "completed", "output_text": "ok"},
        )

    first = _provider(handler, context=_context("workspace-a"))
    second = _provider(handler, context=_context("workspace-b"))
    await __import__("asyncio").gather(
        first.get_response([{"role": "user", "content": "a"}]),
        second.get_response([{"role": "user", "content": "b"}]),
    )

    assert {workspace for workspace, _ in seen} == {"workspace-a", "workspace-b"}
    assert len({request_id for _, request_id in seen}) == 2


@pytest.mark.asyncio
async def test_responses_tool_turn_uses_two_distinct_link_invocations() -> None:
    requests: list[dict[str, Any]] = []
    request_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        request_ids.append(request.headers["X-Link-Request-Id"])
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "response-1",
                    "status": "completed",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "read_file",
                            "arguments": '{"path":"notes.txt"}',
                        }
                    ],
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "response-2",
                "status": "completed",
                "output_text": "The file says hello.",
            },
        )

    provider = _provider(handler)
    await provider.get_response(
        [{"role": "user", "content": "Read notes.txt"}],
        tools=[{"type": "function", "name": "read_file"}],
    )
    tool_calls = provider.get_and_clear_pending_tool_calls()
    result = await provider.get_response(
        [
            {"role": "user", "content": "Read notes.txt"},
            {"role": "assistant", "content": None, "tool_calls": tool_calls},
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": "hello",
            },
        ],
        tools=[{"type": "function", "name": "read_file"}],
    )

    assert result == "The file says hello."
    assert len(requests) == 2
    assert len(set(request_ids)) == 2
    assert requests[1]["input"] == [
        {
            "role": "user",
            "content": [{"type": "input_text", "text": "Read notes.txt"}],
        },
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "read_file",
            "arguments": '{"path":"notes.txt"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "hello",
        },
    ]


@pytest.mark.asyncio
async def test_ambiguous_disconnect_is_not_retryable() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadError("connection reset after dispatch")

    provider = _provider(handler)
    with pytest.raises(Exception) as raised:
        await provider.get_response([{"role": "user", "content": "hi"}])

    assert calls == 1
    assert provider.get_last_error() is not None
    assert provider.get_last_error().retryable is False
    assert provider.get_last_request_lifecycle().status == (
        ProviderRequestStatus.DISCONNECTED
    )
    assert "uncertain" in str(raised.value).lower()


@pytest.mark.asyncio
async def test_stream_http_error_reads_link_error_body_before_reporting() -> None:
    class ErrorStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(
                {
                    "error": {
                        "message": "The selected model rejected this request.",
                        "code": "model_request_rejected",
                    }
                }
            ).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            stream=ErrorStream(),
            headers={
                "content-type": "application/json",
                "x-link-dispatch-state": "not_started",
            },
        )

    provider = _provider(handler)
    with pytest.raises(
        LLMProviderError,
        match="The selected model rejected this request.",
    ) as raised:
        await provider.get_response(
            [{"role": "user", "content": "hi"}],
            stream=True,
        )

    assert raised.value.error.status_code == 400
    assert raised.value.error.provider_data["dispatch_state"] == "not_started"
    assert provider.get_last_request_lifecycle().status == ProviderRequestStatus.FAILED


@pytest.mark.asyncio
async def test_stream_rate_limit_is_retryable_before_any_output() -> None:
    class ErrorStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(
                {
                    "error": {
                        "message": "Rate limit exceeded. Please try again later.",
                        "code": "rate_limit_exceeded",
                    }
                }
            ).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            stream=ErrorStream(),
            headers={
                "content-type": "application/json",
                "retry-after": "17",
                "x-link-dispatch-state": "provider_rejected",
            },
        )

    provider = _provider(handler)
    with pytest.raises(LLMProviderError, match="Rate limit exceeded") as raised:
        await provider.get_response(
            [{"role": "user", "content": "hi"}],
            stream=True,
        )

    assert raised.value.error.retryable is True
    assert raised.value.error.retry_after_seconds == 17
    assert raised.value.error.provider_data["dispatch_state"] == "provider_rejected"


@pytest.mark.asyncio
async def test_stream_eof_before_terminal_event_is_uncertain_and_not_retryable() -> (
    None
):
    def handler(_request: httpx.Request) -> httpx.Response:
        event = {
            "type": "response.output_text.delta",
            "delta": "partial",
        }
        return httpx.Response(
            200,
            text=f"data: {json.dumps(event)}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    provider = _provider(handler)
    with pytest.raises(LLMProviderError, match="terminal event") as raised:
        await provider.get_response(
            [{"role": "user", "content": "hi"}],
            stream=True,
        )

    assert raised.value.error.retryable is False
    assert raised.value.error.provider_data["dispatch_outcome"] == "uncertain"
    assert provider.get_last_request_lifecycle().status == (
        ProviderRequestStatus.DISCONNECTED
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event", "expected_message"),
    [
        (
            {
                "type": "response.failed",
                "response": {"error": {"message": "provider failed"}},
            },
            "provider failed",
        ),
        (
            {
                "type": "response.incomplete",
                "response": {"incomplete_details": {"reason": "content_filter"}},
            },
            "content_filter",
        ),
        ({"type": "error", "message": "explicit stream error"}, "stream error"),
    ],
)
async def test_responses_terminal_failure_events_are_not_reported_as_completed(
    event: dict[str, Any],
    expected_message: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text=f"data: {json.dumps(event)}\n\n",
            headers={"content-type": "text/event-stream"},
        )

    provider = _provider(handler)
    with pytest.raises(LLMProviderError, match=expected_message) as raised:
        await provider.get_response(
            [{"role": "user", "content": "hi"}],
            stream=True,
        )

    assert raised.value.error.retryable is False
    assert provider.get_last_request_lifecycle().status == ProviderRequestStatus.FAILED


@pytest.mark.asyncio
async def test_invalid_link_response_is_terminal_and_not_retryable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="not-json",
            headers={"content-type": "application/json"},
        )

    provider = _provider(handler)
    with pytest.raises(Exception):
        await provider.get_response([{"role": "user", "content": "hi"}])

    error = provider.get_last_error()
    assert error is not None
    assert error.retryable is False
    assert provider.get_last_request_lifecycle().status == ProviderRequestStatus.FAILED


@pytest.mark.asyncio
async def test_stream_output_limit_incomplete_returns_persistable_partial_text() -> (
    None
):
    events = [
        {"type": "response.output_text.delta", "delta": "partial"},
        {
            "type": "response.incomplete",
            "response": {
                "id": "response-incomplete",
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
                "usage": {
                    "input_tokens": 8,
                    "output_tokens": 128,
                    "total_tokens": 136,
                },
            },
        },
    ]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
            headers={"content-type": "text/event-stream"},
        )

    streamed: list[tuple[str, str]] = []

    async def callback(text: str, message_type: str) -> None:
        streamed.append((text, message_type))

    provider = _provider(handler)
    result = await provider.get_response(
        [{"role": "user", "content": "hi"}],
        stream=True,
        stream_callback=callback,
    )

    assert result == "partial"
    assert streamed == [("partial", "assistant")]
    assert provider.get_last_finish_reason() is FinishReason.LENGTH
    assert provider.get_last_usage()["output_tokens"] == 128
    assert provider.get_last_error() is None
    lifecycle = provider.get_last_request_lifecycle()
    assert lifecycle.status is ProviderRequestStatus.COMPLETED
    assert lifecycle.finish_reason is FinishReason.LENGTH


@pytest.mark.asyncio
async def test_buffered_output_limit_incomplete_returns_persistable_partial_text() -> (
    None
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "response-incomplete",
                "status": "incomplete",
                "output_text": "partial",
                "incomplete_details": {"reason": "max_output_tokens"},
            },
        )

    provider = _provider(handler)
    result = await provider.get_response([{"role": "user", "content": "hi"}])

    assert result == "partial"
    assert provider.get_last_finish_reason() is FinishReason.LENGTH
    assert provider.get_last_error() is None
    lifecycle = provider.get_last_request_lifecycle()
    assert lifecycle.status is ProviderRequestStatus.COMPLETED
    assert lifecycle.finish_reason is FinishReason.LENGTH


@pytest.mark.asyncio
async def test_buffered_incomplete_for_other_reason_remains_terminal() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "response-incomplete",
                "status": "incomplete",
                "output_text": "filtered partial",
                "incomplete_details": {"reason": "content_filter"},
            },
        )

    provider = _provider(handler)
    with pytest.raises(LLMProviderError, match="content_filter"):
        await provider.get_response([{"role": "user", "content": "hi"}])

    assert provider.get_last_request_lifecycle().status is (
        ProviderRequestStatus.FAILED
    )


@pytest.mark.asyncio
async def test_stream_read_timeout_is_uncertain_and_not_replayed() -> None:
    calls = 0

    class _TimeoutStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise httpx.ReadTimeout("stream idle timeout")
            yield b""  # pragma: no cover

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            stream=_TimeoutStream(),
            headers={"content-type": "text/event-stream"},
        )

    provider = _provider(handler)
    with pytest.raises(LLMProviderError, match="outcome is uncertain") as raised:
        await provider.get_response(
            [{"role": "user", "content": "hi"}],
            stream=True,
        )

    assert calls == 1
    assert raised.value.error.retryable is False
    assert provider.get_last_request_lifecycle().status == (
        ProviderRequestStatus.DISCONNECTED
    )


@pytest.mark.asyncio
async def test_stream_cancellation_remains_cancelled() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await release.wait()
            yield b"data: [DONE]\n\n"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_BlockingStream(),
            headers={"content-type": "text/event-stream"},
        )

    provider = _provider(handler)
    task = asyncio.create_task(
        provider.get_response(
            [{"role": "user", "content": "hi"}],
            stream=True,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.get_last_request_lifecycle().status == (
        ProviderRequestStatus.CANCELLED
    )
