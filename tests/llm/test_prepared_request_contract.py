from __future__ import annotations

import logging

import pytest

from penguin.llm.api_client import APIClient
from penguin.llm.contracts import (
    LLMPreparedRequest,
    LLMProviderCapabilities,
    stable_payload_hash,
)
from penguin.llm.model_config import ModelConfig

from .provider_contract_fixtures import (
    ANTHROPIC_USAGE,
    OPENAI_USAGE,
    OPENROUTER_USAGE,
    build_anthropic_handler,
    build_openai_handler,
    build_openrouter_handler,
)


def _messages() -> list[dict[str, object]]:
    return [
        {"role": "system", "content": "System rules."},
        {"role": "user", "content": "Hello"},
    ]


def _tool_schema() -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }
    ]


def test_stable_payload_hash_is_deterministic() -> None:
    first = {"b": [2, 1], "a": {"nested": True}}
    second = {"a": {"nested": True}, "b": [2, 1]}

    assert stable_payload_hash(first) == stable_payload_hash(second)


def test_prepared_request_serializes_capabilities() -> None:
    prepared = LLMPreparedRequest(
        provider="fixture",
        model="model-a",
        protocol="fixture_protocol",
        route="fixture.route",
        body={"model": "model-a", "input": "hello"},
        capabilities=LLMProviderCapabilities(
            provider="fixture",
            model="model-a",
            native_tools=True,
        ),
    )

    payload = prepared.to_dict()

    assert payload["request_payload_hash"] == stable_payload_hash(prepared.body)
    assert payload["capabilities"]["native_tools"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_id", ["openai", "openai_compatible"])
async def test_openai_family_prepares_responses_request(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )
    handler = build_openai_handler(
        provider=provider_id,
        stream_events=[],
        final_text="answer",
        usage=OPENAI_USAGE,
    )

    prepared = await handler.prepare_request(
        _messages(),
        max_output_tokens=123,
        stream=True,
        tools=_tool_schema(),
        tool_choice="auto",
    )

    assert prepared.provider == provider_id
    assert prepared.protocol == "openai_responses"
    assert prepared.route == "openai.responses"
    assert prepared.transport == "sdk_stream"
    assert prepared.body["model"] == "gpt-5.4"
    assert "input" in prepared.body
    assert prepared.body["max_output_tokens"] == 123
    assert prepared.body["tools"][0]["type"] == "function"
    assert prepared.body["tool_choice"] == "auto"
    assert prepared.capabilities is not None
    assert prepared.capabilities.native_tools is True
    assert prepared.capabilities.prompt_cache is True


@pytest.mark.asyncio
async def test_openai_prepared_request_keeps_prompt_cache_affinity_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )
    handler = build_openai_handler(
        provider="openai",
        stream_events=[],
        final_text="answer",
        usage=OPENAI_USAGE,
    )

    prepared = await handler.prepare_request(
        _messages(),
        stream=True,
        prompt_cache_key="penguin_0123456789abcdef",
    )

    assert prepared.body["prompt_cache_key"] == "penguin_0123456789abcdef"


@pytest.mark.asyncio
async def test_openai_prepare_codex_oauth_route_does_not_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail_refresh(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("prepare_request must not refresh OAuth credentials")

    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: {
            "type": "oauth",
            "access": "oauth-access",
            "refresh": "oauth-refresh",
            "expires": 0,
        },
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.refresh_provider_oauth",
        _fail_refresh,
    )
    handler = build_openai_handler(
        provider="openai",
        stream_events=[],
        final_text="answer",
        usage=OPENAI_USAGE,
    )

    prepared = await handler.prepare_request(_messages(), stream=False)

    assert prepared.route == "openai.codex_oauth.responses"
    assert prepared.transport == "http_sse"
    assert prepared.body["store"] is False
    assert "Authorization" not in prepared.headers


@pytest.mark.asyncio
async def test_anthropic_prepares_messages_request() -> None:
    handler = build_anthropic_handler(
        stream_chunks=[],
        final_text="answer",
        usage=ANTHROPIC_USAGE,
    )
    tools = [
        {
            "name": "read_file",
            "description": "Read a file",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        }
    ]

    prepared = await handler.prepare_request(
        _messages(),
        max_output_tokens=321,
        temperature=0.2,
        stream=True,
        tools=tools,
    )

    assert prepared.provider == "anthropic"
    assert prepared.protocol == "anthropic_messages"
    assert prepared.route == "anthropic.messages"
    assert prepared.transport == "sdk_stream"
    assert prepared.body["system"] == "System rules."
    assert prepared.body["max_tokens"] == 321
    assert prepared.body["temperature"] == 0.2
    assert prepared.body["messages"][0]["role"] == "user"
    assert prepared.body["tools"] == tools
    assert prepared.capabilities is not None
    assert prepared.capabilities.native_tools is True


