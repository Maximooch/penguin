"""Opt-in Bend model checks against the context window's trimming (SM-55).

Run with PENGUIN_TEST_BEND=1. Model proofs do not verify Python; the table
test runs the real ``ContextWindowManager.trim_session`` on every session the
model enumerates and compares what each kept.
"""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from penguin.system.context_window import ContextWindowManager, TokenBudget
from penguin.system.state import Message, MessageCategory, Session

SOURCE = Path(__file__).resolve().parents[2] / "prototypes" / "bend_context_trim"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PENGUIN_TEST_BEND") != "1",
        reason="native Bend experiments require PENGUIN_TEST_BEND=1",
    ),
]

# The model's window, budgets and enumeration order (see trim.bend).
WINDOW = 6
OUTPUT_BUDGET = TokenBudget(min_tokens=1, max_category_tokens=3)
DIALOG_BUDGET = TokenBudget(min_tokens=2, max_category_tokens=4)
SYSTEM_SIZES = (0, 2)
CATEGORY_SHAPES: tuple[tuple[int, ...], ...] = (
    (),
    *((size,) for size in (1, 2, 3)),
    *itertools.product((1, 2, 3), repeat=2),
)


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    """Run a bounded local process and retain compiler diagnostics on error."""
    return subprocess.run(
        [str(arg) for arg in args],
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )


@pytest.fixture(scope="module")
def compiler() -> str:
    candidate = (
        os.environ.get("BEND_BIN")
        or shutil.which("bend")
        or str(Path.home() / ".bend/bin/bend")
    )
    if not Path(candidate).is_file() and not shutil.which(candidate):
        pytest.fail(f"Bend compiler unavailable: {candidate}")
    return candidate


def _kept_counts(system: int, output: tuple[int, ...], dialog: tuple[int, ...]) -> str:
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_window_tokens = WINDOW
    cwm._initialize_token_budgets()
    cwm._budgets[MessageCategory.SYSTEM_OUTPUT] = OUTPUT_BUDGET
    cwm._budgets[MessageCategory.DIALOG] = DIALOG_BUDGET
    session = Session()
    if system:
        session.add_message(
            Message(
                role="system", content="s" * system, category=MessageCategory.SYSTEM
            )
        )
    # Oldest first, matching the model's Two{a, b}.
    for size in output:
        session.add_message(
            Message(
                role="tool", content="o" * size, category=MessageCategory.SYSTEM_OUTPUT
            )
        )
    for size in dialog:
        session.add_message(
            Message(role="user", content="d" * size, category=MessageCategory.DIALOG)
        )

    trimmed = cwm.trim_session(session)

    def kept(category: MessageCategory) -> int:
        return sum(1 for message in trimmed.messages if message.category == category)

    assert kept(MessageCategory.SYSTEM) == (1 if system else 0)
    return f"{kept(MessageCategory.SYSTEM_OUTPUT)}{kept(MessageCategory.DIALOG)}"


def test_python_trimming_matches_the_model_table(compiler: str) -> None:
    model = run(compiler, SOURCE / "trim.bend").stdout.split()[0].rstrip(",").split(",")
    python = [
        _kept_counts(system, output, dialog)
        for system in SYSTEM_SIZES
        for output in CATEGORY_SHAPES
        for dialog in CATEGORY_SHAPES
    ]

    assert len(model) == len(python) == 338
    mismatches = [
        (index, expected, actual)
        for index, (expected, actual) in enumerate(zip(model, python))
        if expected != actual
    ]
    assert mismatches == []


def test_trim_laws_prove_by_evaluation(compiler: str) -> None:
    result = run(compiler, SOURCE / "PROOF.bend")
    assert "FAIL" not in result.stdout + result.stderr
