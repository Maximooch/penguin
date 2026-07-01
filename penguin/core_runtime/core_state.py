"""Small core state helpers delegated by :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "branch_from_snapshot",
    "create_snapshot",
    "list_context_files",
    "notify_progress",
    "register_progress_callback",
    "reset_context",
    "reset_state",
    "restore_snapshot",
    "validate_path",
]

ProgressCallback = Callable[[int, int, str | None], None]
AccessCheck = Callable[[Path, int], bool]
ScheduleCleanup = Callable[[], Any]


def validate_path(path: Path, *, access_check: AccessCheck | None = None) -> None:
    """Validate and create a writable directory path."""
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)

    can_write = access_check or os.access
    if not can_write(path, os.W_OK):
        raise PermissionError(f"No write access to {path}")


def register_progress_callback(core: Any, callback: ProgressCallback) -> None:
    """Register a callback for progress updates."""
    core.progress_callbacks.append(callback)


def notify_progress(
    core: Any,
    iteration: int,
    max_iterations: int,
    message: str | None = None,
) -> None:
    """Notify registered progress callbacks."""
    for callback in core.progress_callbacks:
        callback(iteration, max_iterations, message)


def reset_context(core: Any, *, diagnostics_manager: Any) -> None:
    """Reset conversation context and diagnostics."""
    diagnostics_manager.reset()
    core._interrupted = False
    core.conversation_manager.reset()


def reset_state(
    core: Any,
    *,
    diagnostics_manager: Any,
    schedule_browser_close: ScheduleCleanup | None = None,
) -> None:
    """Reset core conversation state and schedule external runtime cleanup."""

    reset_context(core, diagnostics_manager=diagnostics_manager)
    core._interrupted = False

    if schedule_browser_close is None:
        from penguin.tools.browser_tools import browser_manager

        def schedule_default_browser_close() -> Any:
            return asyncio.create_task(browser_manager.close())

        schedule_browser_close = schedule_default_browser_close

    schedule_browser_close()


def list_context_files(core: Any) -> list[dict[str, Any]]:
    """Return all context files known to the conversation manager."""

    return core.conversation_manager.list_context_files()


def create_snapshot(core: Any, *, meta: dict[str, Any] | None = None) -> str | None:
    """Persist current conversation state and return a snapshot id."""

    return core.conversation_manager.create_snapshot(meta=meta)


def restore_snapshot(core: Any, snapshot_id: str) -> bool:
    """Restore conversation state from a snapshot id."""

    return bool(core.conversation_manager.restore_snapshot(snapshot_id))


def branch_from_snapshot(
    core: Any,
    snapshot_id: str,
    *,
    meta: dict[str, Any] | None = None,
) -> str | None:
    """Fork a snapshot into a new branch and load it."""

    return core.conversation_manager.branch_from_snapshot(snapshot_id, meta=meta)
