"""Tests for core model-runtime resolution helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from penguin.core_runtime.model_runtime import (
    apply_new_model_config,
    build_model_config_for_model,
    canonicalize_runtime_model_id,
    configure_llm_client,
    current_model_payload,
    ensure_litellm_configured,
    ensure_litellm_runtime_state,
    list_available_models,
    load_model_for_core,
    refresh_api_client,
    resolve_model_provider,
    resolve_request_runtime,
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


def test_refresh_api_client_propagates_to_runtime_components() -> None:
    model_config = ModelConfig(model="gpt-4o", provider="openai", api_key="test-key")
    context_window = SimpleNamespace()
    conversation_manager = SimpleNamespace(context_window=context_window)
    engine = SimpleNamespace()
    owner = SimpleNamespace(
        model_config=model_config,
        system_prompt="system",
        conversation_manager=conversation_manager,
        engine=engine,
    )

    class FakeAPIClient:
        def __init__(self, *, model_config: ModelConfig) -> None:
            self.model_config = model_config
            self.system_prompt = None

        def set_system_prompt(self, prompt: str) -> None:
            self.system_prompt = prompt

    refresh_api_client(owner, api_client_factory=FakeAPIClient)

    assert owner.api_client.model_config is model_config
    assert owner.api_client.system_prompt == "system"
    assert conversation_manager.api_client is owner.api_client
    assert context_window.api_client is owner.api_client
    assert engine.api_client is owner.api_client


def test_ensure_litellm_configured_disables_debugging_once() -> None:
    calls: list[str] = []

    class _Logging:
        def _disable_debugging(self) -> None:
            calls.append("disable_debugging")

    class _LiteLLM:
        _logging = _Logging()
        set_verbose = True
        drop_params = True

    owner = SimpleNamespace(_litellm_configured=False)

    ensure_litellm_configured(
        owner,
        litellm_loader=lambda reason: calls.append(reason) or _LiteLLM,
    )
    ensure_litellm_configured(
        owner,
        litellm_loader=lambda reason: calls.append(f"again:{reason}") or _LiteLLM,
    )

    assert owner._litellm_configured is True
    assert calls == ["LiteLLM optional runtime", "disable_debugging"]
    assert _LiteLLM.set_verbose is False
    assert _LiteLLM.drop_params is False


def test_ensure_litellm_configured_marks_done_after_loader_failure() -> None:
    debug_calls: list[tuple[str, tuple[Any, ...]]] = []
    owner = SimpleNamespace(_litellm_configured=False)

    class _Logger:
        def debug(self, message: str, *args: Any) -> None:
            debug_calls.append((message, args))

    def failing_loader(_reason: str) -> Any:
        raise RuntimeError("missing optional dependency")

    ensure_litellm_configured(
        owner,
        litellm_loader=failing_loader,
        log=_Logger(),
    )

    assert owner._litellm_configured is True
    assert len(debug_calls) == 1
    assert debug_calls[0][0] == (
        "LiteLLM optional runtime unavailable or not configured: %s"
    )
    assert str(debug_calls[0][1][0]) == "missing optional dependency"


def test_ensure_litellm_runtime_state_preserves_core_side_effects() -> None:
    calls: list[Any] = []

    class _Logging:
        def _disable_debugging(self) -> None:
            calls.append("disable_debugging")

    class _LiteLLM:
        _logging = _Logging()
        set_verbose = True
        drop_params = True

    tool_manager = SimpleNamespace(set_core=lambda owner: calls.append(owner))
    owner = SimpleNamespace(
        _litellm_configured=False,
        current_runmode_status_summary="busy",
        tool_manager=tool_manager,
    )

    ensure_litellm_runtime_state(
        owner,
        litellm_loader=lambda _reason: _LiteLLM,
    )

    assert owner._litellm_configured is True
    assert owner.current_runmode_status_summary == "RunMode idle."
    assert calls == ["disable_debugging", owner]


def test_ensure_litellm_runtime_state_tolerates_missing_tool_core_hook() -> None:
    owner = SimpleNamespace(
        _litellm_configured=True,
        current_runmode_status_summary="busy",
        tool_manager=SimpleNamespace(),
    )

    ensure_litellm_runtime_state(owner)

    assert owner.current_runmode_status_summary == "RunMode idle."


def test_configure_llm_client_creates_link_configured_client() -> None:
    model_config = ModelConfig(model="gpt-4o", provider="openai")
    created_configs: list[Any] = []
    created_links: list[dict[str, Any]] = []

    class FakeLinkConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.values = kwargs
            created_links.append(kwargs)

    class FakeLLMClientConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.values = kwargs
            created_configs.append(kwargs)

    class FakeLLMClient:
        def __init__(self, model_config: ModelConfig, config: Any) -> None:
            self.model_config = model_config
            self.config = config
            self.update_calls: list[dict[str, Any]] = []

        def get_status(self) -> dict[str, Any]:
            return {"configured": True, "model": self.model_config.model}

    owner = SimpleNamespace(model_config=model_config, _llm_client=None)

    status = configure_llm_client(
        owner,
        base_url="http://localhost:3001/api/v1",
        link_user_id="user_1",
        link_session_id="session_1",
        link_agent_id="agent_1",
        link_workspace_id="workspace_1",
        link_api_key="key_1",
        llm_client_factory=FakeLLMClient,
        llm_client_config_factory=FakeLLMClientConfig,
        link_config_factory=FakeLinkConfig,
    )

    assert status == {"configured": True, "model": "gpt-4o"}
    assert owner._llm_client.model_config is model_config
    assert created_links == [
        {
            "user_id": "user_1",
            "session_id": "session_1",
            "agent_id": "agent_1",
            "workspace_id": "workspace_1",
            "api_key": "key_1",
        }
    ]
    assert created_configs == [
        {
            "base_url": "http://localhost:3001/api/v1",
            "link": owner._llm_client.config.values["link"],
        }
    ]


def test_configure_llm_client_updates_existing_client() -> None:
    class ExistingClient:
        def __init__(self) -> None:
            self.update_calls: list[dict[str, Any]] = []

        def update_config(self, **kwargs: Any) -> None:
            self.update_calls.append(kwargs)

        def get_status(self) -> dict[str, Any]:
            return {"updated": bool(self.update_calls)}

    existing = ExistingClient()
    owner = SimpleNamespace(
        model_config=ModelConfig(model="gpt-4o", provider="openai"),
        _llm_client=existing,
    )

    status = configure_llm_client(
        owner,
        base_url="http://localhost:4000",
        link_user_id="user_2",
        link_session_id="session_2",
        link_agent_id="agent_2",
        link_workspace_id="workspace_2",
        link_api_key="key_2",
    )

    assert owner._llm_client is existing
    assert status == {"updated": True}
    assert existing.update_calls == [
        {
            "base_url": "http://localhost:4000",
            "link_user_id": "user_2",
            "link_session_id": "session_2",
            "link_agent_id": "agent_2",
            "link_workspace_id": "workspace_2",
            "link_api_key": "key_2",
        }
    ]


def test_apply_new_model_config_propagates_budget_and_model_config() -> None:
    old_config = ModelConfig(model="old", provider="openai")
    new_config = ModelConfig(model="new", provider="openai")
    context_window = SimpleNamespace(
        max_context_window_tokens=100,
        _initialize_token_budgets=MagicMock(),
    )
    conversation_manager = SimpleNamespace(context_window=context_window)
    engine = SimpleNamespace()
    owner = SimpleNamespace(
        model_config=old_config,
        conversation_manager=conversation_manager,
        engine=engine,
    )
    refresh_calls: list[str] = []

    apply_new_model_config(
        owner,
        new_config,
        context_window_tokens=85,
        refresh_active_client=lambda: refresh_calls.append(owner.model_config.model),
    )

    assert refresh_calls == ["new"]
    assert owner.model_config is new_config
    assert conversation_manager.model_config is new_config
    assert context_window.model_config is new_config
    assert context_window.max_context_window_tokens == 85
    context_window._initialize_token_budgets.assert_called_once()
    assert engine.model_config is new_config


@pytest.mark.asyncio
async def test_resolve_request_runtime_requires_connected_model() -> None:
    owner = SimpleNamespace(
        model_config=ModelConfig(model="", provider=""),
        system_prompt="system",
        get_current_model=lambda: {"model": "", "provider": ""},
    )

    with pytest.raises(ValueError, match="Connect an AI model"):
        await resolve_request_runtime(
            owner,
            None,
            api_client_factory=lambda **_kwargs: None,
        )


@pytest.mark.asyncio
async def test_resolve_request_runtime_requires_selected_provider_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    owner = SimpleNamespace(
        model_config=ModelConfig(
            model="openai/gpt-5.2",
            provider="openrouter",
        ),
        system_prompt="system",
        get_current_model=lambda: {
            "model": "openai/gpt-5.2",
            "provider": "openrouter",
        },
    )

    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        await resolve_request_runtime(
            owner,
            None,
            api_client_factory=lambda **_kwargs: None,
        )


@pytest.mark.asyncio
async def test_resolve_request_runtime_reuses_current_model_without_mutation() -> None:
    model_config = ModelConfig(model="gpt-4o", provider="openai", api_key="test-key")
    model_config.temperature = 0.1
    built_models: list[str] = []

    class FakeAPIClient:
        def __init__(self, *, model_config: ModelConfig) -> None:
            self.model_config = model_config
            self.prompts: list[str] = []

        def set_system_prompt(self, prompt: str) -> None:
            self.prompts.append(prompt)

    async def _build_model_config_for_model(model_id: str) -> tuple[ModelConfig, int]:
        built_models.append(model_id)
        return ModelConfig(model=model_id, provider="openai"), 1000

    owner = SimpleNamespace(
        model_config=model_config,
        system_prompt="system",
        get_current_model=lambda: {"model": "gpt-4o", "provider": "openai"},
        _build_model_config_for_model=_build_model_config_for_model,
    )

    resolved, api_client = await resolve_request_runtime(
        owner,
        "openai/gpt-4o",
        api_client_factory=FakeAPIClient,
    )

    assert built_models == []
    assert resolved is not model_config
    assert resolved.model == "gpt-4o"
    assert resolved.temperature == 0.1
    assert api_client.model_config is resolved
    assert api_client.prompts == ["system"]


@pytest.mark.asyncio
async def test_resolve_request_runtime_builds_requested_override() -> None:
    requested = ModelConfig(model="gpt-5", provider="openai", api_key="test-key")
    built_models: list[str] = []

    class FakeAPIClient:
        def __init__(self, *, model_config: ModelConfig) -> None:
            self.model_config = model_config
            self.prompts: list[str] = []

        def set_system_prompt(self, prompt: str) -> None:
            self.prompts.append(prompt)

    async def _build_model_config_for_model(
        model_id: str,
    ) -> tuple[ModelConfig, int]:
        built_models.append(model_id)
        return requested, 1000

    owner = SimpleNamespace(
        model_config=ModelConfig(model="gpt-4o", provider="openai"),
        system_prompt="system",
        get_current_model=lambda: {"model": "gpt-4o", "provider": "openai"},
        _build_model_config_for_model=_build_model_config_for_model,
    )

    resolved, api_client = await resolve_request_runtime(
        owner,
        "gpt-5",
        api_client_factory=FakeAPIClient,
    )

    assert built_models == ["gpt-5"]
    assert resolved is requested
    assert api_client.model_config is requested
    assert api_client.prompts == ["system"]


@pytest.mark.asyncio
async def test_load_model_for_core_applies_config_and_records_failures() -> None:
    new_config = ModelConfig(model="gpt-5", provider="openai")
    applied: list[tuple[ModelConfig, int | None]] = []

    async def _build_success(_model_id: str) -> tuple[ModelConfig, int]:
        return new_config, 2048

    owner = SimpleNamespace(
        _last_model_load_error="previous",
        _build_model_config_for_model=_build_success,
        _apply_new_model_config=lambda config, *, context_window_tokens=None: (
            applied.append((config, context_window_tokens))
        ),
    )

    assert await load_model_for_core(owner, "gpt-5") is True
    assert owner._last_model_load_error is None
    assert applied == [(new_config, 2048)]

    async def _build_failure(_model_id: str) -> tuple[ModelConfig, int]:
        raise RuntimeError("bad model")

    owner._build_model_config_for_model = _build_failure
    assert await load_model_for_core(owner, "bad") is False
    assert owner._last_model_load_error == "bad model"
    assert applied == [(new_config, 2048)]


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


@given(
    context_length=st.integers(min_value=1, max_value=1_000_000),
    max_output_tokens=st.integers(min_value=1, max_value=1_000_000),
)
@settings(max_examples=50, deadline=None)
def test_build_model_config_for_model_never_exposes_output_cap_above_safe_window(
    context_length: int,
    max_output_tokens: int,
) -> None:
    async def _fetch_specs(model_id: str) -> dict[str, Any]:
        assert model_id == "example/model"
        return {
            "context_length": context_length,
            "max_output_tokens": max_output_tokens,
            "supports_vision": False,
        }

    model_config, safe_window = asyncio.run(
        build_model_config_for_model(
            "openrouter/example/model",
            model_configs={},
            fetch_specs=_fetch_specs,
        )
    )

    if safe_window is None:
        assert model_config.max_output_tokens == max_output_tokens
    else:
        assert model_config.max_output_tokens <= safe_window


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
