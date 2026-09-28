from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest

from penguin.web.services import external_subscription as service

LINK_SERVICE_SECRET = "test-link-service-secret"


def _execution(**overrides: object) -> service.ExternalSubscriptionExecutionRequest:
    issued_at = datetime.now(timezone.utc)
    values: dict[str, object] = {
        "protocol_version": 1,
        "owner_user_id": "user-a",
        "user_id": "user-a",
        "actor_user_id": "user-a",
        "credential_owner_type": "user",
        "credential_owner_id": "user-a",
        "workspace_id": "workspace-a",
        "agent_id": "agent-a",
        "run_id": "run-a",
        "issued_at": issued_at,
        "expires_at": issued_at + timedelta(minutes=5),
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
        "authority_signature_version": 1,
        "authority_signature": "unsigned",
    }
    values.update(overrides)
    execution = service.ExternalSubscriptionExecutionRequest(**values)
    signature = hmac.new(
        LINK_SERVICE_SECRET.encode(), execution.signature_payload(), hashlib.sha256
    ).hexdigest()
    model_copy = getattr(execution, "model_copy", None)
    if callable(model_copy):
        return model_copy(update={"authority_signature": signature})
    return execution.copy(update={"authority_signature": signature})


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
                    "supported_reasoning_levels": [
                        "low",
                        "medium",
                        "high",
                        "xhigh",
                    ],
                    "default_reasoning_level": "medium",
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
    model = subscription["models"][0]
    assert model["id"] == "gpt-5.4"
    assert model["reasoning_efforts"] == ["low", "medium", "high", "xhigh"]
    assert model["default_reasoning_effort"] == "medium"
    assert model["service_tiers"] == ["priority"]
    serialized = repr(payload)
    assert "secret-access" not in serialized
    assert "secret-refresh" not in serialized
    assert "account-secret" not in serialized


def test_public_execution_result_supports_pydantic_1(monkeypatch) -> None:
    if hasattr(service.ExternalSubscriptionExecutionRequest, "model_dump"):
        monkeypatch.setattr(
            service.ExternalSubscriptionExecutionRequest,
            "model_dump",
            None,
        )
    monkeypatch.setattr(
        service.ExternalSubscriptionExecutionRequest,
        "dict",
        lambda self: dict(self.__dict__),
    )

    result = _execution().public_result()

    assert result["owner_user_id"] == "user-a"
    assert result["settlement_mode"] == "subscription_quota"
    assert result["issued_at"].endswith("Z")
    assert "authority_signature" not in result


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
            LINK_SERVICE_SECRET,
        )


def test_execution_accepts_an_authenticated_link_user_without_runtime_pairing(
    monkeypatch,
) -> None:
    monkeypatch.delenv("PENGUIN_LINK_SUBSCRIPTION_OWNER_USER_ID", raising=False)
    monkeypatch.setattr(
        service,
        "get_provider_credentials",
        lambda: {"openai": {"type": "oauth", "access": "secret"}},
    )

    service.validate_external_subscription_execution(
        _execution(), "gpt-5.4", LINK_SERVICE_SECRET
    )


def test_execution_ignores_a_stale_runtime_user_binding(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PENGUIN_LINK_SUBSCRIPTION_OWNER_USER_ID", "user-b")
    monkeypatch.setattr(
        service,
        "get_provider_credentials",
        lambda: {"openai": {"type": "oauth", "access": "secret"}},
    )

    service.validate_external_subscription_execution(
        _execution(), "gpt-5.4", LINK_SERVICE_SECRET
    )


def test_execution_rejects_expired_or_cross_owner_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        service,
        "get_provider_credentials",
        lambda: {"openai": {"type": "oauth", "access": "secret"}},
    )
    now = datetime.now(timezone.utc)

    with pytest.raises(ValueError, match="expired"):
        service.validate_external_subscription_execution(
            _execution(issued_at=now - timedelta(minutes=10), expires_at=now),
            "gpt-5.4",
            LINK_SERVICE_SECRET,
        )

    with pytest.raises(ValueError, match="credential owner"):
        service.validate_external_subscription_execution(
            _execution(credential_owner_id="user-b"),
            "gpt-5.4",
            LINK_SERVICE_SECRET,
        )


def test_execution_requires_local_oauth_and_exact_model(monkeypatch) -> None:
    monkeypatch.setenv("PENGUIN_LINK_SUBSCRIPTION_OWNER_USER_ID", "user-a")
    monkeypatch.setattr(
        service,
        "get_provider_credentials",
        lambda: {"openai": {"type": "api", "key": "not-returned"}},
    )

    with pytest.raises(ValueError, match="authentication is unavailable"):
        service.validate_external_subscription_execution(
            _execution(),
            "gpt-5.4",
            LINK_SERVICE_SECRET,
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
            LINK_SERVICE_SECRET,
        )


def test_execution_rejects_an_invalid_link_signature() -> None:
    with pytest.raises(ValueError, match="signature is invalid"):
        service.validate_external_subscription_execution(
            _execution(authority_signature="invalid"),
            "gpt-5.4",
            "different-service-secret",
        )
