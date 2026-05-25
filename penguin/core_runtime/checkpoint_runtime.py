"""Checkpoint runtime helpers used by :mod:`penguin.core`."""

from __future__ import annotations

from typing import Any

__all__ = [
    "branch_from_checkpoint",
    "cleanup_old_checkpoints",
    "create_checkpoint",
    "get_checkpoint_stats",
    "list_checkpoints",
    "rollback_to_checkpoint",
]


async def create_checkpoint(
    conversation_manager: Any,
    *,
    name: str | None = None,
    description: str | None = None,
) -> str | None:
    """Create a manual checkpoint through the conversation manager."""
    return await conversation_manager.create_manual_checkpoint(
        name=name,
        description=description,
    )


async def rollback_to_checkpoint(
    conversation_manager: Any,
    checkpoint_id: str,
) -> bool:
    """Rollback the active conversation to a checkpoint."""
    return await conversation_manager.rollback_to_checkpoint(checkpoint_id)


async def branch_from_checkpoint(
    conversation_manager: Any,
    checkpoint_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
) -> str | None:
    """Create a new conversation branch from a checkpoint."""
    return await conversation_manager.branch_from_checkpoint(
        checkpoint_id,
        name=name,
        description=description,
    )


def list_checkpoints(
    conversation_manager: Any,
    *,
    session_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List checkpoints, defaulting to the current session when available."""
    resolved_session_id = session_id
    if resolved_session_id is None:
        current_session = conversation_manager.get_current_session()
        if current_session:
            resolved_session_id = current_session.id

    return conversation_manager.list_checkpoints(
        session_id=resolved_session_id,
        limit=limit,
    )


async def cleanup_old_checkpoints(conversation_manager: Any) -> int:
    """Clean up old checkpoints according to retention policy."""
    return await conversation_manager.cleanup_old_checkpoints()


def get_checkpoint_stats(conversation_manager: Any) -> dict[str, Any]:
    """Return aggregate checkpoint statistics for diagnostics and API payloads."""
    checkpoint_manager = getattr(conversation_manager, "checkpoint_manager", None)
    if not conversation_manager or not checkpoint_manager:
        return {
            "enabled": False,
            "total_checkpoints": 0,
            "auto_checkpoints": 0,
            "manual_checkpoints": 0,
            "branch_checkpoints": 0,
        }

    checkpoints = conversation_manager.list_checkpoints(limit=1000)
    config = checkpoint_manager.config

    return {
        "enabled": True,
        "total_checkpoints": len(checkpoints),
        "auto_checkpoints": len(
            [checkpoint for checkpoint in checkpoints if checkpoint.get("auto", False)]
        ),
        "manual_checkpoints": len(
            [
                checkpoint
                for checkpoint in checkpoints
                if checkpoint.get("type") == "manual"
            ]
        ),
        "branch_checkpoints": len(
            [
                checkpoint
                for checkpoint in checkpoints
                if checkpoint.get("type") == "branch"
            ]
        ),
        "config": {
            "frequency": config.frequency,
            "retention_hours": config.retention["keep_all_hours"],
            "max_age_days": config.retention["max_age_days"],
        },
    }
