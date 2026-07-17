"""Immutable per-turn attribution for Link-managed inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LinkInferenceContext:
    """Link-owned execution facts that must remain request scoped."""

    workspace_id: str
    user_id: str
    session_id: str
    agent_id: str
    run_id: str
    requested_model_id: str
    execution_source: Literal["link_gateway"] = "link_gateway"
    provider_state_owner: Literal["link_managed"] = "link_managed"
    settlement_mode: Literal["debit_link_credits"] = "debit_link_credits"

    def __post_init__(self) -> None:
        required = {
            "workspace_id": self.workspace_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "requested_model_id": self.requested_model_id,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(
                "Link inference context is missing required values: "
                + ", ".join(missing)
            )

    def headers(self, invocation_id: str) -> dict[str, str]:
        """Return per-invocation attribution headers without credentials."""

        return {
            "X-Link-Workspace-Id": self.workspace_id,
            "X-Link-User-Id": self.user_id,
            "X-Link-Session-Id": self.session_id,
            "X-Link-Agent-Id": self.agent_id,
            "X-Link-Run-Id": self.run_id,
            "X-Link-Request-Id": invocation_id,
            # Link currently consumes this compatibility name for settlement
            # idempotency. Keep both names equal during the protocol migration.
            "X-Link-Inference-Request-Id": invocation_id,
        }


__all__ = ["LinkInferenceContext"]
