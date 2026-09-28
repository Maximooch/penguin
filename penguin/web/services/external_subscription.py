"""Link-facing external-subscription capability and execution contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel

from penguin.web.services.provider_catalog import codex_oauth_provider_models
from penguin.web.services.provider_credentials import get_provider_credentials
from penguin.web.services.reasoning_variants import (
    reasoning_effort_from_metadata,
    reasoning_efforts_from_metadata,
)

EXTERNAL_SUBSCRIPTION_PROTOCOL_VERSION = 1
EXTERNAL_SUBSCRIPTION_AUTHORITY_MAX_LIFETIME = timedelta(minutes=5)


class ExternalSubscriptionExecutionRequest(BaseModel):
    """Immutable external-subscription authority supplied by Link."""

    protocol_version: Literal[1]
    owner_user_id: str
    user_id: str
    actor_user_id: str
    credential_owner_type: Literal["user"]
    credential_owner_id: str
    workspace_id: str
    agent_id: str
    run_id: str
    issued_at: datetime
    expires_at: datetime
    requested_model_id: str
    agent_runtime: Literal["penguin"]
    provider: Literal["openai"]
    inference_transport: Literal["codex_responses_compat"]
    execution_source: Literal["local_penguin"]
    provider_state_owner: Literal["user_owned"]
    credential_custodian: Literal["local_penguin"]
    settlement_mode: Literal["subscription_quota"]
    usage_authority: Literal["local_runtime_observed"]
    integration_support: Literal["ecosystem_compatible"]
    allow_fallback_to_link_gateway: Literal[False] = False
    authority_signature_version: Literal[1]
    authority_signature: str

    def public_result(self) -> dict[str, Any]:
        """Return execution facts without credentials or local auth records."""

        model_dump = getattr(self, "model_dump", None)
        if callable(model_dump):
            result = model_dump()
        else:
            result = self.dict()
        result.pop("authority_signature", None)
        result["issued_at"] = self.issued_at.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        result["expires_at"] = self.expires_at.isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        return result

    def signature_payload(self) -> bytes:
        """Return the canonical payload Link signs for this authority."""

        values = [
            self.protocol_version,
            self.owner_user_id,
            self.user_id,
            self.actor_user_id,
            self.credential_owner_type,
            self.credential_owner_id,
            self.workspace_id,
            self.agent_id,
            self.run_id,
            self.issued_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            self.expires_at.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            self.requested_model_id,
            self.agent_runtime,
            self.provider,
            self.inference_transport,
            self.execution_source,
            self.provider_state_owner,
            self.credential_custodian,
            self.settlement_mode,
            self.usage_authority,
            self.integration_support,
            self.allow_fallback_to_link_gateway,
        ]
        return json.dumps(values, separators=(",", ":"), ensure_ascii=False).encode()


def build_external_subscription_capabilities() -> dict[str, Any]:
    """Describe locally authenticated subscriptions without exposing secrets."""

    records = get_provider_credentials()
    openai_record = records.get("openai")
    authenticated = bool(
        isinstance(openai_record, dict)
        and openai_record.get("type") == "oauth"
        and (
            str(openai_record.get("access") or "").strip()
            or str(openai_record.get("refresh") or "").strip()
        )
    )
    discovered = (
        codex_oauth_provider_models(openai_record).get("openai", {})
        if authenticated
        else {}
    )
    models = [
        _model_capability(model_id, config)
        for model_id, config in sorted(
            discovered.items(),
            key=lambda item: (_model_priority(item[1]), item[0]),
        )
        if isinstance(model_id, str) and isinstance(config, dict)
    ]

    return {
        "protocol_version": EXTERNAL_SUBSCRIPTION_PROTOCOL_VERSION,
        "agent_runtime": "penguin",
        "subscriptions": [
            {
                "provider": "openai",
                "inference_transport": "codex_responses_compat",
                "credential_custodian": "local_penguin",
                "account_scope": "personal",
                "settlement_mode": "subscription_quota",
                "usage_authority": "local_runtime_observed",
                "usage_reporting_level": "turn_aggregate",
                "integration_support": "ecosystem_compatible",
                "authenticated": authenticated,
                "catalog_state": (
                    "ready" if models else "empty" if authenticated else "disconnected"
                ),
                "models": models,
            }
        ],
    }


def validate_external_subscription_execution(
    execution: ExternalSubscriptionExecutionRequest,
    requested_model: str | None,
    link_service_secret: str,
) -> None:
    """Fail closed unless Link's user-scoped request matches local OAuth state."""

    secret = str(link_service_secret or "").strip()
    if not secret:
        raise ValueError("Link execution signing is not configured.")
    expected_signature = hmac.new(
        secret.encode(), execution.signature_payload(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(execution.authority_signature, expected_signature):
        raise ValueError("Link's personal-subscription execution signature is invalid.")
    if execution.owner_user_id != execution.user_id:
        raise ValueError("A personal subscription can only serve its owning Link user.")
    if execution.actor_user_id != execution.owner_user_id:
        raise ValueError("A personal subscription can only serve its owning Link user.")
    if execution.credential_owner_id != execution.owner_user_id:
        raise ValueError(
            "The personal-subscription credential owner does not match Link's "
            "execution authority."
        )
    if not all(
        value.strip()
        for value in (
            execution.workspace_id,
            execution.agent_id,
            execution.run_id,
        )
    ):
        raise ValueError(
            "Personal-subscription execution requires workspace, agent, and "
            "run identity."
        )
    now = datetime.now(timezone.utc)
    issued_at = execution.issued_at.astimezone(timezone.utc)
    expires_at = execution.expires_at.astimezone(timezone.utc)
    if expires_at <= now:
        raise ValueError("Link's personal-subscription execution authority expired.")
    if expires_at <= issued_at or (
        expires_at - issued_at > EXTERNAL_SUBSCRIPTION_AUTHORITY_MAX_LIFETIME
    ):
        raise ValueError(
            "Link's personal-subscription execution authority has an invalid lifetime."
        )
    selected = str(requested_model or "").strip()
    if not selected or selected != execution.requested_model_id:
        raise ValueError(
            "The requested model does not match Link's external-subscription execution."
        )

    openai_record = get_provider_credentials().get("openai")
    if not isinstance(openai_record, dict) or openai_record.get("type") != "oauth":
        raise ValueError(
            "ChatGPT subscription authentication is unavailable in this "
            "Penguin runtime."
        )
    if not (
        str(openai_record.get("access") or "").strip()
        or str(openai_record.get("refresh") or "").strip()
    ):
        raise ValueError(
            "ChatGPT subscription authentication requires reauthentication."
        )


def _model_capability(model_id: str, config: dict[str, Any]) -> dict[str, Any]:
    reasoning_efforts = reasoning_efforts_from_metadata(
        config.get("supported_reasoning_levels")
    )
    default_reasoning_effort = reasoning_effort_from_metadata(
        config.get("default_reasoning_level")
    )
    return {
        "id": model_id,
        "name": str(config.get("name") or config.get("model") or model_id),
        "context_window": _positive_int(
            config.get("max_context_window_tokens") or config.get("context_window")
        ),
        "max_output_tokens": _positive_int(config.get("max_output_tokens")),
        "reasoning": bool(config.get("reasoning_enabled") or reasoning_efforts),
        "reasoning_efforts": list(reasoning_efforts),
        "default_reasoning_effort": default_reasoning_effort,
        # The ChatGPT-backed Codex transport accepts OpenAI's priority service
        # tier. Link presents that exact transport capability as Fast mode.
        "service_tiers": ["priority"],
        "vision": bool(config.get("vision_enabled")),
        "tools": True,
    }


def _model_priority(config: dict[str, Any]) -> int:
    value = config.get("priority")
    return value if isinstance(value, int) and value >= 0 else 1_000_000


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and value > 0 else None


__all__ = [
    "EXTERNAL_SUBSCRIPTION_PROTOCOL_VERSION",
    "ExternalSubscriptionExecutionRequest",
    "build_external_subscription_capabilities",
    "validate_external_subscription_execution",
]
