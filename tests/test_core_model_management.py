"""Characterization tests for PenguinCore model management facade methods."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from penguin.core import PenguinCore
from penguin.llm.model_config import ModelConfig

MODEL_CONFIGS: dict[str, dict[str, Any]] = {
    "claude-3-sonnet": {
        "model": "anthropic/claude-3-sonnet-20240229",
        "provider": "anthropic",
        "client_preference": "native",
        "vision_enabled": True,
        "max_output_tokens": 4000,
        "max_context_window_tokens": 200000,
        "temperature": 0.7,
    },
    "gpt-4": {
        "model": "openai/gpt-4",
        "provider": "openai",
        "client_preference": "native",
        "vision_enabled": False,
        "max_output_tokens": 8000,
        "max_context_window_tokens": 128000,
        "temperature": 0.3,
    },
    "gpt-4-vision": {
        "model": "openai/gpt-4-vision-preview",
        "provider": "openai",
        "client_preference": "native",
        "vision_enabled": True,
        "max_output_tokens": 4000,
        "max_context_window_tokens": 128000,
        "temperature": 0.5,
    },
}


@pytest.fixture
def model_config() -> ModelConfig:
    """Return the initially loaded model config used by facade tests."""

    return ModelConfig(
        model="anthropic/claude-3-sonnet-20240229",
        provider="anthropic",
        client_preference="native",
        max_output_tokens=4000,
        max_context_window_tokens=200000,
        temperature=0.7,
        streaming_enabled=True,
        vision_enabled=True,
    )


@pytest.fixture
def core(model_config: ModelConfig) -> PenguinCore:
    """Create a minimal core instance without running full startup."""

    instance = PenguinCore.__new__(PenguinCore)
    instance.model_config = model_config
    instance.config = SimpleNamespace(model_configs=dict(MODEL_CONFIGS))
    instance.initialized = True
    instance._last_model_load_error = None
    instance._apply_new_model_config = MagicMock()
    instance._build_model_config_for_model = (
        PenguinCore._build_model_config_for_model.__get__(instance)
    )
    instance.load_model = PenguinCore.load_model.__get__(instance)
    instance.list_available_models = PenguinCore.list_available_models.__get__(instance)
    instance.get_current_model = PenguinCore.get_current_model.__get__(instance)
    return instance


def test_list_available_models_uses_current_output_token_keys(
    core: PenguinCore,
) -> None:
    result = core.list_available_models()

    assert [model["id"] for model in result] == [
        "claude-3-sonnet",
        "gpt-4",
        "gpt-4-vision",
    ]
    claude_model = result[0]
    assert claude_model == {
        "id": "claude-3-sonnet",
        "name": "anthropic/claude-3-sonnet-20240229",
        "provider": "anthropic",
        "client_preference": "native",
        "vision_enabled": True,
        "max_output_tokens": 4000,
        "temperature": 0.7,
        "current": True,
    }


def test_list_available_models_accepts_legacy_max_tokens_key(
    core: PenguinCore,
) -> None:
    core.config.model_configs["legacy"] = {
        "model": "openai/gpt-4o-mini",
        "provider": "openai",
        "client_preference": "native",
        "max_tokens": 1234,
    }

    result = core.list_available_models()

    legacy = next(model for model in result if model["id"] == "legacy")
    assert legacy["max_output_tokens"] == 1234


def test_list_available_models_filters_invalid_entries(core: PenguinCore) -> None:
    core.config.model_configs["invalid"] = "not a mapping"
    core.config.model_configs["also_invalid"] = None

    result = core.list_available_models()

    assert {model["id"] for model in result} == {
        "claude-3-sonnet",
        "gpt-4",
        "gpt-4-vision",
    }


def test_get_current_model_uses_explicit_token_names(core: PenguinCore) -> None:
    result = core.get_current_model()

    assert result == {
        "model": "anthropic/claude-3-sonnet-20240229",
        "provider": "anthropic",
        "client_preference": "native",
        "max_output_tokens": 4000,
        "temperature": 0.7,
        "streaming_enabled": True,
        "vision_enabled": True,
        "api_base": None,
    }


def test_get_current_model_no_config(core: PenguinCore) -> None:
    core.model_config = None

    assert core.get_current_model() is None


@pytest.mark.asyncio
async def test_resolve_request_runtime_uses_runtime_helper(
    core: PenguinCore,
) -> None:
    core.system_prompt = "system"
    core.resolve_request_runtime = PenguinCore.resolve_request_runtime.__get__(core)
    requested_config = ModelConfig(model="gpt-5", provider="openai")
    core._build_model_config_for_model = AsyncMock(
        return_value=(requested_config, 1000)
    )

    class FakeAPIClient:
        def __init__(self, *, model_config: ModelConfig) -> None:
            self.model_config = model_config
            self.system_prompt = None

        def set_system_prompt(self, prompt: str) -> None:
            self.system_prompt = prompt

    with patch("penguin.core.APIClient", FakeAPIClient):
        model_config, api_client = await core.resolve_request_runtime("gpt-5")

    assert model_config is requested_config
    assert api_client.model_config is requested_config
    assert api_client.system_prompt == "system"
    core._build_model_config_for_model.assert_called_once_with("gpt-5")


@pytest.mark.asyncio
async def test_load_model_existing_config_applies_derived_config(
    core: PenguinCore,
) -> None:
    result = await core.load_model("gpt-4")

    assert result is True
    core._apply_new_model_config.assert_called_once()
    (new_config,) = core._apply_new_model_config.call_args.args
    assert new_config.model == "gpt-4"
    assert new_config.provider == "openai"
    assert new_config.client_preference == "native"
    assert new_config.max_output_tokens == 8000
    assert core._apply_new_model_config.call_args.kwargs == {
        "context_window_tokens": 108800,
    }


@pytest.mark.asyncio
async def test_load_model_fully_qualified_native_model_applies_provider_local_id(
    core: PenguinCore,
) -> None:
    result = await core.load_model("openai/gpt-3.5-turbo")

    assert result is True
    (new_config,) = core._apply_new_model_config.call_args.args
    assert new_config.model == "gpt-3.5-turbo"
    assert new_config.provider == "openai"
    assert new_config.client_preference == "native"


@pytest.mark.asyncio
async def test_load_model_invalid_unqualified_name_fails(core: PenguinCore) -> None:
    result = await core.load_model("invalid_model_name")

    assert result is False
    assert "Could not resolve provider" in core._last_model_load_error
    core._apply_new_model_config.assert_not_called()


@pytest.mark.asyncio
async def test_load_model_openrouter_spec_failure_fails(
    core: PenguinCore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _empty_specs(_model_id: str) -> dict[str, Any]:
        return {}

    monkeypatch.setattr("penguin.core.fetch_model_specs", _empty_specs)

    result = await core.load_model("openrouter/openai/gpt-4o")

    assert result is False
    assert "Could not fetch specifications" in core._last_model_load_error
    core._apply_new_model_config.assert_not_called()


def test_model_capabilities_comparison_uses_max_output_tokens(
    core: PenguinCore,
) -> None:
    models = core.list_available_models()

    vision_enabled = [model for model in models if model["vision_enabled"]]
    high_output_limit = [
        model for model in models if model.get("max_output_tokens", 0) >= 8000
    ]
    low_temperature = [
        model for model in models if model.get("temperature", 1.0) <= 0.3
    ]

    assert [model["id"] for model in vision_enabled] == [
        "claude-3-sonnet",
        "gpt-4-vision",
    ]
    assert [model["id"] for model in high_output_limit] == ["gpt-4"]
    assert [model["id"] for model in low_temperature] == ["gpt-4"]


def test_apply_new_model_config_propagates_to_runtime_components(
    model_config: ModelConfig,
) -> None:
    core = PenguinCore.__new__(PenguinCore)
    core.model_config = model_config
    core.system_prompt = "system prompt"
    context_window = SimpleNamespace(
        max_context_window_tokens=200000,
        _initialize_token_budgets=MagicMock(),
    )
    conversation_manager = SimpleNamespace(context_window=context_window)
    engine = SimpleNamespace()
    core.conversation_manager = conversation_manager
    core.engine = engine
    core.refresh_api_client = PenguinCore.refresh_api_client.__get__(core)
    core._apply_new_model_config = PenguinCore._apply_new_model_config.__get__(core)

    class FakeAPIClient:
        def __init__(self, model_config: ModelConfig) -> None:
            self.model_config = model_config
            self.system_prompt = None

        def set_system_prompt(self, prompt: str) -> None:
            self.system_prompt = prompt

    new_config = ModelConfig(
        model="gpt-4",
        provider="openai",
        client_preference="native",
        max_output_tokens=8000,
        max_context_window_tokens=128000,
        streaming_enabled=True,
    )

    with patch("penguin.core.APIClient", FakeAPIClient):
        core._apply_new_model_config(new_config, context_window_tokens=108800)

    assert core.model_config is new_config
    assert core.api_client.model_config is new_config
    assert core.api_client.system_prompt == "system prompt"
    assert conversation_manager.model_config is new_config
    assert conversation_manager.api_client is core.api_client
    assert context_window.model_config is new_config
    assert context_window.api_client is core.api_client
    assert context_window.max_context_window_tokens == 108800
    context_window._initialize_token_budgets.assert_called_once()
    assert engine.model_config is new_config
    assert engine.api_client is core.api_client
