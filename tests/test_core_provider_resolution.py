"""Tests for provider/client resolution during model switching."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from penguin.core import PenguinCore
from penguin.llm.model_config import ModelConfig, safe_context_window


def _attach_core_helpers(core_like: SimpleNamespace) -> None:
    core_like._canonicalize_runtime_model_id = (
        lambda model_id,
        provider,
        client_preference: PenguinCore._canonicalize_runtime_model_id(
            core_like,
            model_id,
            provider,
            client_preference,
        )
    )
    core_like._build_model_config_for_model = (
        lambda model_id: PenguinCore._build_model_config_for_model(
            core_like,
            model_id,
        )
    )


def _model_facade_globals() -> dict[str, object]:
    return PenguinCore._build_model_config_for_model.__globals__


def test_resolve_model_provider_prefers_config_entry() -> None:
    core_like = SimpleNamespace(
        config=SimpleNamespace(
            model_configs={
                "openai/gpt-5": {
                    "provider": "openai",
                    "client_preference": "native",
                }
            }
        ),
        model_config=SimpleNamespace(client_preference="openrouter"),
    )

    provider, client_pref = PenguinCore._resolve_model_provider(
        core_like,
        "openai/gpt-5",
    )

    assert provider == "openai"
    assert client_pref == "native"


def test_resolve_model_provider_uses_native_for_openai_and_anthropic() -> None:
    core_like = SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        model_config=SimpleNamespace(client_preference="openrouter"),
    )

    openai_provider, openai_pref = PenguinCore._resolve_model_provider(
        core_like,
        "openai/gpt-5",
    )
    anthropic_provider, anthropic_pref = PenguinCore._resolve_model_provider(
        core_like,
        "anthropic/claude-4-5-sonnet",
    )

    assert (openai_provider, openai_pref) == ("openai", "native")
    assert (anthropic_provider, anthropic_pref) == ("anthropic", "native")


def test_resolve_model_provider_keeps_openrouter_gateway() -> None:
    core_like = SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        model_config=SimpleNamespace(client_preference="native"),
    )

    provider, client_pref = PenguinCore._resolve_model_provider(
        core_like,
        "openrouter/openai/gpt-5-codex",
    )

    assert provider == "openrouter"
    assert client_pref == "openrouter"


@pytest.mark.asyncio
async def test_request_model_config_inherits_top_level_service_tier() -> None:
    core_like = SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        model_config=SimpleNamespace(
            client_preference="native",
            service_tier="priority",
        ),
    )
    _attach_core_helpers(core_like)

    def _resolve(model_id: str) -> tuple[str, str]:
        del model_id
        return "openai", "native"

    core_like._resolve_model_provider = _resolve

    model_config, _ = await PenguinCore._build_model_config_for_model(
        core_like,
        "openai/gpt-5.5",
    )

    assert model_config.model == "gpt-5.5"
    assert model_config.service_tier == "priority"


@pytest.mark.asyncio
async def test_load_model_resolves_provider_before_fetch() -> None:
    state = {"resolved": False}
    applied: dict[str, str] = {}

    core_like = SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        model_config=SimpleNamespace(client_preference="openrouter"),
        _last_model_load_error=None,
    )
    _attach_core_helpers(core_like)

    def _resolve(model_id: str) -> tuple[str, str]:
        del model_id
        state["resolved"] = True
        return "openrouter", "openrouter"

    def _apply(config: ModelConfig, context_window_tokens: int | None = None) -> None:
        del context_window_tokens
        applied["model"] = str(config.model)

    async def _fetch(model_id: str) -> dict[str, int]:
        assert state["resolved"] is True
        assert model_id == "openai/gpt-5"
        return {"context_length": 128000, "max_output_tokens": 8192}

    core_like._resolve_model_provider = _resolve
    core_like._apply_new_model_config = _apply

    with patch.dict(
        _model_facade_globals(),
        {"fetch_model_specs": AsyncMock(side_effect=_fetch)},
    ):
        ok = await PenguinCore.load_model(core_like, "openrouter/openai/gpt-5")

    assert ok is True
    assert applied["model"] == "openai/gpt-5"


@pytest.mark.asyncio
async def test_load_model_allows_native_anthropic_without_openrouter_specs() -> None:
    applied: dict[str, str] = {}
    core_like = SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        model_config=SimpleNamespace(client_preference="native"),
        _last_model_load_error=None,
    )
    _attach_core_helpers(core_like)

    def _resolve(model_id: str) -> tuple[str, str]:
        del model_id
        return "anthropic", "native"

    def _apply(config: ModelConfig, context_window_tokens: int | None = None) -> None:
        del context_window_tokens
        applied.update(
            {
                "model": str(config.model),
                "provider": str(config.provider),
                "client": str(config.client_preference),
            }
        )

    core_like._resolve_model_provider = _resolve
    core_like._apply_new_model_config = _apply

    fetch = AsyncMock(return_value={})
    with patch.dict(_model_facade_globals(), {"fetch_model_specs": fetch}):
        ok = await PenguinCore.load_model(
            core_like,
            "anthropic/claude-3-7-sonnet-latest",
        )

    assert ok is True
    fetch.assert_not_called()
    assert applied["provider"] == "anthropic"
    assert applied["client"] == "native"
    assert applied["model"] == "claude-3-7-sonnet-latest"


@pytest.mark.asyncio
async def test_load_model_surfaces_reason_when_openrouter_specs_missing() -> None:
    core_like = SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        model_config=SimpleNamespace(client_preference="openrouter"),
        _last_model_load_error=None,
    )
    _attach_core_helpers(core_like)

    def _resolve(model_id: str) -> tuple[str, str]:
        del model_id
        return "openrouter", "openrouter"

    def _apply(config: ModelConfig, context_window_tokens: int | None = None) -> None:
        del config, context_window_tokens

    core_like._resolve_model_provider = _resolve
    core_like._apply_new_model_config = _apply

    with patch.dict(
        _model_facade_globals(),
        {"fetch_model_specs": AsyncMock(return_value={})},
    ):
        ok = await PenguinCore.load_model(core_like, "openrouter/openai/gpt-5")

    assert ok is False
    assert isinstance(core_like._last_model_load_error, str)
    assert "Could not fetch specifications" in core_like._last_model_load_error


@pytest.mark.asyncio
async def test_load_model_does_not_use_context_window_as_output_cap() -> None:
    applied: dict[str, object] = {}
    core_like = SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        model_config=SimpleNamespace(client_preference="openrouter"),
        _last_model_load_error=None,
    )
    _attach_core_helpers(core_like)

    def _resolve(model_id: str) -> tuple[str, str]:
        del model_id
        return "openrouter", "openrouter"

    def _apply(config: ModelConfig, context_window_tokens: int | None = None) -> None:
        applied["model"] = str(config.model)
        applied["max_output_tokens"] = getattr(config, "max_output_tokens", None)
        applied["context_window_tokens"] = context_window_tokens

    core_like._resolve_model_provider = _resolve
    core_like._apply_new_model_config = _apply

    with patch.dict(
        _model_facade_globals(),
        {
            "fetch_model_specs": AsyncMock(
                return_value={
                    "context_length": 204800,
                    "max_output_tokens": None,
                }
            )
        },
    ):
        ok = await PenguinCore.load_model(core_like, "openrouter/z-ai/glm-5.1")

    assert ok is True
    assert applied["model"] == "z-ai/glm-5.1"
    assert applied["max_output_tokens"] is None
    assert applied["context_window_tokens"] == safe_context_window(204800)


@pytest.mark.asyncio
async def test_load_model_clamps_explicit_max_output_tokens_to_safe_window() -> None:
    applied: dict[str, object] = {}
    core_like = SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        model_config=SimpleNamespace(current_model="old/model", service_tier=None),
        api_client=None,
        _last_model_load_error=None,
    )

    _attach_core_helpers(core_like)

    def _resolve(model_id: str) -> tuple[str, str]:
        del model_id
        return "openrouter", "openrouter"

    def _apply(config: ModelConfig, context_window_tokens: int | None = None) -> None:
        applied["model"] = str(config.model)
        applied["max_output_tokens"] = getattr(config, "max_output_tokens", None)
        applied["context_window_tokens"] = context_window_tokens

    core_like._resolve_model_provider = _resolve
    core_like._apply_new_model_config = _apply

    with patch.dict(
        _model_facade_globals(),
        {
            "fetch_model_specs": AsyncMock(
                return_value={
                    "context_length": 204800,
                    "max_output_tokens": 202752,
                }
            )
        },
    ):
        ok = await PenguinCore.load_model(core_like, "openrouter/z-ai/glm-5.1")

    assert ok is True
    assert applied["model"] == "z-ai/glm-5.1"
    assert applied["max_output_tokens"] == safe_context_window(204800)
    assert applied["context_window_tokens"] == safe_context_window(204800)


@pytest.mark.asyncio
async def test_load_model_clamps_for_model_max_output_tokens_to_safe_window() -> None:
    applied: dict[str, object] = {}
    core_like = SimpleNamespace(
        config=SimpleNamespace(
            model_configs={
                "openrouter/z-ai/glm-5.1": {
                    "max_output_tokens": 202752,
                }
            }
        ),
        model_config=SimpleNamespace(client_preference="openrouter"),
        _last_model_load_error=None,
    )
    _attach_core_helpers(core_like)

    def _resolve(model_id: str) -> tuple[str, str]:
        del model_id
        return "openrouter", "openrouter"

    def _apply(config: ModelConfig, context_window_tokens: int | None = None) -> None:
        applied["model"] = str(config.model)
        applied["max_output_tokens"] = config.max_output_tokens
        applied["context_window_tokens"] = context_window_tokens

    core_like._resolve_model_provider = _resolve
    core_like._apply_new_model_config = _apply

    with patch.dict(
        _model_facade_globals(),
        {
            "fetch_model_specs": AsyncMock(
                return_value={
                    "context_length": 204800,
                    "max_output_tokens": None,
                }
            )
        },
    ):
        ok = await PenguinCore.load_model(core_like, "openrouter/z-ai/glm-5.1")

    assert ok is True
    assert applied["model"] == "z-ai/glm-5.1"
    assert applied["max_output_tokens"] == safe_context_window(204800)
    assert applied["context_window_tokens"] == safe_context_window(204800)