@pytest.mark.asyncio
async def test_openrouter_prepares_chat_completions_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = build_openrouter_handler(
        monkeypatch,
        stream_chunks=[],
        final_text="answer",
        usage=OPENROUTER_USAGE,
    )
    handler.extra_headers["X-Test"] = "prepared"

    prepared = await handler.prepare_request(
        _messages(),
        max_output_tokens=456,
        temperature=0.3,
        stream=True,
        tools=_tool_schema(),
    )

    assert prepared.provider == "openrouter"
    assert prepared.protocol == "openai_chat_completions"
    assert prepared.route == "openrouter.chat_completions"
    assert prepared.transport == "sdk_stream"
    assert prepared.headers["X-Test"] == "prepared"
    assert prepared.body["model"] == "openai/gpt-4.1-mini"
    assert prepared.body["max_tokens"] == 456
    assert prepared.body["temperature"] == 0.3
    assert prepared.body["stream"] is True
    assert prepared.body["stream_options"] == {"include_usage": True}
    assert "extra_headers" not in prepared.body
    assert prepared.body["tools"][0]["type"] == "function"


@pytest.mark.asyncio
async def test_api_client_delegates_prepared_request_to_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: None,
    )
    handler = build_openai_handler(
        provider="openai",
        stream_events=[],
        final_text="answer",
        usage=OPENAI_USAGE,
    )
    client = APIClient.__new__(APIClient)
    client.model_config = handler.model_config
    client.system_prompt = "Injected system prompt."
    client.client_handler = handler
    client.logger = logging.getLogger(__name__)

    prepared = await client.prepare_request(
        [{"role": "user", "content": "Hello"}],
        max_output_tokens=111,
        stream=False,
    )

    assert prepared.protocol == "openai_responses"
    assert "Injected system prompt." in str(prepared.body["input"])
    assert prepared.body["max_output_tokens"] == 111


@pytest.mark.asyncio
async def test_api_client_does_not_synthesize_max_tokens_from_context_window() -> None:
    class _Handler:
        model_config = None
        received_max_output_tokens: int | None = -1

        def get_capabilities(self) -> LLMProviderCapabilities:
            return LLMProviderCapabilities(provider="openrouter")

        async def get_response(self, **kwargs: object) -> str:
            value = kwargs.get("max_output_tokens")
            self.received_max_output_tokens = value if isinstance(value, int) else None
            return "ok"

    handler = _Handler()
    client = APIClient.__new__(APIClient)
    client.model_config = ModelConfig(
        model="moonshotai/kimi-k2.6",
        provider="openrouter",
        client_preference="openrouter",
    )
    client.model_config.max_context_window_tokens = 272000
    client.model_config.max_output_tokens = None
    client.system_prompt = None
    client.client_handler = handler
    client.logger = logging.getLogger(__name__)
    client._last_error = None
    client._last_response_result = None
    client._clear_handler_error = lambda: None
    client._get_handler_error = lambda: None
    client._build_response_result = lambda **kwargs: None
    client._prepare_messages_with_system_prompt = lambda messages: messages
    client.count_tokens = lambda _messages: 46421

    result = await client.get_response(_messages(), stream=False)

    assert result == "ok"
    assert handler.received_max_output_tokens is None


@pytest.mark.asyncio
async def test_api_client_clamps_explicit_max_tokens_to_available_context() -> None:
    class _Handler:
        model_config = None
        received_max_output_tokens: int | None = None

        def get_capabilities(self) -> LLMProviderCapabilities:
            return LLMProviderCapabilities(provider="openrouter")

        async def get_response(self, **kwargs: object) -> str:
            value = kwargs.get("max_output_tokens")
            self.received_max_output_tokens = value if isinstance(value, int) else None
            return "ok"

    handler = _Handler()
    client = APIClient.__new__(APIClient)
    client.model_config = ModelConfig(
        model="moonshotai/kimi-k2.6",
        provider="openrouter",
        client_preference="openrouter",
    )
    client.model_config.max_context_window_tokens = 272000
    client.model_config.max_output_tokens = 100000
    client.system_prompt = None
    client.client_handler = handler
    client.logger = logging.getLogger(__name__)
    client._last_error = None
    client._last_response_result = None
    client._clear_handler_error = lambda: None
    client._get_handler_error = lambda: None
    client._build_response_result = lambda **kwargs: None
    client._prepare_messages_with_system_prompt = lambda messages: messages
    client.count_tokens = lambda _messages: 225000

    result = await client.get_response(_messages(), stream=False)

    assert result == "ok"
    assert handler.received_max_output_tokens == 46488
