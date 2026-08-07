"""Top-level CLI mode selection independent of Typer and runtime globals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from penguin.cli.output_policy import RunModeCompletion, classify_runmode_completion

__all__ = [
    "DispatchMode",
    "DispatchRequest",
    "execute_run_mode",
    "select_dispatch_mode",
]


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


async def execute_run_mode(
    core: Any,
    console: Any,
    *,
    task_name: str | None,
    continuous: bool,
    time_limit: int | None,
    description: str | None,
) -> RunModeCompletion:
    """Execute RunMode and return render-neutral completion truth."""

    stream_started = False

    async def stream_callback(chunk: str, message_type: str = "assistant") -> None:
        nonlocal stream_started
        if chunk == "" and stream_started:
            console.print("")
            stream_started = False
            return
        if not chunk:
            return
        if not stream_started:
            console.print("")
            stream_started = True
        console.print(
            chunk,
            style="dim" if message_type == "reasoning" else "white",
            end="",
            highlight=False,
            soft_wrap=True,
        )
        try:
            console.file.flush()
        except (AttributeError, OSError):
            pass

    async def update_callback() -> None:
        return None

    if continuous:
        console.print(
            f"[bold blue]Starting continuous mode{' for task: ' + task_name if task_name else ''}[/bold blue]"
        )
        if time_limit:
            console.print(f"[blue]Time limit: {time_limit} minutes[/blue]")
        console.print("[blue]Press Ctrl+C to stop execution gracefully[/blue]")
    else:
        if not task_name:
            raise ValueError("A task name is required for non-continuous RunMode")
        console.print(f"[bold blue]Running task: {task_name}[/bold blue]")
        if description:
            console.print(f"[blue]Description: {description}[/blue]")
        if time_limit:
            console.print(f"[blue]Time limit: {time_limit} minutes[/blue]")

    await core.start_run_mode(
        name=task_name,
        description=description,
        continuous=continuous,
        time_limit=time_limit,
        stream_callback_for_cli=stream_callback,
        ui_update_callback_for_cli=update_callback,
    )
    return classify_runmode_completion(
        getattr(core, "current_runmode_status_summary", "")
    )
