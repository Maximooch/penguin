"""Opt-in Bend model checks against the turn loop's recovery-turn caps.

Run with PENGUIN_TEST_BEND=1. Model proofs do not verify Python or provider I/O.
"""

from __future__ import annotations

import asyncio
import itertools
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from penguin.llm.contracts import FinishReason
from tests.test_engine_task_finish_contract import _ScriptedTaskEngine

SOURCE = Path(__file__).resolve().parents[2] / "prototypes" / "bend_loop_termination"
MALFORMED = '-contract.md","show_line_numbers":true}</read_file>\n\n'
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


@pytest.fixture(scope="module")
def tables(compiler: str) -> tuple[list[int], list[int]]:
    recovery, mixed = run(compiler, SOURCE / "recovery.bend").stdout.split()[:2]
    return (
        [int(cell) for cell in recovery.rstrip(",").split(",")],
        [int(cell) for cell in mixed.rstrip(",").split(",")],
    )


def _turn(kind: str, index: int) -> dict[str, Any]:
    if kind == "L":
        return {
            "assistant_response": "partial, ",
            "action_results": [],
            "finish_reason": FinishReason.LENGTH,
        }
    if kind == "M":
        return {"assistant_response": MALFORMED, "action_results": []}
    return {
        "assistant_response": f"step {index}",
        "action_results": [
            {"action": "read_file", "status": "completed", "result": f"r{index}"}
        ],
    }


def _python_stop_turn(sequence: tuple[str, ...]) -> int:
    """The 1-based turn at which the engine stops, or 0 if it ran out of turns."""
    engine = _ScriptedTaskEngine(
        [_turn(kind, index) for index, kind in enumerate(sequence)]
    )
    result = asyncio.run(engine.run_response("Work", streaming=False))
    return engine.provider_calls if result["status"] == "max_iterations" else 0


def test_loop_termination_laws(compiler: str) -> None:
    assert "ALL PROOFS CHECK" in run(compiler, SOURCE / "PROOF.bend").stdout


def test_every_recovery_sequence_stops_where_python_stops(
    tables: tuple[list[int], list[int]],
) -> None:
    """All 4096 sequences of twelve output-limit or malformed turns."""
    recovery, _mixed = tables
    sequences = list(itertools.product("LM", repeat=12))
    assert len(recovery) == len(sequences)
    assert 0 not in recovery
    for index, sequence in enumerate(sequences):
        assert _python_stop_turn(sequence) == recovery[index], "".join(sequence)


def test_ordinary_turns_reset_like_python(
    tables: tuple[list[int], list[int]],
) -> None:
    """All 729 sequences of six output-limit, malformed or ordinary turns."""
    _recovery, mixed = tables
    sequences = list(itertools.product("LMO", repeat=6))
    assert len(mixed) == len(sequences)
    for index, sequence in enumerate(sequences):
        assert _python_stop_turn(sequence) == mixed[index], "".join(sequence)


@pytest.mark.parametrize(
    "needle,replacement",
    [
        (
            "      cap(gt(1n+rc, rep_cap()), Going{oc, 1n+rc}, at)",
            "      Going{oc, rc}",
        ),
        (
            "      cap(gt(1n+oc, out_cap()), Going{1n+oc, rc}, at)\n"
            "    case BrokenSyntax{}:\n"
            "      cap(gt(1n+rc, rep_cap()), Going{oc, 1n+rc}, at)",
            "      cap(gt(1n+oc, out_cap()), Going{1n+oc, 0n}, at)\n"
            "    case BrokenSyntax{}:\n"
            "      cap(gt(1n+rc, rep_cap()), Going{0n, 1n+rc}, at)",
        ),
    ],
    ids=["uncapped-repair", "each-recovery-clears-the-other"],
)
def test_unsafe_mutation_rejected(
    compiler: str, tmp_path: Path, needle: str, replacement: str
) -> None:
    """The laws catch a recovery turn that can repeat forever."""
    for source in SOURCE.glob("*.bend"):
        shutil.copyfile(source, tmp_path / source.name)
    model = tmp_path / "recovery.bend"
    text = model.read_text()
    assert text.count(needle) == 1
    model.write_text(text.replace(needle, replacement))
    result = subprocess.run(
        [compiler, str(tmp_path / "PROOF.bend")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert "SOME PROOFS FAIL" in result.stdout + result.stderr
