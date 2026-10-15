"""Offline contracts for OpenAI service-tier configuration and web overrides."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from penguin.llm.model_config import ModelConfig, normalize_openai_service_tier
from penguin.web.routes import MessageRequest, _apply_request_service_tier_override


@pytest.mark.parametrize("tier", ["auto", "default", "flex", "priority", "ultrafast"])
def test_service_tier_configuration_and_web_override(tier: str) -> None:
    config = ModelConfig(model="gpt-6-astra", provider="openai", service_tier=tier)
    assert config.get_config()["service_tier"] == tier
    request = MessageRequest(text="hello", service_tier=f" {tier.upper()} ")
    target = SimpleNamespace(service_tier="default", reasoning_effort="high")
    assert _apply_request_service_tier_override(request.service_tier, model_config=target) == tier
    assert target.service_tier == tier
    assert target.reasoning_effort == "high"
    assert _apply_request_service_tier_override(tier, model_config=None) == tier


def test_ultrafast_environment_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENGUIN_OPENAI_SERVICE_TIER", "ultrafast")
    assert ModelConfig.from_env().service_tier == "ultrafast"


@pytest.mark.parametrize("tier", ["turbo", "", "ultrafast extra"])
def test_invalid_tier_does_not_mutate_request_config(tier: str) -> None:
    target = SimpleNamespace(service_tier="priority")
    assert normalize_openai_service_tier(tier) is None
    with pytest.raises(HTTPException) as exc:
        _apply_request_service_tier_override(tier, model_config=target)
    assert exc.value.status_code == 400
    assert "ultrafast" in exc.value.detail
    assert target.service_tier == "priority"


def test_unset_override_preserves_config() -> None:
    target = SimpleNamespace(service_tier="ultrafast")
    assert _apply_request_service_tier_override(None, model_config=target) is None
    assert target.service_tier == "ultrafast"
