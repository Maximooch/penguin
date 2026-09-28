from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.llm.model_config import ModelConfig
from penguin.llm.providers.link import LinkProvider
from penguin.web.services.link_inference import (
    LinkExecutionRequest,
    resolve_link_inference_runtime,
)


def _execution(
    max_output_tokens: int | None = 512,
    requested_model_id: str = "openai/gpt-5.4-nano",
    *,
    include_persisted_identity: bool = True,
) -> LinkExecutionRequest:
    payload: dict[str, Any] = {
        "workspace_id": "workspace-1",
        "user_id": "user-1",
        "workos_organization_id": "org_01M06XBYP88CD1MHHSRGWTC2BA",
        "run_id": "run-1",
        "requested_model_id": requested_model_id,
        "execution_source": "link_gateway",
        "provider_state_owner": "link_managed",
        "settlement_mode": "debit_link_credits",
    }
    if include_persisted_identity:
        payload["session_id"] = "session-1"
        payload["agent_id"] = "agent-1"
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    return LinkExecutionRequest(**payload)


def test_builds_request_scoped_link_provider_without_mutating_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINK_INFERENCE_SERVICE_TOKEN", "service-secret")
    original = ModelConfig(
        model="anthropic/claude-sonnet-4",
        provider="openrouter",
        client_preference="openrouter",
        max_output_tokens=512,
    )
    core = SimpleNamespace(model_config=original)

    model_config, api_client = resolve_link_inference_runtime(
        core,
        _execution(),
        "openai/gpt-5.4-nano",
    )

    assert model_config.client_preference == "link"
    assert model_config.provider == "link"
    assert model_config.api_key == ""
    assert isinstance(api_client.client_handler, LinkProvider)
    assert api_client.client_handler.context.workspace_id == "workspace-1"
    assert (
        api_client.client_handler.context.workos_organization_id
        == "org_01M06XBYP88CD1MHHSRGWTC2BA"
    )
    assert core.model_config is original
    assert original.client_preference == "openrouter"


def test_rejects_model_that_differs_from_link_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINK_INFERENCE_SERVICE_TOKEN", "service-secret")
    core = SimpleNamespace(
        model_config=ModelConfig(
            model="openai/gpt-5.4-nano",
            provider="openrouter",
            max_output_tokens=128,
        )
    )

    with pytest.raises(ValueError, match="does not match"):
        resolve_link_inference_runtime(core, _execution(), "openai/gpt-5.4")


def test_uses_link_owned_output_bound_instead_of_the_base_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINK_INFERENCE_SERVICE_TOKEN", "service-secret")
    original = ModelConfig(
        model="anthropic/claude-sonnet-4",
        provider="openrouter",
        client_preference="openrouter",
        max_output_tokens=None,
    )
    core = SimpleNamespace(model_config=original)
    execution = _execution(max_output_tokens=16_384)

    model_config, _api_client = resolve_link_inference_runtime(
        core,
        execution,
        "openai/gpt-5.4-nano",
    )

    assert model_config.max_output_tokens == 16_384
    assert original.max_output_tokens is None


def test_accepts_legacy_execution_without_an_output_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINK_INFERENCE_SERVICE_TOKEN", "service-secret")
    original = ModelConfig(
        model="anthropic/claude-sonnet-4",
        provider="openrouter",
        client_preference="openrouter",
        max_output_tokens=2048,
    )
    core = SimpleNamespace(model_config=original)

    model_config, _api_client = resolve_link_inference_runtime(
        core,
        _execution(max_output_tokens=None),
        "openai/gpt-5.4-nano",
    )

    assert model_config.max_output_tokens == 2048


def test_accepts_transient_execution_without_persisted_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINK_INFERENCE_SERVICE_TOKEN", "service-secret")
    core = SimpleNamespace(
        model_config=ModelConfig(
            model="openai/gpt-5.4-nano",
            provider="openrouter",
            max_output_tokens=128,
        )
    )

    _model_config, api_client = resolve_link_inference_runtime(
        core,
        _execution(include_persisted_identity=False),
        "openai/gpt-5.4-nano",
    )

    context = api_client.client_handler.context
    assert context.session_id is None
    assert context.agent_id is None
    headers = context.headers("request-1")
    assert "X-Link-Session-Id" not in headers
    assert "X-Link-Agent-Id" not in headers


def test_rejects_one_sided_persisted_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINK_INFERENCE_SERVICE_TOKEN", "service-secret")
    core = SimpleNamespace(
        model_config=ModelConfig(
            model="openai/gpt-5.4-nano",
            provider="openrouter",
            max_output_tokens=128,
        )
    )
    execution = _execution(include_persisted_identity=False)
    execution.session_id = "session-1"

    with pytest.raises(ValueError, match="supplied together"):
        resolve_link_inference_runtime(
            core,
            execution,
            "openai/gpt-5.4-nano",
        )


def test_does_not_inherit_model_specific_metadata_from_the_base_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINK_INFERENCE_SERVICE_TOKEN", "service-secret")
    original = ModelConfig(
        model="openai/gpt-5.4",
        provider="openrouter",
        client_preference="openrouter",
        max_output_tokens=4096,
        max_context_window_tokens=128_000,
        max_history_tokens=64_000,
        reasoning_enabled=True,
        reasoning_effort="ultra",
        supports_reasoning=True,
        supported_reasoning_levels=["low", "medium", "high", "ultra"],
    )
    core = SimpleNamespace(model_config=original)

    model_config, _api_client = resolve_link_inference_runtime(
        core,
        _execution(
            max_output_tokens=8192,
            requested_model_id="moonshotai/kimi-k3",
        ),
        "moonshotai/kimi-k3",
    )

    assert model_config.max_context_window_tokens is None
    assert model_config.max_history_tokens != original.max_history_tokens
    assert model_config.reasoning_effort is None
    assert model_config.supported_reasoning_levels is None
    assert model_config.supports_reasoning is False
    assert original.max_context_window_tokens == 128_000
    assert original.reasoning_effort == "ultra"
