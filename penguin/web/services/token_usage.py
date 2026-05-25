"""Token usage service helpers for route handlers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def get_token_usage_payload(
    core: Any,
    *,
    session_id: str | None = None,
    conversation_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Build token usage response payload, preserving explicit scope metadata."""

    usage = core.get_token_usage(
        session_id=session_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
    )
    if usage.get("scope") == "missing":
        raise HTTPException(status_code=404, detail=usage)
    return {"usage": usage}
