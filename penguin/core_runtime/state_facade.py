"""Core state compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from penguin.utils.diagnostics import diagnostics

from . import core_state as core_state_runtime

__all__ = ["StateCoreFacade"]

if TYPE_CHECKING:
    from pathlib import Path


class StateCoreFacade:
    """Compatibility methods for context, state, and snapshot helpers."""

    def validate_path(self, path: Path) -> None:
        """Validate and create a directory path if needed."""
        core_state_runtime.validate_path(path)

    def register_progress_callback(
        self,
        callback: Any,
    ) -> None:
        """Register a callback for progress updates during multi-step processing."""
        core_state_runtime.register_progress_callback(self, callback)

    def notify_progress(
        self,
        iteration: int,
        max_iterations: int,
        message: str | None = None,
    ) -> None:
        """Notify all registered callbacks about progress."""
        core_state_runtime.notify_progress(
            self,
            iteration,
            max_iterations,
            message,
        )

    def reset_context(self) -> None:
        """Reset conversation context and diagnostics."""
        core_state_runtime.reset_context(self, diagnostics_manager=diagnostics)

    async def reset_state(self) -> None:
        """Reset the core state completely."""
        core_state_runtime.reset_state(self, diagnostics_manager=diagnostics)

    def list_context_files(self) -> list[dict[str, Any]]:
        """List all available context files."""
        return core_state_runtime.list_context_files(self)

    def create_snapshot(self, meta: dict[str, Any] | None = None) -> str | None:
        """Persist current conversation state and return snapshot_id."""
        return core_state_runtime.create_snapshot(self, meta=meta)

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Load conversation from snapshot; returns success bool."""
        return core_state_runtime.restore_snapshot(self, snapshot_id)

    def branch_from_snapshot(
        self,
        snapshot_id: str,
        meta: dict[str, Any] | None = None,
    ) -> str | None:
        """Fork a snapshot into a new branch and load it."""
        return core_state_runtime.branch_from_snapshot(self, snapshot_id, meta=meta)
