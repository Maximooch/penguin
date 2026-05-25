"""Small core state helpers delegated by :mod:`penguin.core`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "notify_progress",
    "register_progress_callback",
    "reset_context",
    "validate_path",
]

ProgressCallback = Callable[[int, int, str | None], None]
AccessCheck = Callable[[Path, int], bool]


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
