"""A broker disconnect retries inference, not the surrounding tool execution."""

import asyncio
import json

import httpx
import pytest

from penguin.llm.contracts import LLMProviderError, ProviderRequestStatus
from penguin.llm.model_config import ModelConfig
from penguin.llm.providers.link import (
    LinkInferenceContext,
    LinkProvider,
    LinkProviderConfig,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["partial", "unavailable", "connection"])
async def test_runtime_recovery_discards_partial_attempt(
    monkeypatch: pytest.MonkeyPatch,
    fault: str,
) -> None:
    """Preserve tool results and retry with a fresh billing identity, without deltas."""
    requests = []
    emitted = []

    async def backoff(seconds: float) -> None:
        """Skip the connection delay in this deterministic test."""
        assert seconds > 0

    monkeypatch.setattr("penguin.llm.providers.link.provider.asyncio.sleep", backoff)

    def handler(request: httpx.Request) -> httpx.Response:
        """Interrupt the first attempt and complete its replacement."""
        requests.append(request)
        body = json.loads(request.content)
        assert body["messages"][-1] == {
            "role": "tool",
            "tool_call_id": "executed",
            "content": "done once",
        }
        if len(requests) == 1:
            if fault == "unavailable":
                return httpx.Response(
                    503, json={"error": {"message": "broker restarting"}}
                )
            if fault == "connection":
                raise httpx.ConnectError("broker restarting")
            event = {
                "choices": [
                    {
                        "delta": {
                            "content": "discard me",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "bad",
                                    "function": {
                                        "name": "execute_command",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        else:
            event = {
                "choices": [
                    {"delta": {"content": "complete"}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 2},
            }
        return httpx.Response(
            200,
            text="data: " + json.dumps(event) + "\n\n",
            headers={"content-type": "text/event-stream"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = make_provider(client)
        result = await provider.get_response(
            [{"role": "tool", "tool_call_id": "executed", "content": "done once"}],
            stream=True,
            stream_callback=lambda text, message_type="assistant": emitted.append(text),
        )
        assert result == "complete"
        assert emitted == ["complete"]
        assert provider.get_and_clear_pending_tool_calls() == []
        assert len(requests) == 2
        assert (
            requests[0].headers["x-link-inference-request-id"]
            != requests[1].headers["x-link-inference-request-id"]
        )


def make_provider(client: httpx.AsyncClient) -> LinkProvider:
    """Build the real provider with a scoped credential and fake transport."""
    return LinkProvider(
        model_config=ModelConfig(
            model="test", provider="openrouter", max_output_tokens=32
        ),
        context=LinkInferenceContext(
            workspace_id="w", user_id="u", run_id="r", requested_model_id="test"
        ),
        config=LinkProviderConfig(
            base_url="http://link.test/api/v1",
            protocol="chat_completions",
            runtime_token="lk-run-" + "a" * 43,
        ),
        http_client=client,
    )


@pytest.mark.asyncio
async def test_runtime_recovery_is_cancellable(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable broker must not defeat user Stop."""
    waiting = asyncio.Event()

    async def backoff(seconds: float) -> None:
        """Hold the connection retry until cancellation."""
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("penguin.llm.providers.link.provider.asyncio.sleep", backoff)

    def handler(request: httpx.Request) -> httpx.Response:
        """Model a broker that is not listening."""
        raise httpx.ConnectError("broker down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = make_provider(client)
        task = asyncio.create_task(
            provider.get_response([{"role": "user", "content": "hi"}])
        )
        await asyncio.wait_for(waiting.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (
            provider.get_last_request_lifecycle().status
            == ProviderRequestStatus.CANCELLED
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 402, 400])
async def test_runtime_recovery_does_not_retry_denials(status: int) -> None:
    """Authorization, budget and validation failures remain authoritative."""
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Return an authoritative denial."""
        nonlocal count
        count += 1
        return httpx.Response(status, json={"error": {"message": "denied"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(LLMProviderError):
            await make_provider(client).get_response(
                [{"role": "user", "content": "hi"}]
            )
    assert count == 1


@pytest.mark.asyncio
async def test_runtime_recovery_does_not_retry_stream_error() -> None:
    """An explicit stream error is not an accidental transport disconnect."""
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Return an authoritative in-band provider failure."""
        nonlocal count
        count += 1
        return httpx.Response(
            200, text='data: {"error":{"message":"budget denied"}}\n\n'
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(LLMProviderError, match="budget denied"):
            await make_provider(client).get_response(
                [{"role": "user", "content": "hi"}], stream=True
            )
    assert count == 1
