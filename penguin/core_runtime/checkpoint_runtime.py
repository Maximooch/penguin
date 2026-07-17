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
            resolved_session_id = getattr(current_session, "id", None)

    return conversation_manager.list_checkpoints(
        session_id=resolved_session_id,
        limit=limit,
    )


async def cleanup_old_checkpoints(
    conversation_manager: Any,
    *,
    execute: bool = False,
    confirmation: str | None = None,
) -> dict[str, Any]:
    """Plan cleanup by default or execute an explicitly confirmed plan."""

    if not execute and confirmation is None:
        return await conversation_manager.cleanup_old_checkpoints()
    return await conversation_manager.cleanup_old_checkpoints(
        execute=execute,
        confirmation=confirmation,
    )


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
    index_snapshot_method = getattr(
        checkpoint_manager,
        "get_checkpoint_index_snapshot",
        None,
    )
    indexed_checkpoints = (
        index_snapshot_method()
        if callable(index_snapshot_method)
        else getattr(checkpoint_manager, "checkpoint_index", None)
    )
    config = getattr(checkpoint_manager, "config", None)
    retention = getattr(config, "retention", None)
    if not isinstance(retention, dict):
        retention = {}

    payload = {
        "enabled": True,
        "total_checkpoints": (
            len(indexed_checkpoints)
            if isinstance(indexed_checkpoints, dict)
            else len(checkpoints)
        ),
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
            "frequency": getattr(config, "frequency", None),
            "retention_hours": retention.get("keep_all_hours"),
            "max_age_days": retention.get("max_age_days"),
        },
    }
    safety_method = getattr(
        type(checkpoint_manager),
        "get_storage_safety_status",
        None,
    )
    if callable(safety_method):
        payload["storage_safety"] = checkpoint_manager.get_storage_safety_status()
    return payload
