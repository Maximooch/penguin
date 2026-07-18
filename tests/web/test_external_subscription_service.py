from __future__ import annotations

import pytest

from penguin.web.services import external_subscription as service


def _execution(**overrides: object) -> service.ExternalSubscriptionExecutionRequest:
    values: dict[str, object] = {
        "protocol_version": 1,
        "owner_user_id": "user-a",
        "user_id": "user-a",
        "requested_model_id": "gpt-5.4",
        "agent_runtime": "penguin",
        "provider": "openai",
        "inference_transport": "codex_responses_compat",
        "execution_source": "local_penguin",
        "provider_state_owner": "user_owned",
        "credential_custodian": "local_penguin",
        "settlement_mode": "subscription_quota",
        "usage_authority": "local_runtime_observed",
        "integration_support": "ecosystem_compatible",
        "allow_fallback_to_link_gateway": False,
    }
    values.update(overrides)
    return service.ExternalSubscriptionExecutionRequest(**values)


def test_capability_reports_oauth_models_without_credentials(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_provider_credentials",
        lambda: {
            "openai": {
                "type": "oauth",
                "access": "secret-access",
                "refresh": "secret-refresh",
                "accountId": "account-secret",
            }
        },
    )
    monkeypatch.setattr(
        service,
        "codex_oauth_provider_models",
        lambda _record: {
            "openai": {
                "gpt-5.4": {
                    "name": "GPT-5.4",
                    "context_window": 200_000,
                    "max_output_tokens": 32_000,
                    "reasoning_enabled": True,
                    "vision_enabled": True,
                    "source": "codex",
                }
            }
        },
    )

    payload = service.build_external_subscription_capabilities()

    assert payload["protocol_version"] == 1
    subscription = payload["subscriptions"][0]
    assert subscription["authenticated"] is True
    assert subscription["models"][0]["id"] == "gpt-5.4"
    serialized = repr(payload)
    assert "secret-access" not in serialized
    assert "secret-refresh" not in serialized
    assert "account-secret" not in serialized


def test_execution_rejects_cross_user_subscription(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_provider_credentials",
        lambda: {"openai": {"type": "oauth", "access": "secret"}},
    )

    with pytest.raises(ValueError, match="owning Link user"):
        service.validate_external_subscription_execution(
            _execution(user_id="user-b"),
            "gpt-5.4",
        )


def test_execution_requires_local_oauth_and_exact_model(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_provider_credentials",
        lambda: {"openai": {"type": "api", "key": "not-returned"}},
    )

    with pytest.raises(ValueError, match="authentication is unavailable"):
        service.validate_external_subscription_execution(
            _execution(),
            "gpt-5.4",
        )

    monkeypatch.setattr(
        service,
        "get_provider_credentials",
        lambda: {"openai": {"type": "oauth", "access": "secret"}},
    )
    with pytest.raises(ValueError, match="requested model does not match"):
        service.validate_external_subscription_execution(
            _execution(),
            "gpt-5.4-mini",
        )
