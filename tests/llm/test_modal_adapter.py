"""Contract tests for Modal Auto Endpoint inference."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.llm.model_config import ModelConfig
from tests.llm.provider_contract_fixtures import (
    OPENROUTER_USAGE,
    OpenRouterClientStub,
    OpenRouterStream,
)


def test_modal_adapter_prepares_chat_completions_request_with_proxy_headers() -> None:
    from penguin.llm.adapters.modal import ModalAdapter

    adapter = ModalAdapter(
        ModelConfig(
            model="moonshotai/Kimi-K3",
            provider="modal",
            client_preference="native",
            api_base="https://example.modal.direct",
            streaming_enabled=True,
            vision_enabled=True,
        ),
        proxy_token_id="modal-token-id",
        proxy_token_secret="modal-token-secret",
    )

    request = adapter.prepare_request_sync(
        [{"role": "user", "content": "Hello"}],
        max_output_tokens=512,
        stream=True,
    )

    assert request.route == "modal.chat_completions"
    assert request.url == "https://example.modal.direct/v1/chat/completions"
    assert request.headers == {
        "Modal-Key": "modal-token-id",
        "Modal-Secret": "modal-token-secret",
    }
    assert request.to_dict()["headers"] == {
        "Modal-Key": "[REDACTED]",
        "Modal-Secret": "[REDACTED]",
    }
    assert request.body == {
        "model": "moonshotai/Kimi-K3",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 512,
        "temperature": 0.7,
        "stream": True,
        "reasoning_effort": "max",
        "stream_options": {"include_usage": True},
    }


def test_modal_adapter_advertises_kimi_reasoning_and_tools() -> None:
    from penguin.llm.adapters.modal import ModalAdapter

    adapter = ModalAdapter(
        ModelConfig(
            model="moonshotai/Kimi-K3",
            provider="modal",
            client_preference="native",
            api_base="https://example.modal.direct/v1/",
            vision_enabled=True,
        ),
        proxy_token_id="modal-token-id",
        proxy_token_secret="modal-token-secret",
    )

    capabilities = adapter.get_capabilities()

    assert capabilities.provider == "modal"
    assert capabilities.vision is True
    assert capabilities.streaming is False
    assert capabilities.native_tools is True
    assert capabilities.reasoning is True
    assert capabilities.reasoning_efforts == ("low", "high", "max")


def test_modal_adapter_prepares_reasoning_and_tool_request() -> None:
    from penguin.llm.adapters.modal import ModalAdapter

    adapter = ModalAdapter(
        ModelConfig(
            model="moonshotai/Kimi-K3",
            provider="modal",
            client_preference="native",
            api_base="https://example.modal.direct",
            reasoning_enabled=True,
            reasoning_effort="high",
        ),
        proxy_token_id="modal-token-id",
        proxy_token_secret="modal-token-secret",
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
        }
    ]

    request = adapter.prepare_request_sync(
        [{"role": "user", "content": "Inspect the repository"}],
        tools=tools,
        tool_choice="auto",
    )

    assert request.body["reasoning_effort"] == "high"
    assert "reasoning" not in request.body
    assert request.body["tools"] == tools
    assert request.body["tool_choice"] == "auto"


@pytest.mark.asyncio
async def test_modal_adapter_streams_kimi_reasoning_and_structured_tool_calls() -> None:
    from penguin.llm.adapters.modal import ModalAdapter

    adapter = ModalAdapter(
        ModelConfig(
            model="moonshotai/Kimi-K3",
            provider="modal",
            client_preference="native",
            api_base="https://example.modal.direct",
            streaming_enabled=True,
            reasoning_enabled=True,
            reasoning_effort="low",
            interrupt_on_tool_call=True,
        ),
        proxy_token_id="modal-token-id",
        proxy_token_secret="modal-token-secret",
    )
    chunks = [
        SimpleNamespace(
            id="chatcmpl-modal-test",
            model="moonshotai/Kimi-K3",
            error=None,
            choices=[
                {
                    "delta": {
                        "content": None,
                        "reasoning_content": "I should inspect the file.",
                        "tool_calls": None,
                    },
                    "finish_reason": None,
                }
            ],
            usage=None,
        ),
        SimpleNamespace(
            id="chatcmpl-modal-test",
            model="moonshotai/Kimi-K3",
            error=None,
            choices=[
                {
                    "delta": {
                        "content": None,
                        "reasoning_content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_modal_read",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"README.md"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            usage=OPENROUTER_USAGE,
        ),
    ]
    create_response = SimpleNamespace(
        choices=[],
        usage=OPENROUTER_USAGE,
        error=None,
    )
    client = OpenRouterClientStub(
        stream_response=OpenRouterStream(chunks),
        create_response=create_response,
    )
    adapter.client = client  # type: ignore[assignment]

    async def fail_direct_transport(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("Modal reasoning must use the OpenAI SDK transport")

    adapter._direct_api_call_with_reasoning = fail_direct_transport  # type: ignore[method-assign]
    streamed: list[tuple[str, str]] = []

    async def stream_callback(text: str, message_type: str) -> None:
        streamed.append((text, message_type))

    result = await adapter.get_response(
        [{"role": "user", "content": "Inspect the repository"}],
        stream=True,
        stream_callback=stream_callback,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_choice="auto",
    )

    request = client.chat.completions.last_kwargs
    assert result == ""
    assert streamed == [("I should inspect the file.", "reasoning")]
    assert request is not None
    assert request["reasoning_effort"] == "low"
    assert "reasoning" not in request
    assert request["tool_choice"] == "auto"
    assert adapter.get_and_clear_pending_tool_calls() == [
        {
            "item_id": None,
            "call_id": "call_modal_read",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        }
    ]


def test_modal_adapter_rejects_missing_or_non_https_endpoint(monkeypatch) -> None:
    from penguin.llm.adapters.modal import ModalAdapter

    monkeypatch.delenv("MODAL_ENDPOINT", raising=False)

    config = ModelConfig(
        model="moonshotai/Kimi-K3",
        provider="modal",
        client_preference="native",
    )

    for api_base in (None, "http://example.modal.direct", "https://example.com/not-v1"):
        config.api_base = api_base
        try:
            ModalAdapter(
                config,
                proxy_token_id="modal-token-id",
                proxy_token_secret="modal-token-secret",
            )
        except ValueError:
            continue
        raise AssertionError(f"Expected ModalAdapter to reject {api_base!r}")


def test_modal_adapter_uses_endpoint_from_runtime_environment(monkeypatch) -> None:
    from penguin.llm.adapters.modal import ModalAdapter

    monkeypatch.setenv("MODAL_ENDPOINT", "https://example.modal.direct")

    adapter = ModalAdapter(
        ModelConfig(
            model="moonshotai/Kimi-K3",
            provider="modal",
            client_preference="native",
        ),
        proxy_token_id="modal-token-id",
        proxy_token_secret="modal-token-secret",
    )

    assert adapter.base_url == "https://example.modal.direct/v1"
