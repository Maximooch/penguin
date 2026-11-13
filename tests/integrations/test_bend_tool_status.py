"""Opt-in Bend model checks against Penguin's ordered-batch status mapping.

Run with PENGUIN_TEST_BEND=1. Model proofs do not verify Python or tool I/O.
"""

from __future__ import annotations

import itertools
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from penguin.tools.runtime import halts_ordered_execution, tool_status_from_output

SOURCE = Path(__file__).resolve().parents[2] / "prototypes" / "bend_tool_status"
RAW_STATUSES = (
    "completed",
    "error",
    "cancelled",
    "pending_approval",
    "requires_approval",
    "running",
)
SYMBOLS = {"completed": "c", "error": "e", "cancelled": "x", "requires_approval": "r"}
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


def test_status_laws(compiler: str) -> None:
    assert "ALL PROOFS CHECK" in run(compiler, SOURCE / "PROOF.bend").stdout


def test_all_model_inputs_against_python(compiler: str) -> None:
    """2 error flags x 6 status words, as dicts and as JSON strings."""
    observed = run(compiler, SOURCE / "status.bend").stdout.split()[0]
    cases = list(itertools.product((False, True), RAW_STATUSES))
    assert len(observed) == 2 * len(cases)
    for index, (has_error, raw) in enumerate(cases):
        payload = {"status": raw, **({"error": "boom"} if has_error else {})}
        for output in (payload, json.dumps(payload)):
            status = tool_status_from_output(output)
            expected = SYMBOLS[status] + str(int(halts_ordered_execution(status)))
            assert observed[2 * index : 2 * index + 2] == expected, (has_error, raw)


@pytest.mark.parametrize(
    "needle,replacement",
    [
        (
            "    case False{} RawPendingApproval{}:\n      RequiresApproval{}",
            "    case False{} RawPendingApproval{}:\n      Completed{}",
        ),
        (
            "    case RequiresApproval{}:\n      True{}",
            "    case RequiresApproval{}:\n      False{}",
        ),
    ],
    ids=["pending-recorded-as-completed", "approval-wait-does-not-halt"],
)
def test_unsafe_mutation_rejected(
    compiler: str, tmp_path: Path, needle: str, replacement: str
) -> None:
    """The laws catch a batch that runs past a call still awaiting approval."""
    for source in SOURCE.glob("*.bend"):
        shutil.copyfile(source, tmp_path / source.name)
    implementation = tmp_path / "status.bend"
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
