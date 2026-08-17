"""Structured output decisions shared by CLI execution surfaces."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RunModeCompletion", "classify_runmode_completion"]


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
