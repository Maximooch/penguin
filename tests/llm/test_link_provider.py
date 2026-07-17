from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from penguin.llm.contracts import ProviderRequestStatus
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
