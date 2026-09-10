"""Elapsed-time policy for process waiting inside the reasoning loop."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from penguin.tools.runtime import ToolResult


@dataclass
class ProcessWaitGuard:
    """Allow live process waits, but stop a turn after bounded lack of progress."""

    timeout_seconds: float = 120.0
    progress: dict[str, tuple[int, float]] = field(default_factory=dict)

    def check(self, results: list[Any]) -> tuple[bool, str | None] | None:
        """Return a wait decision, or None for ordinary tool-loop detection."""
        live: list[tuple[str, int]] = []
        for result in results:
            if isinstance(result, ToolResult):
                data = dict(result.structured_output or {})
                data.update(action=result.name, status=result.status)
            elif isinstance(result, dict):
                data = {**(result.get("metadata") or {}), **result}
            else:
                return None
            if data.get("action") not in {
                "process",
                "process_poll",
                "process_start",
                "execute_command",
            }:
                return None
            if data.get("status") != "completed" or data.get("process_status") not in {
                "running",
                "draining",
            }:
                return None
            process_id = data.get("process_id")
            cursor = data.get("next_sequence")
            if not isinstance(process_id, str) or not isinstance(cursor, int):
                return None
            live.append((process_id, cursor))
        if not live:
            return None
        now = time.monotonic()
        for process_id, cursor in live:
            previous, since = self.progress.get(process_id, (cursor, now))
            if cursor > previous:
                since = now
            self.progress[process_id] = (max(previous, cursor), since)
            if now - since >= self.timeout_seconds:
                return True, "process_wait_budget_exhausted"
        return False, None


__all__ = ["ProcessWaitGuard"]
