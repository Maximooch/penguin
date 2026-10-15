"""Opt-in bounded model/Python comparisons; Bend is not a runtime dependency."""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from penguin.engine import _TOOL_ONLY_STALL_NOTES, Engine, LoopState
from penguin.tools.process_wait import ProcessWaitGuard

SOURCE = Path(__file__).resolve().parents[2] / "prototypes/bend_loop_recovery"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PENGUIN_TEST_BEND") != "1",
        reason="enable native Bend assurance with PENGUIN_TEST_BEND=1",
    ),
]


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    """Retain local compiler diagnostics; do not require network or providers."""
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
def binary(compiler: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    executable = tmp_path_factory.mktemp("bend-loop") / "policy"
    run(compiler, SOURCE / "policy.bend", "-o", executable)
    return executable


def test_laws(compiler: str) -> None:
    assert "ALL PROOFS CHECK" in run(compiler, SOURCE / "PROOF.bend").stdout


@pytest.mark.parametrize("threads", [1, 4])
def test_model_matches_runtime(
    binary: Path,
    threads: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed = run(binary, "--threads", str(threads)).stdout.strip()
    cases = list(itertools.product((False, True), repeat=4))
    assert len(observed) == len(cases) * 2
    now = [0.0]
    monkeypatch.setattr("penguin.tools.process_wait.time.monotonic", lambda: now[0])
    for i, (stalled, attempted, explicit, elapsed) in enumerate(cases):
        for status in _TOOL_ONLY_STALL_NOTES if stalled else (None, "completed"):
            state = LoopState(stall_recovery_attempted=attempted)
            engine = object.__new__(Engine)
            engine._get_loop_state = lambda: state
            conversation = Mock()
            actual = engine._queue_stall_recovery(
                SimpleNamespace(conversation=conversation),
                status,
            )
            assert observed[2 * i] == str(int(actual))
            assert conversation.add_message.call_count == int(actual)
            if actual:
                assert state.stall_recovery_attempted
                assert (
                    "replay mutations"
                    in conversation.add_message.call_args.kwargs["content"]
                )
                assert not engine._queue_stall_recovery(
                    SimpleNamespace(conversation=conversation),
                    status,
                )
                assert conversation.add_message.call_count == 1
        for lifecycle in ("running", "draining"):
            for action in (
                "process",
                "process_poll",
                "process_start",
                "execute_command",
            ):
                guard = ProcessWaitGuard(timeout_seconds=120 if explicit else None)
                result = {
                    "action": action,
                    "status": "completed",
                    "process_status": lifecycle,
                    "process_id": "proc",
                    "next_sequence": 0,
                }
                now[0] = 0.0
                assert guard.check([result]) == (False, None)
                now[0] = 120.0 if elapsed else 119.0
                actual = guard.check([result])
                assert observed[2 * i + 1] == str(int(actual[0]))
                if actual[0]:
                    assert actual[1] == "process_wait_budget_exhausted"
                # Real progress resets only an explicitly supplied deadline.
                result["next_sequence"] = 1
                assert guard.check([result]) == (False, None)


@pytest.mark.parametrize("mutation", ["unlimited_recovery", "implicit_deadline"])
def test_unsafe_mutations_rejected(
    compiler: str,
    tmp_path: Path,
    mutation: str,
) -> None:
    for source in SOURCE.glob("*.bend"):
        shutil.copyfile(source, tmp_path / source.name)
    implementation = tmp_path / "policy.bend"
    text = implementation.read_text()
    old, new = {
        "unlimited_recovery": ("case True{} False{}:", "case True{} _:"),
        "implicit_deadline": ("case True{} True{}:", "case _ True{}:"),
    }[mutation]
    assert text.count(old) == 1
    implementation.write_text(text.replace(old, new))
    result = subprocess.run(
        [compiler, str(tmp_path / "PROOF.bend")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert "SOME PROOFS FAIL" in result.stdout + result.stderr
