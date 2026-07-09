"""Session-goal compatibility facade for ``PenguinCore``."""

from __future__ import annotations

from typing import Any

from .session_goal_runtime import run_session_goal


class SessionGoalCoreFacade:
    """Expose bounded session-goal execution on PenguinCore."""

    async def run_session_goal(
        self,
        session_id: str,
        *,
        max_iterations: int | None = None,
        directory: str | None = None,
    ) -> dict[str, Any]:
        return await run_session_goal(
            self,
            session_id,
            max_iterations=max_iterations,
            directory=directory,
        )
