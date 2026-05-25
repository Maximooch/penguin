"""Token usage compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

from typing import Any

from . import token_usage_runtime as core_token_usage_runtime

__all__ = ["TokenUsageCoreFacade"]


class TokenUsageCoreFacade:
    """Compatibility methods for token and context-window usage helpers."""

    def get_token_usage(
        self,
        session_id: str | None = None,
        conversation_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Return runtime or scoped token/context-window telemetry."""
        return core_token_usage_runtime.get_token_usage(
            self,
            session_id=session_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
        )

    def _get_session_token_usage(
        self,
        session_id: str,
        *,
        conversation_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return usage for one persisted session without global fallback."""
        return core_token_usage_runtime.get_session_token_usage(
            self,
            session_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
        )

    def _usage_from_session_messages(
        self,
        session: Any,
        *,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Build a conservative session-scoped usage payload from messages."""
        return core_token_usage_runtime.usage_from_session_messages(
            self,
            session,
            agent_id=agent_id,
        )
