"""Tests for Anthropic output_config effort mapping."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.llm.adapters.anthropic import AnthropicAdapter
from penguin.llm.model_config import ModelConfig


class _Response:
    content: list[Any] = []
    stop_reason = "end_turn"
    usage: dict[str, Any] = {}

    def model_dump(self) -> dict[str, Any]:
        return {"ok": True}


class _Messages:
    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _Response:
        self.last_kwargs = dict(kwargs)
        return _Response()


def _build_adapter(config: ModelConfig) -> tuple[AnthropicAdapter, _Messages]:
    messages = _Messages()
    adapter = AnthropicAdapter.__new__(AnthropicAdapter)
    adapter.model_config = config
    adapter.async_client = SimpleNamespace(messages=messages)
    adapter.logger = logging.getLogger(__name__)
    return adapter, messages


@pytest.mark.asyncio
async def test_anthropic_completion_maps_effort_to_output_config() -> None:
    config = ModelConfig(
        model="claude-opus-4-6",
        provider="anthropic",
        client_preference="native",
        api_key="sk-ant",
        reasoning_enabled=True,
        reasoning_effort="max",
        streaming_enabled=False,
    )
    adapter, messages = _build_adapter(config)

    await adapter.create_completion(
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert messages.last_kwargs is not None
    assert messages.last_kwargs["extra_body"]["output_config"]["effort"] == "max"


@pytest.mark.asyncio
async def test_anthropic_completion_ignores_unsupported_effort_values() -> None:
    config = ModelConfig(
        model="claude-sonnet-4-6",
        provider="anthropic",
        client_preference="native",
        api_key="sk-ant",
        reasoning_enabled=True,
        reasoning_effort="xhigh",
        streaming_enabled=False,
    )
    adapter, messages = _build_adapter(config)

    await adapter.create_completion(
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert messages.last_kwargs is not None
    assert "extra_body" not in messages.last_kwargs
