"""Tests for render-neutral CLI output classification."""

import pytest

from penguin.cli.output_policy import classify_runmode_completion


@pytest.mark.parametrize(
    ("summary", "kind"),
    [
        ("Awaiting input for clarification", "waiting_input"),
        ("Stopped: time_limit", "time_limit"),
        ("No ready work remained", "idle"),
        ("Completed successfully", "finished"),
        (None, "finished"),
    ],
)
def test_runmode_completion_classification(summary: str | None, kind: str) -> None:
    assert classify_runmode_completion(summary).kind == kind
