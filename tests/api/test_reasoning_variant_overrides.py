"""Tests for provider-aware reasoning variant overrides in chat routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.model_config import ModelConfig
from penguin.llm.runtime import UnsupportedReasoningVariantError
from penguin.web.routes import (
    _apply_cached_provider_model_metadata,
    _apply_reasoning_variant_override,
    _restore_reasoning_variant_override,
)


def _core_with_model_config(
    provider: str,
    model: str,
    supported_reasoning_levels: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        model_config=SimpleNamespace(
            provider=provider,
            model=model,
            supported_reasoning_levels=supported_reasoning_levels,
            reasoning_enabled=False,
            reasoning_effort=None,
            reasoning_max_tokens=None,
            reasoning_exclude=False,
        )
    )


def test_openai_native_variant_rejects_unsupported_effort() -> None:
    """Unsupported native OpenAI efforts raise a structured error."""

    core = _core_with_model_config("openai", "gpt-5.1")

    with pytest.raises(UnsupportedReasoningVariantError):
        _apply_reasoning_variant_override(core, "xhigh")

    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None
    assert core.model_config.reasoning_max_tokens is None


def test_openai_metadata_variant_allows_ultra_when_advertised() -> None:
    """Advertised Codex Ultra metadata enables an Ultra request override."""

    core = _core_with_model_config(
        "openai",
        "gpt-5.6-sol",
        ["low", "medium", "high", "xhigh", "max", "ultra"],
    )

    snapshot = _apply_reasoning_variant_override(core, "ultra")

    assert isinstance(snapshot, dict)
    assert core.model_config.reasoning_enabled is True
    assert core.model_config.reasoning_effort == "ultra"
    assert core.model_config.reasoning_max_tokens is None


def test_openai_metadata_variant_rejects_ultra_when_not_advertised() -> None:
    """Unadvertised Ultra variants raise a structured validation error."""

    core = _core_with_model_config(
        "openai",
        "gpt-5.6-luna",
        ["low", "medium", "high", "max"],
    )

    with pytest.raises(UnsupportedReasoningVariantError):
        _apply_reasoning_variant_override(core, "ultra")

    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None


def test_anthropic_native_variant_allows_max_for_opus_46() -> None:
    core = _core_with_model_config("anthropic", "claude-opus-4-6")

    snapshot = _apply_reasoning_variant_override(core, "max")

    assert isinstance(snapshot, dict)
    assert core.model_config.reasoning_enabled is True
    assert core.model_config.reasoning_effort == "max"
    assert core.model_config.reasoning_max_tokens is None

    _restore_reasoning_variant_override(core, snapshot)
    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None
    assert core.model_config.reasoning_max_tokens is None


def test_anthropic_native_variant_rejects_max_for_sonnet_46() -> None:
    """Unsupported native Anthropic Max raises a structured error."""

    core = _core_with_model_config("anthropic", "claude-sonnet-4-6")

    with pytest.raises(UnsupportedReasoningVariantError):
        _apply_reasoning_variant_override(core, "max")

    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None


def test_anthropic_metadata_variant_rejects_ultra() -> None:
    """Anthropic adapter capabilities reject Ultra despite bad metadata."""

    core = _core_with_model_config(
        "anthropic",
        "claude-opus-4-6",
        ["low", "medium", "high", "max", "ultra"],
    )

    api_client = SimpleNamespace(
        get_provider_capabilities=lambda: SimpleNamespace(
            reasoning_efforts=("low", "medium", "high", "max")
        )
    )
    with pytest.raises(UnsupportedReasoningVariantError):
        _apply_reasoning_variant_override(core, "ultra", api_client=api_client)

    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None


@pytest.mark.asyncio
async def test_cached_codex_ultra_reaches_openai_safe_prepared_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cached Codex metadata survives runtime validation and request preparation."""

    oauth_record = {
        "type": "oauth",
        "access": "oauth-test-token",
        "accountId": "account-test",
    }
    monkeypatch.setattr(
        "penguin.web.routes.get_provider_auth_records",
        lambda: {"openai": oauth_record},
    )
    monkeypatch.setattr(
        "penguin.web.routes.codex_oauth_cached_provider_models",
        lambda _record: {
            "openai": {
                "gpt-5.6-sol": {
                    "supported_reasoning_levels": [
                        "none",
                        "low",
                        "medium",
                        "high",
                        "xhigh",
                        "max",
                        "ultra",
                    ],
                    "default_reasoning_level": "low",
                }
            }
        },
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda _provider_id: oauth_record,
    )
    model_config = ModelConfig(
        model="gpt-5.6-sol",
        provider="openai",
        client_preference="native",
        api_key="oauth-test-token",
    )
    adapter = OpenAIAdapter(model_config)
    api_client = SimpleNamespace(get_provider_capabilities=adapter.get_capabilities)
    core = SimpleNamespace(model_config=model_config)

    _apply_cached_provider_model_metadata(model_config)
    snapshot = _apply_reasoning_variant_override(
        core,
        "ultra",
        model_config=model_config,
        api_client=api_client,
    )
    prepared = await adapter.prepare_request(
        [{"role": "user", "content": "ping"}],
        stream=False,
    )

    assert isinstance(snapshot, dict)
    assert model_config.supported_reasoning_levels[-1] == "ultra"
    assert prepared.route == "openai.codex_oauth.responses"
    assert prepared.body["reasoning"]["effort"] == "max"
