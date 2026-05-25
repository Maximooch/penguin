"""Tests for core model-runtime resolution helpers."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, strategies as st

from penguin.core_runtime.model_runtime import (
    build_model_config_for_model,
    canonicalize_runtime_model_id,
    current_model_payload,
    list_available_models,
    resolve_model_provider,
)
from penguin.llm.model_config import ModelConfig


def test_canonicalize_runtime_model_id_table() -> None:
    cases = [
        ("openai/gpt-4o", "openai", "native", "gpt-4o"),
        ("anthropic/claude-3-5-sonnet", "anthropic", "native", "claude-3-5-sonnet"),
        ("openrouter/openai/gpt-4o", "openrouter", "openrouter", "openai/gpt-4o"),
        ("openai/gpt-4o", "openai", "openrouter", "openai/gpt-4o"),
        ("google/gemini-2.5-pro", "google", "native", "google/gemini-2.5-pro"),
    ]

    for model_id, provider, client_preference, expected in cases:
        assert (
            canonicalize_runtime_model_id(model_id, provider, client_preference)
            == expected
        )


@given(
    model_name=st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"),
            whitelist_characters="-_.",
        ),
        min_size=1,
        max_size=50,
    ).filter(lambda value: "/" not in value and value.strip() == value),
)
def test_native_openai_prefix_is_stripped_for_any_local_model_name(
    model_name: str,
) -> None:
    assert (
        canonicalize_runtime_model_id(
            f"openai/{model_name}",
            "openai",
            "native",
        )
        == model_name
    )


_MODEL_ID_PART = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"),
        whitelist_characters="-_.",
    ),
    min_size=1,
    max_size=40,
).filter(lambda value: value.strip() == value)


@given(provider=_MODEL_ID_PART, model=_MODEL_ID_PART)
def test_openrouter_prefix_is_stripped_without_touching_provider_model(
    provider: str,
    model: str,
) -> None:
    provider_model = f"{provider}/{model}"

    assert (
        canonicalize_runtime_model_id(
            f"openrouter/{provider_model}",
            "openrouter",
            "openrouter",
        )
        == provider_model
    )


def test_resolve_model_provider_prefers_configured_model_entry() -> None:
    model_configs = {
        "fast": {
            "model": "openai/gpt-4o-mini",
            "provider": "openai",
            "client_preference": "native",
        }
    }

    assert resolve_model_provider("fast", model_configs) == ("openai", "native")


def test_resolve_model_provider_unknown_unqualified_fails_closed() -> None:
    assert resolve_model_provider("not-configured", {}) == (None, "")


def test_list_available_models_filters_invalid_entries_and_sorts_current_first() -> (
    None
):
    model_configs = {
        "b": {"model": "openai/gpt-4o", "provider": "openai"},
        "a": {"model": "anthropic/claude", "provider": "anthropic"},
        "bad": "not a config",
    }

    assert list_available_models(model_configs, current_model_name="openai/gpt-4o") == [
        {
            "id": "b",
            "name": "openai/gpt-4o",
            "provider": "openai",
            "client_preference": "openrouter",
            "vision_enabled": False,
            "max_output_tokens": None,
            "temperature": None,
            "current": True,
        },
        {
            "id": "a",
            "name": "anthropic/claude",
            "provider": "anthropic",
            "client_preference": "openrouter",
            "vision_enabled": False,
            "max_output_tokens": None,
            "temperature": None,
            "current": False,
        },
    ]


def test_current_model_payload_uses_explicit_output_token_name() -> None:
    model_config = ModelConfig(
        model="gpt-4o",
        provider="openai",
        client_preference="native",
        max_output_tokens=4096,
        max_context_window_tokens=128000,
        streaming_enabled=True,
    )

    payload = current_model_payload(model_config)

    assert payload is not None
    assert payload["max_output_tokens"] == 4096
    assert "max_tokens" not in payload


@pytest.mark.asyncio
async def test_build_model_config_for_model_uses_config_without_fetching_specs() -> (
    None
):
    async def _raise_if_called(_model_id: str) -> dict[str, Any]:
        raise AssertionError(
            "native configured models should not fetch OpenRouter specs"
        )

    model_config, safe_window = await build_model_config_for_model(
        "gpt-4",
        model_configs={
            "gpt-4": {
                "model": "openai/gpt-4",
                "provider": "openai",
                "client_preference": "native",
                "max_output_tokens": 8000,
                "max_context_window_tokens": 128000,
            }
        },
        fetch_specs=_raise_if_called,
    )

    assert model_config.model == "gpt-4"
    assert model_config.provider == "openai"
    assert model_config.client_preference == "native"
    assert model_config.max_output_tokens == 8000
    assert model_config.max_context_window_tokens == 128000
    assert model_config.max_history_tokens == 108800
    assert safe_window == 108800


@pytest.mark.asyncio
async def test_build_model_config_for_model_fetches_openrouter_specs() -> None:
    async def _fetch_specs(model_id: str) -> dict[str, Any]:
        assert model_id == "openai/gpt-4o"
        return {
            "context_length": 200000,
            "max_output_tokens": 8192,
            "supports_vision": True,
        }

    model_config, safe_window = await build_model_config_for_model(
        "openrouter/openai/gpt-4o",
        model_configs={},
        fetch_specs=_fetch_specs,
    )

    assert model_config.model == "openai/gpt-4o"
    assert model_config.provider == "openrouter"
    assert model_config.client_preference == "openrouter"
    assert model_config.max_output_tokens == 8192
    assert model_config.max_context_window_tokens == 200000
    assert model_config.max_history_tokens == 170000
    assert model_config.vision_enabled is True
    assert safe_window == 170000


@pytest.mark.asyncio
async def test_build_model_config_for_model_does_not_synthesize_output_cap() -> None:
    async def _fetch_specs(model_id: str) -> dict[str, Any]:
        assert model_id == "z-ai/glm-5.1"
        return {
            "context_length": 204800,
            "max_output_tokens": None,
            "supports_vision": False,
        }

    model_config, safe_window = await build_model_config_for_model(
        "openrouter/z-ai/glm-5.1",
        model_configs={},
        fetch_specs=_fetch_specs,
    )

    assert model_config.model == "z-ai/glm-5.1"
    assert model_config.max_output_tokens is None
    assert model_config.max_context_window_tokens == 204800
    assert model_config.max_history_tokens == 174080
    assert safe_window == 174080


@pytest.mark.asyncio
async def test_build_model_config_for_model_clamps_config_output_cap() -> None:
    async def _fetch_specs(model_id: str) -> dict[str, Any]:
        assert model_id == "z-ai/glm-5.1"
        return {
            "context_length": 204800,
            "max_output_tokens": None,
            "supports_vision": False,
        }

    model_config, safe_window = await build_model_config_for_model(
        "openrouter/z-ai/glm-5.1",
        model_configs={
            "openrouter/z-ai/glm-5.1": {
                "provider": "openrouter",
                "client_preference": "openrouter",
                "max_output_tokens": 202752,
            }
        },
        fetch_specs=_fetch_specs,
    )

    assert model_config.max_output_tokens == 174080
    assert safe_window == 174080


@pytest.mark.asyncio
async def test_build_model_config_for_model_does_not_mutate_current_config() -> None:
    current = ModelConfig(
        model="anthropic/claude-3-5-sonnet",
        provider="anthropic",
        client_preference="native",
        api_base="https://api.anthropic.com",
        service_tier="priority",
        max_output_tokens=4096,
    )
    before = current.get_config()

    async def _raise_if_called(_model_id: str) -> dict[str, Any]:
        raise AssertionError(
            "native configured models should not fetch OpenRouter specs"
        )

    await build_model_config_for_model(
        "gpt-4",
        model_configs={
            "gpt-4": {
                "model": "openai/gpt-4",
                "provider": "openai",
                "client_preference": "native",
            }
        },
        current_model_config=current,
        fetch_specs=_raise_if_called,
    )

    assert current.get_config() == before
