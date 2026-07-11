"""Fallback routing for session-goal commands sent through chat transport."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any, Literal

from penguin.core_runtime.session_goals import GoalValidationError
from penguin.web.schemas.session_goal import (
    SessionGoalRunRequest,
    SessionGoalUpdateRequest,
)

from . import session_goal

__all__ = [
    "SessionGoalCommand",
    "execute_session_goal_command",
    "parse_session_goal_command",
]


_GOAL_COMMANDS = {"/goal", "/247"}
_GOAL_CONTROLS = {"status", "pause", "resume", "run", "clear"}


@dataclass(frozen=True)
class SessionGoalCommand:
    """A session-goal command recovered from a raw chat message."""

    action: Literal["set", "status", "pause", "resume", "run", "clear"]
    display_command: str
    objective: str | None = None
    replace: bool = False


def parse_session_goal_command(text: str) -> SessionGoalCommand | None:
    """Parse a ``/goal`` or ``/247`` command without treating it as chat text.

    The TUI normally handles these commands locally. This parser is deliberately
    kept server-side as a compatibility backstop for pasted input, old clients,
    and REST chat submissions that bypass the local command dispatcher.
    """

    normalized = text.strip()
    if not normalized:
        return None

    first_line = normalized.split("\n", 1)[0].strip()
    command = first_line.split(None, 1)[0] if first_line else ""
    if command not in _GOAL_COMMANDS:
        return None

    argument_text = normalized[len(command) :].strip()
    try:
        arguments = shlex.split(argument_text)
    except ValueError as exc:
        raise GoalValidationError(f"Invalid /goal command: {exc}") from exc

    if not arguments:
        return SessionGoalCommand(action="status", display_command=normalized)

    control = arguments[0].lower()
    if control in _GOAL_CONTROLS:
        return SessionGoalCommand(action=control, display_command=normalized)

    replace = "--replace" in arguments
    objective = " ".join(
        argument for argument in arguments if argument != "--replace"
    ).strip()
    if not objective:
        raise GoalValidationError("/goal requires an objective")
    return SessionGoalCommand(
        action="set",
        display_command=normalized,
        objective=objective,
        replace=replace,
    )


async def execute_session_goal_command(
    core: Any,
    session_id: str,
    command: SessionGoalCommand,
    *,
    client_message_id: str | None = None,
    client_part_id: str | None = None,
    directory: str | None = None,
) -> dict[str, Any]:
    """Execute a recovered goal command through the durable goal service."""

    if command.action == "status":
        return {"goal": session_goal.get_goal(core, session_id), "status": "ok"}

    if command.action == "clear":
        await session_goal.clear_goal(core, session_id)
        return {"goal": None, "status": "ok"}

    if command.action in {"pause", "resume"}:
        status = "paused" if command.action == "pause" else "active"
        goal = await session_goal.update_goal(
            core,
            session_id,
            SessionGoalUpdateRequest(status=status),
        )
        if command.action == "pause":
            return {"goal": goal, "status": "ok"}

    if command.action == "set":
        assert command.objective is not None
        display_command = command.display_command if client_message_id else None
        await session_goal.update_goal(
            core,
            session_id,
            SessionGoalUpdateRequest(
                objective=command.objective,
                replace=command.replace,
                display_command=display_command,
                client_message_id=client_message_id if display_command else None,
                client_part_id=client_part_id if display_command else None,
            ),
        )

    if command.action in {"set", "resume", "run"}:
        return await session_goal.run_goal(
            core,
            session_id,
            SessionGoalRunRequest(directory=directory.strip() if directory else None),
        )

    raise GoalValidationError(f"Unsupported /goal command action: {command.action}")
