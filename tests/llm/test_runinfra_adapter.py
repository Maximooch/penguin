"""Contract tests for RunInfra Inference API integration."""

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


def test_runinfra_adapter_prepares_chat_completions_request_with_bearer_auth() -> None:
    from penguin.llm.adapters.runinfra import RunInfraAdapter

    adapter = RunInfraAdapter(
        ModelConfig(
            model="deepseek-v4-flash",
            provider="runinfra",
            client_preference="native",
            api_key="runinfra-test-key",
            streaming_enabled=True,
        )
    )

    request = adapter.prepare_request_sync(
        [{"role": "user", "content": "Hello"}],
        max_output_tokens=512,
        stream=True,
    )

    assert request.route == "runinfra.chat_completions"
    assert request.url == "https://api.runinfra.ai/v1/chat/completions"
    assert request.to_dict()["headers"] == {}
    assert request.body == {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": "Hello"}],
        "max_tokens": 512,
        "temperature": 0.7,
        "stream": True,
        "reasoning_effort": "medium",
        "stream_options": {"include_usage": True},
    }


def test_runinfra_adapter_advertises_deepseek_v4_reasoning_and_tools() -> None:
    from penguin.llm.adapters.runinfra import RunInfraAdapter

    adapter = RunInfraAdapter(
        ModelConfig(
            model="deepseek-v4-flash",
            provider="runinfra",
            client_preference="native",
            api_key="runinfra-test-key",
            vision_enabled=False,
        )
    )

    capabilities = adapter.get_capabilities()

    assert capabilities.provider == "runinfra"
    assert capabilities.vision is False
    assert capabilities.streaming is False
    assert capabilities.native_tools is True
    assert capabilities.reasoning is True
    assert capabilities.reasoning_efforts == ("low", "medium", "high")


def test_runinfra_adapter_prepares_reasoning_and_tool_request() -> None:
    from penguin.llm.adapters.runinfra import RunInfraAdapter

    adapter = RunInfraAdapter(
        ModelConfig(
            model="deepseek-v4-flash",
            provider="runinfra",
            client_preference="native",
            api_key="runinfra-test-key",
            reasoning_enabled=True,
            reasoning_effort="high",
        )
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
async def test_runinfra_adapter_streams_reasoning_and_tool_calls() -> None:
    from penguin.llm.adapters.runinfra import RunInfraAdapter

    adapter = RunInfraAdapter(
        ModelConfig(
            model="deepseek-v4-flash",
            provider="runinfra",
            client_preference="native",
            api_key="runinfra-test-key",
            streaming_enabled=True,
            reasoning_enabled=True,
            reasoning_effort="low",
            interrupt_on_tool_call=True,
        )
    )
    chunks = [
        SimpleNamespace(
            id="chatcmpl-runinfra-test",
            model="deepseek-v4-flash",
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
            id="chatcmpl-runinfra-test",
            model="deepseek-v4-flash",
            error=None,
            choices=[
                {
                    "delta": {
                        "content": None,
                        "reasoning_content": None,
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_runinfra_read",
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
            "call_id": "call_runinfra_read",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        }
    ]


def test_runinfra_adapter_rejects_missing_or_non_https_endpoint(monkeypatch) -> None:
    from penguin.llm.adapters.runinfra import RunInfraAdapter

    monkeypatch.delenv("RUNINFRA_GATEWAY_KEY", raising=False)

    config = ModelConfig(
        model="deepseek-v4-flash",
        provider="runinfra",
        client_preference="native",
        api_key="runinfra-test-key",
    )

    # A missing endpoint falls back to the documented default; only invalid
    # URLs should be rejected.
    for api_base in ("http://foo.runinfra.ai", "https://api.runinfra.ai/v1/extra"):
        config.api_base = api_base
        try:
            RunInfraAdapter(config)
        except ValueError:
            continue
        raise AssertionError(f"Expected RunInfraAdapter to reject {api_base!r}")

    config.api_base = None
    adapter = RunInfraAdapter(config)
    assert adapter.base_url == "https://api.runinfra.ai/v1"


def test_runinfra_adapter_uses_api_key_from_environment(monkeypatch) -> None:
    from penguin.llm.adapters.runinfra import RunInfraAdapter

    monkeypatch.delenv("RUNINFRA_GATEWAY_KEY", raising=False)
    monkeypatch.setenv("RUNINFRA_GATEWAY_KEY", "env-runinfra-key")

    adapter = RunInfraAdapter(
        ModelConfig(
            model="deepseek-v4-flash",
            provider="runinfra",
            client_preference="native",
        )
    )

    assert adapter.base_url == "https://api.runinfra.ai/v1"
    assert adapter.client.api_key == "env-runinfra-key"


def test_runinfra_native_tool_format_uses_openai_chat_contract() -> None:
    """Regression: native tool schemas must reach runinfra chat completions.

    Without this, ``native_tool_format()`` returns None for runinfra and the
    engine sends zero tools, so the model answers in prose and the agent loop
    ends after a single iteration.
    """
    from penguin.llm.provider_transform import native_tool_format

    config = ModelConfig(
        model="deepseek-v4-flash",
        provider="runinfra",
        client_preference="native",
        api_key="runinfra-test-key",
    )

    assert native_tool_format(config) == "openai_chat"

    config.native_tools = False
    assert native_tool_format(config) is None


def test_runinfra_adapter_supports_qualified_pro_model_id() -> None:
    """DeepSeek V4 Pro uses a qualified model id on RunInfra."""
    from penguin.llm.adapters.runinfra import RunInfraAdapter

    adapter = RunInfraAdapter(
        ModelConfig(
            model="deepseek-ai/DeepSeek-V4-Pro-0813",
            provider="runinfra",
            client_preference="native",
            api_key="runinfra-test-key",
            max_context_window_tokens=1_048_576,
            max_output_tokens=32768,
        )
    )

    request = adapter.prepare_request_sync(
        [{"role": "user", "content": "Hello"}],
        stream=False,
    )

    assert request.body["model"] == "deepseek-ai/DeepSeek-V4-Pro-0813"
    assert request.body["reasoning_effort"] == "medium"

    capabilities = adapter.get_capabilities()
    assert capabilities.max_context_tokens == 1_048_576
    assert capabilities.max_output_tokens == 32768
    assert capabilities.reasoning_efforts == ("low", "medium", "high")