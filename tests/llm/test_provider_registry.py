from __future__ import annotations

from typing import Any

from penguin.llm.model_config import ModelConfig
from penguin.llm.provider_registry import ProviderRegistry


def _unused_litellm_loader(feature: str) -> Any:
    raise AssertionError(f"LiteLLM loader should not be used: {feature}")


def test_provider_registry_routes_openai_compatible_native_adapter(
    monkeypatch,
) -> None:
    from penguin.llm.adapters import openai_compatible as adapter_module

    captured: dict[str, Any] = {}

    class _Adapter:
        def __init__(self, model_config: ModelConfig) -> None:
            captured["provider"] = model_config.provider
            captured["model"] = model_config.model
            captured["api_base"] = model_config.api_base

    monkeypatch.setattr(adapter_module, "OpenAICompatibleAdapter", _Adapter)

    registry = ProviderRegistry(
        native_adapter_factory=lambda *_args: (_ for _ in ()).throw(
            AssertionError("native adapter factory should not be used")
        ),
        litellm_gateway_loader=_unused_litellm_loader,
    )
    config = ModelConfig(
        model="openai/gpt-4.1-mini",
        provider="openai-compatible",
        client_preference="native",
        api_key="test-key",
    )

    handler = registry.create_handler(
        config,
        base_url="http://localhost:8080/v1",
    )

    assert isinstance(handler, _Adapter)
    assert captured == {
        "provider": "openai_compatible",
        "model": "gpt-4.1-mini",
        "api_base": "http://localhost:8080/v1",
    }


def test_provider_registry_routes_openrouter_gateway_with_context(
    monkeypatch,
) -> None:
    from penguin.llm import openrouter_gateway as gateway_module

    captured: dict[str, Any] = {}

    class _Gateway:
        def __init__(
            self,
            model_config: ModelConfig,
            base_url: str | None = None,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            captured["provider"] = model_config.provider
            captured["model"] = model_config.model
            captured["base_url"] = base_url
            captured["extra_headers"] = dict(extra_headers or {})
            self.extra_headers = dict(extra_headers or {})

    monkeypatch.setattr(gateway_module, "OpenRouterGateway", _Gateway)

    registry = ProviderRegistry(
        native_adapter_factory=lambda *_args: None,
        litellm_gateway_loader=_unused_litellm_loader,
    )
    config = ModelConfig(
        model="openai/gpt-4o",
        provider="openrouter",
        client_preference="openrouter",
    )

    handler = registry.create_handler(
        config,
        base_url="http://localhost:3001/api/v1",
        extra_headers={"X-Link-User-Id": "user-123"},
    )

    assert isinstance(handler, _Gateway)
    assert captured == {
        "provider": "openrouter",
        "model": "openai/gpt-4o",
        "base_url": "http://localhost:3001/api/v1",
        "extra_headers": {"X-Link-User-Id": "user-123"},
    }
