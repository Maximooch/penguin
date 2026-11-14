"""Opt-in Bend model checks against Penguin's request lifecycle transitions.

Run with PENGUIN_TEST_BEND=1. Model proofs do not verify Python or provider I/O.
"""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from penguin.llm.contracts import (
    ErrorCategory,
    LLMCallStatus,
    LLMError,
    classify_call_outcome,
    next_request_status,
)
from penguin.llm.contracts import ProviderRequestStatus as S

SOURCE = Path(__file__).resolve().parents[2] / "prototypes" / "bend_request_lifecycle"
ORDER = (
    S.PENDING,
    S.RUNNING,
    S.STREAMING,
    S.DISCONNECTED,
    S.RETRYING,
    S.COMPLETED,
    S.FAILED,
    S.CANCELLED,
)
SYMBOLS = dict(zip(ORDER, "prsdycfx"))
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PENGUIN_TEST_BEND") != "1",
        reason="native Bend experiments require PENGUIN_TEST_BEND=1",
    ),
]


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    """Run a bounded local process and retain compiler diagnostics on error."""
    return subprocess.run(
        [str(arg) for arg in args],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
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


def test_lifecycle_laws(compiler: str) -> None:
    assert "ALL PROOFS CHECK" in run(compiler, SOURCE / "PROOF.bend").stdout


def test_all_transitions_against_python(compiler: str) -> None:
    """All 64 (current, requested) pairs."""
    observed = run(compiler, SOURCE / "lifecycle.bend").stdout.split()[0]
    pairs = list(itertools.product(ORDER, ORDER))
    assert set(ORDER) == set(S)
    assert len(observed) == len(pairs)
    for index, (current, requested) in enumerate(pairs):
        expected = SYMBOLS[next_request_status(current, requested)]
        assert observed[index] == expected, (current, requested)


def test_all_call_outcomes_against_python(compiler: str) -> None:
    """8 lifecycle statuses x no, retryable or fatal error."""
    observed = run(compiler, SOURCE / "outcome.bend").stdout.split()[0]
    errors = (
        None,
        LLMError(message="r", category=ErrorCategory.NETWORK, retryable=True),
        LLMError(message="f", category=ErrorCategory.AUTH, retryable=False),
    )
    symbols = {
        LLMCallStatus.COMPLETED: "c",
        LLMCallStatus.RETRYABLE_ERROR: "r",
        LLMCallStatus.FATAL_ERROR: "f",
        LLMCallStatus.CANCELLED: "x",
    }
    cases = list(itertools.product(ORDER, errors))
    assert len(observed) == len(cases)
    for index, (status, error) in enumerate(cases):
        expected = symbols[classify_call_outcome(lifecycle_status=status, error=error)]
        assert observed[index] == expected, (status, error)


@pytest.mark.parametrize(
    "needle,replacement",
    [
        ("    case Final{}:\n      cur", "    case Final{}:\n      req"),
        (
            "    case Ended{}:\n      pick(is_retrying(req), req, cur)",
            "    case Ended{}:\n      req",
        ),
    ],
    ids=["final-status-changes", "failed-attempt-reopens"],
)
def test_unsafe_mutation_rejected(
    compiler: str, tmp_path: Path, needle: str, replacement: str
) -> None:
    """The laws catch a finished request that is reopened or relabelled."""
    _assert_mutation_rejected(compiler, tmp_path, "lifecycle.bend", needle, replacement)


@pytest.mark.parametrize(
    "needle,replacement",
    [
        (
            "    case L.Cancelled{}:\n      CancelledOut{}",
            "    case L.Cancelled{}:\n      Succeeded{}",
        ),
        (
            "    case True{}:\n      FatalError{}",
            "    case True{}:\n      Succeeded{}",
        ),
    ],
    ids=["cancelled-reported-done", "failed-request-reported-done"],
)
def test_unsafe_outcome_mutation_rejected(
    compiler: str, tmp_path: Path, needle: str, replacement: str
) -> None:
    """The laws catch a failed or cancelled request reported as completed."""
    _assert_mutation_rejected(compiler, tmp_path, "outcome.bend", needle, replacement)


def _assert_mutation_rejected(
    compiler: str, tmp_path: Path, name: str, needle: str, replacement: str
) -> None:
    for source in SOURCE.glob("*.bend"):
        shutil.copyfile(source, tmp_path / source.name)
    implementation = tmp_path / name
    text = implementation.read_text()
    assert text.count(needle) == 1
    implementation.write_text(text.replace(needle, replacement))
    result = subprocess.run(
        [compiler, str(tmp_path / "PROOF.bend")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert "SOME PROOFS FAIL" in result.stdout + result.stderr
