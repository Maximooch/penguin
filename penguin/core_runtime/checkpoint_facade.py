"""Checkpoint compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

from typing import Any

from . import checkpoint_runtime as core_checkpoint_runtime

__all__ = ["CheckpointCoreFacade"]


class CheckpointCoreFacade:
    """Compatibility methods for checkpoint management helpers."""

    async def create_checkpoint(
        self,
        name: str | None = None,
        description: str | None = None,
    ) -> str | None:
        """Create a manual checkpoint of the current conversation state."""
        return await core_checkpoint_runtime.create_checkpoint(
            self.conversation_manager,
            name=name,
            description=description,
        )

    async def rollback_to_checkpoint(self, checkpoint_id: str) -> bool:
        """Rollback conversation to a specific checkpoint."""
        return await core_checkpoint_runtime.rollback_to_checkpoint(
            self.conversation_manager,
            checkpoint_id,
        )

    async def branch_from_checkpoint(
        self,
        checkpoint_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> str | None:
        """Create a new conversation branch from a checkpoint."""
        return await core_checkpoint_runtime.branch_from_checkpoint(
            self.conversation_manager,
            checkpoint_id,
            name=name,
            description=description,
        )

    def list_checkpoints(
        self,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List available checkpoints with optional filtering."""
        return core_checkpoint_runtime.list_checkpoints(
            self.conversation_manager,
            session_id=session_id,
            limit=limit,
        )

    async def cleanup_old_checkpoints(
        self,
        *,
        execute: bool = False,
        confirmation: str | None = None,
    ) -> dict[str, Any]:
        """Plan cleanup by default or execute an explicitly confirmed plan."""

        if not execute and confirmation is None:
            return await core_checkpoint_runtime.cleanup_old_checkpoints(
                self.conversation_manager
            )
        return await core_checkpoint_runtime.cleanup_old_checkpoints(
            self.conversation_manager,
            execute=execute,
            confirmation=confirmation,
        )

    def get_checkpoint_stats(self) -> dict[str, Any]:
        """Get statistics about the checkpointing system."""
        return core_checkpoint_runtime.get_checkpoint_stats(self.conversation_manager)
