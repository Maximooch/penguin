"""Session-goal compatibility facade for ``PenguinCore``."""

from __future__ import annotations

from typing import Any

from .session_goal_runtime import run_session_goal

__all__ = ["SessionGoalCoreFacade"]


class SessionGoalCoreFacade:
    """Expose session-goal execution on PenguinCore."""

    async def run_session_goal(
        self,
        session_id: str,
        *,
        max_iterations: int | None = None,
        timeout_seconds: int | None = None,
        directory: str | None = None,
    ) -> dict[str, Any]:
        """Execute a persisted session goal.

        Args:
            session_id: Persisted session containing the active goal.
            max_iterations: Optional goal-specific iteration ceiling.
            timeout_seconds: Optional wall-clock ceiling for this run.
            directory: Optional directory assertion. It binds an unbound legacy
                session once; later runs must match the persisted directory.

        Returns:
            The finalized goal and typed RunMode result.
        """
        return await run_session_goal(
            self,
            session_id,
            max_iterations=max_iterations,
            timeout_seconds=timeout_seconds,
            directory=directory,
        )
