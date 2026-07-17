from __future__ import annotations

import logging

import pytest

from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.llm.prompt_cache import build_prompt_cache_key
from penguin.system.execution_context import ExecutionContext, execution_context_scope


def test_prompt_cache_key_is_stable_scoped_and_bounded() -> None:
    first = build_prompt_cache_key(
        session_id="session-one",
        provider="openai",
        model="gpt-5.4",
        variant="medium",
    )
    repeat = build_prompt_cache_key(
        session_id="session-one",
        provider="openai",
        model="gpt-5.4",
        variant="medium",
    )
    other_session = build_prompt_cache_key(
        session_id="session-two",
        provider="openai",
        model="gpt-5.4",
        variant="medium",
    )

    assert first == repeat
    assert first != other_session
    assert first is not None
    assert len(first) <= 64
    assert "session-one" not in first


def test_api_client_adds_cache_affinity_only_for_openai_family() -> None:
    openai_client = APIClient.__new__(APIClient)
    openai_client.model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
    )
    openai_client._last_prompt_cache_key = None
    openai_kwargs = openai_client._with_prompt_cache_key(
        {"reasoning_effort": "medium"},
        session_id="session-one",
    )

    openrouter_client = APIClient.__new__(APIClient)
    openrouter_client.model_config = ModelConfig(
        model="openrouter/model",
        provider="openrouter",
        client_preference="openrouter",
    )
    openrouter_client._last_prompt_cache_key = None
    openrouter_kwargs = openrouter_client._with_prompt_cache_key(
        {},
        session_id="session-one",
    )

    assert isinstance(openai_kwargs.get("prompt_cache_key"), str)
    assert "prompt_cache_key" not in openrouter_kwargs


@pytest.mark.asyncio
async def test_api_client_forwards_session_affinity_to_provider_handler() -> None:
    class Handler:
        received: dict[str, object] = {}

        async def get_response(self, **kwargs: object) -> str:
            self.received = dict(kwargs)
            return "ok"

    handler = Handler()
    client = APIClient.__new__(APIClient)
    client.model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
    )
    client.system_prompt = None
    client.client_handler = handler
    client.logger = logging.getLogger(__name__)
    client._last_error = None
    client._last_response_result = None
    client._last_prompt_cache_key = None
    client._last_request_accounting = {}
    client._clear_handler_error = lambda: None
    client._get_handler_error = lambda: None
    client._build_response_result = lambda **_kwargs: None
    client._prepare_messages_with_system_prompt = lambda messages: messages
    client.count_tokens = lambda _messages: 3

    with execution_context_scope(ExecutionContext(session_id="session-one")):
        result = await client.get_response(
            [{"role": "user", "content": "hello"}],
            stream=False,
        )

    assert result == "ok"
    assert isinstance(handler.received.get("prompt_cache_key"), str)
    assert client.get_last_request_accounting()["message_count"] == 1
    assert client.get_last_request_accounting()["estimated_input_tokens"] == 3
