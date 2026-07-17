"""SDK retry-budget regressions for native provider clients."""

from __future__ import annotations

from typing import Any

from penguin.llm.adapters.anthropic import AnthropicAdapter
from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


def test_anthropic_sdk_retries_are_disabled(monkeypatch) -> None:
    """Penguin, not the Anthropic SDK, owns the two-send retry limit."""

    captured: dict[str, dict[str, Any]] = {}

    class _SyncClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["sync"] = kwargs

    class _AsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["async"] = kwargs

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(
        "penguin.llm.adapters.anthropic.anthropic.Anthropic", _SyncClient
    )
    monkeypatch.setattr("penguin.llm.adapters.anthropic.AsyncAnthropic", _AsyncClient)

    AnthropicAdapter(
        ModelConfig(
            model="claude-test",
            provider="anthropic",
            client_preference="native",
        )
    )

    assert captured["sync"]["api_key"] == "sk-ant-test"
    assert captured["async"]["api_key"] == "sk-ant-test"
    assert captured["async"]["max_retries"] == 0


def test_openrouter_sdk_retries_are_disabled(monkeypatch) -> None:
    """Penguin's runtime budget includes OpenRouter's OpenAI-compatible SDK."""

    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    monkeypatch.setattr("penguin.llm.adapters.openrouter.AsyncOpenAI", _Client)

    OpenRouterGateway(
        ModelConfig(
            model="openai/gpt-test",
            provider="openrouter",
            client_preference="openrouter",
        )
    )

    assert captured["max_retries"] == 0
