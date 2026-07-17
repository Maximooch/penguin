"""Link-facing external-subscription capability and execution contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from penguin.web.services.provider_catalog import codex_oauth_provider_models
from penguin.web.services.provider_credentials import get_provider_credentials

EXTERNAL_SUBSCRIPTION_PROTOCOL_VERSION = 1


class ExternalSubscriptionExecutionRequest(BaseModel):
    """Immutable external-subscription authority supplied by Link."""

    protocol_version: Literal[1]
    owner_user_id: str
    user_id: str
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

    def public_result(self) -> dict[str, Any]:
        """Return execution facts without credentials or local auth records."""

        return self.model_dump()


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
) -> None:
    """Fail closed unless Link's user-scoped request matches local OAuth state."""

    if execution.owner_user_id != execution.user_id:
        raise ValueError("A personal subscription can only serve its owning Link user.")
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
    supported_reasoning = config.get("supported_reasoning_levels")
    return {
        "id": model_id,
        "name": str(config.get("name") or config.get("model") or model_id),
        "context_window": _positive_int(
            config.get("max_context_window_tokens") or config.get("context_window")
        ),
        "max_output_tokens": _positive_int(config.get("max_output_tokens")),
        "reasoning": bool(
            config.get("reasoning_enabled")
            or (
                isinstance(supported_reasoning, (list, tuple))
                and bool(supported_reasoning)
            )
        ),
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
