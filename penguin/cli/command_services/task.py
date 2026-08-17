"""Task command domain helpers."""

from __future__ import annotations

from penguin.project.models import TaskStatus

__all__ = ["parse_task_status"]


def parse_task_status(value: str | None) -> TaskStatus | None:
    """Parse a case-insensitive task status or return ``None`` when unset."""

    if value is None:
        return None
    return TaskStatus(value.strip().lower())
