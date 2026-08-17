"""Top-level CLI mode selection independent of Typer and runtime globals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["DispatchMode", "DispatchRequest", "select_dispatch_mode"]


class DispatchMode(str, Enum):
    """Mutually exclusive top-level CLI execution modes."""

    RUN_MODE = "run_mode"
    SESSION = "session"
    DIRECT_PROMPT = "direct_prompt"
    CONTINUOUS = "continuous"
    INTERACTIVE = "interactive"
    SUBCOMMAND = "subcommand"


@dataclass(frozen=True)
class DispatchRequest:
    """Inputs that determine the CLI execution mode."""

    run_task: str | None
    continue_last: bool
    resume_session: str | None
    prompt: str | None
    continuous: bool
    invoked_subcommand: str | None


def select_dispatch_mode(request: DispatchRequest) -> DispatchMode:
    """Select one mode using the CLI's documented precedence contract."""

    if request.run_task is not None:
        return DispatchMode.RUN_MODE
    if request.continue_last or request.resume_session:
        return DispatchMode.SESSION
    if request.prompt is not None:
        return DispatchMode.DIRECT_PROMPT
    if request.continuous:
        return DispatchMode.CONTINUOUS
    if request.invoked_subcommand is None:
        return DispatchMode.INTERACTIVE
    return DispatchMode.SUBCOMMAND
