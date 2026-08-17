"""Immutable per-turn attribution for Link-managed inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LinkInferenceContext:
    """Link-owned execution facts that must remain request scoped."""

    workspace_id: str
    user_id: str
    run_id: str
    requested_model_id: str
    workos_organization_id: str | None = None
    session_id: str | None = None
    agent_id: str | None = None
    execution_source: Literal["link_gateway"] = "link_gateway"
    provider_state_owner: Literal["link_managed"] = "link_managed"
    settlement_mode: Literal["debit_link_credits"] = "debit_link_credits"

    def __post_init__(self) -> None:
        required = {
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "run_id": self.run_id,
            "requested_model_id": self.requested_model_id,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(
                "Link inference context is missing required values: "
                + ", ".join(missing)
            )

        optional_identity = {
            "workos_organization_id": self.workos_organization_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
        }
        invalid = [
            name
            for name, value in optional_identity.items()
            if value is not None and (not isinstance(value, str) or not value.strip())
        ]
        if invalid:
            raise ValueError(
                "Link inference context has invalid optional values: "
                + ", ".join(invalid)
            )
        if (self.session_id is None) != (self.agent_id is None):
            raise ValueError(
                "Link inference session and agent attribution must be "
                "supplied together."
            )

    def headers(self, invocation_id: str) -> dict[str, str]:
        """Return per-invocation attribution headers without credentials."""

        headers = {
            "X-Link-Workspace-Id": self.workspace_id,
            "X-Link-User-Id": self.user_id,
            "X-Link-Run-Id": self.run_id,
            "X-Link-Request-Id": invocation_id,
            # Link currently consumes this compatibility name for settlement
            # idempotency. Keep both names equal during the protocol migration.
            "X-Link-Inference-Request-Id": invocation_id,
        }
        if self.workos_organization_id is not None:
            headers["X-Link-WorkOS-Organization-Id"] = self.workos_organization_id
        if self.session_id is not None and self.agent_id is not None:
            headers["X-Link-Session-Id"] = self.session_id
            headers["X-Link-Agent-Id"] = self.agent_id
        return headers


__all__ = ["LinkInferenceContext"]
