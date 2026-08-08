"""Structured output decisions shared by CLI execution surfaces."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from rich.panel import Panel

if TYPE_CHECKING:
    from collections.abc import Callable

    from penguin.cli.run_dispatch import DirectPromptOutcome

__all__ = [
    "RunModeCompletion",
    "classify_runmode_completion",
    "render_direct_prompt",
    "render_runmode_completion",
]


@dataclass(frozen=True)
class RunModeCompletion:
    """A render-neutral RunMode completion classification."""

    kind: str
    message: str


def classify_runmode_completion(status_summary: str | None) -> RunModeCompletion:
    """Translate runtime status truth into a stable presentation outcome."""

    summary = status_summary or ""
    normalized = summary.lower()
    if "clarification" in normalized or "awaiting input" in normalized:
        return RunModeCompletion("waiting_input", summary)
    if "time limit" in normalized or "time_limit" in normalized:
        return RunModeCompletion("time_limit", summary)
    if any(
        phrase in normalized
        for phrase in ("idle", "no ready task", "no ready work remained")
    ):
        return RunModeCompletion("idle", summary)
    if summary:
        return RunModeCompletion("finished", summary)
    return RunModeCompletion("finished", "")


def render_runmode_completion(console: object, completion: RunModeCompletion) -> None:
    """Render a classified completion through a Rich-compatible console."""

    printer = getattr(console, "print")
    if completion.kind == "waiting_input":
        printer(
            "[yellow]Run mode is waiting for clarification/input.[/yellow] "
            f"{completion.message}"
        )
    elif completion.kind == "time_limit":
        printer(
            f"[yellow]Run mode stopped due to time limit.[/yellow] {completion.message}"
        )
    elif completion.kind == "idle":
        printer(
            "[yellow]Run mode stopped because no ready work remained.[/yellow] "
            f"{completion.message}"
        )
    elif completion.message:
        printer(f"[green]Run mode finished.[/green] {completion.message}")
    else:
        printer("[green]Run mode finished.[/green]")


def render_direct_prompt(
    console: Any,
    outcome: DirectPromptOutcome,
    *,
    stdout_print: Callable[[str], None] = print,
) -> None:
    """Render a structured direct-prompt outcome."""

    if outcome.error:
        if outcome.output_format == "text":
            console.print(f"[yellow]{outcome.error}[/yellow]")
        else:
            stdout_print(
                json.dumps(
                    {
                        "error": outcome.error,
                        "assistant_response": "",
                        "action_results": [],
                    }
                )
            )
        return

    response = outcome.response or {}
    if outcome.output_format in {"json", "stream-json"}:
        stdout_print(json.dumps(response, indent=2))
        return

    assistant_response = response.get("assistant_response", "")
    if assistant_response:
        console.print(assistant_response)
    for index, result in enumerate(response.get("action_results", [])):
        if index == 0 and assistant_response:
            console.print("")
        panel_content = (
            "[bold cyan]Action:[/bold cyan] "
            f"{result.get('action', result.get('action_name', 'Unknown'))}\n"
            "[bold cyan]Status:[/bold cyan] "
            f"{result.get('status', 'unknown')}\n"
            "[bold cyan]Result:[/bold cyan]\n"
            f"{result.get('result', result.get('output', 'N/A'))}"
        )
        console.print(
            Panel(
                panel_content,
                title=f"Action Result {index + 1}",
                padding=1,
                border_style="yellow",
            )
        )
