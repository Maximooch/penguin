"""Request-scoped observation of successfully committed canonical edits."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["capture_edits", "record_edits"]

_EDITS: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "committed_edits", default=None
)
MAX_DIFF_BYTES = 128 * 1024
MAX_DIFF_FILES = 16


@contextmanager
def capture_edits() -> Iterator[list[dict[str, Any]]]:
    """Capture existing transaction snapshots without extra filesystem reads."""
    edits: list[dict[str, Any]] = []
    token = _EDITS.set(edits)
    try:
        yield edits
    finally:
        _EDITS.reset(token)


def record_edits(changes: list[dict[str, Any]]) -> None:
    """Observe only committed writes, bounded without truncating file contents."""
    target = _EDITS.get()
    if target is None:
        return
    for change in changes:
        if len(target) >= MAX_DIFF_FILES:
            break
        old, new = change.get("old_content", ""), change.get("new_content")
        record = {"path": str(change["resolved_path"])}
        if (
            not isinstance(new, str)
            or len(str(old).encode()) + len(new.encode()) > MAX_DIFF_BYTES
        ):
            record["omitted"] = True
        else:
            record.update(
                old_text=old if change.get("existed_before") else None, new_text=new
            )
        target.append(record)
