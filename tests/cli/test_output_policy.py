"""Tests for render-neutral CLI output classification."""

import pytest
from types import SimpleNamespace
from unittest.mock import Mock

from penguin.cli.output_policy import classify_runmode_completion, render_direct_prompt
from penguin.cli.run_dispatch import DirectPromptOutcome


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


def test_direct_prompt_json_has_no_rich_decoration() -> None:
    console = SimpleNamespace(print=Mock())
    stdout = Mock()
    outcome = DirectPromptOutcome(
        "json", response={"assistant_response": "hello", "action_results": []}
    )

    render_direct_prompt(console, outcome, stdout_print=stdout)

    console.print.assert_not_called()
    assert '"assistant_response": "hello"' in stdout.call_args.args[0]
