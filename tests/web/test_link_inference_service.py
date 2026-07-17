from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.llm.model_config import ModelConfig
from penguin.llm.providers.link import LinkProvider
from penguin.web.services.link_inference import (
    LinkExecutionRequest,
    resolve_link_inference_runtime,
)


def _execution() -> LinkExecutionRequest:
    return LinkExecutionRequest(
        workspace_id="workspace-1",
        user_id="user-1",
        session_id="session-1",
        agent_id="agent-1",
        run_id="run-1",
        requested_model_id="openai/gpt-5.4-nano",
        execution_source="link_gateway",
        provider_state_owner="link_managed",
        settlement_mode="debit_link_credits",
    )


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
    assert isinstance(api_client.client_handler, LinkProvider)
    assert api_client.client_handler.context.workspace_id == "workspace-1"
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
