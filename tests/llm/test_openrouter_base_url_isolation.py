from __future__ import annotations

from types import SimpleNamespace

from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


def test_openrouter_gateway_ignores_openai_base_url(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fixture")

    class _Client:
        def __init__(self, *, base_url: str, api_key: str) -> None:
            self.base_url = base_url
            self.api_key = api_key

    monkeypatch.setattr("penguin.llm.adapters.openrouter.AsyncOpenAI", _Client)

    model_config = ModelConfig(
        model="z-ai/glm-5-turbo",
        provider="openrouter",
        client_preference="openrouter",
        api_key=None,
        streaming_enabled=True,
    )

    gateway = OpenRouterGateway(model_config)

    assert gateway.base_url == "https://openrouter.ai/api/v1"
    assert gateway.client.base_url == "https://openrouter.ai/api/v1"
    assert gateway.client.api_key == "sk-or-v1-fixture"


def test_openrouter_gateway_honors_openrouter_specific_base_url(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://proxy.example.test/v1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-fixture")

    monkeypatch.setattr(
        "penguin.llm.adapters.openrouter.AsyncOpenAI",
        lambda *, base_url, api_key: SimpleNamespace(
            base_url=base_url,
            api_key=api_key,
        ),
    )

    model_config = ModelConfig(
        model="z-ai/glm-5-turbo",
        provider="openrouter",
        client_preference="openrouter",
        api_key=None,
        streaming_enabled=True,
    )

    gateway = OpenRouterGateway(model_config)

    assert gateway.base_url == "https://proxy.example.test/v1"
    assert gateway.client.base_url == "https://proxy.example.test/v1"


def test_openrouter_gateway_rejects_placeholder_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")

    model_config = ModelConfig(
        model="z-ai/glm-5-turbo",
        provider="openrouter",
        client_preference="openrouter",
        api_key=None,
        streaming_enabled=True,
    )

    try:
        OpenRouterGateway(model_config)
    except ValueError as exc:
        assert "Missing OpenRouter API Key" in str(exc)
    else:
        raise AssertionError("Expected placeholder OpenRouter key to be rejected")
