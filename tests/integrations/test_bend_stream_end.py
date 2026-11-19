"""Opt-in Bend model checks against Penguin's stream-end classification.

Run with PENGUIN_TEST_BEND=1. Model proofs do not verify Python or provider I/O.
"""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from penguin.llm.contracts import FinishReason
from penguin.llm.stream_end import StreamEnd, classify_stream_end, keeps_tool_calls

SOURCE = Path(__file__).resolve().parents[2] / "prototypes" / "bend_stream_end"
EARLY = (None, FinishReason.LENGTH, FinishReason.CONTENT_FILTER)
SYMBOLS = {
    StreamEnd.CANCELLED: "c",
    StreamEnd.PROVIDER_ERROR: "p",
    StreamEnd.INCOMPLETE: "i",
    StreamEnd.TRUNCATED: "l",
    StreamEnd.FILTERED: "f",
    StreamEnd.TOOL_CALLS: "t",
    StreamEnd.TEXT: "x",
    StreamEnd.EMPTY: "e",
}
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


def test_stream_end_laws(compiler: str) -> None:
    assert "ALL PROOFS CHECK" in run(compiler, SOURCE / "PROOF.bend").stdout


def test_all_model_inputs_against_python(compiler: str) -> None:
    """All 96 inputs: 5 flags x 3 early-stop values."""
    observed = run(compiler, SOURCE / "stream_end.bend").stdout.split()[0]
    flags = (False, True)
    cases = list(itertools.product(flags, flags, flags, EARLY, flags, flags))
    assert len(observed) == 2 * len(cases)
    for index, case in enumerate(cases):
        cancelled, saw_error, saw_terminal, early, pending_tool, has_text = case
        end = classify_stream_end(
            cancelled=cancelled,
            saw_error=saw_error,
            saw_terminal=saw_terminal,
            stopped_early=early,
            pending_tool=pending_tool,
            has_text=has_text,
        )
        expected = SYMBOLS[end] + str(int(keeps_tool_calls(end)))
        assert observed[2 * index : 2 * index + 2] == expected, case


@pytest.mark.parametrize(
    "needle,replacement",
    [
        (
            "    case False{} True{} _ _ _ _:\n      ProviderError{}",
            "    case False{} True{} _ _ _ _:\n      ToolCalls{}",
        ),
        (
            "    case False{} False{} True{} Length{} _ _:\n      Truncated{}",
            "    case False{} False{} True{} Length{} _ _:\n      ToolCalls{}",
        ),
        (
            "    case Incomplete{}:\n      False{}",
            "    case Incomplete{}:\n      True{}",
        ),
    ],
    ids=[
        "provider-error-runs-tool-call",
        "cut-off-output-runs-tool-call",
        "incomplete-stream-keeps-tool-call",
    ],
)
def test_unsafe_mutation_rejected(
    compiler: str, tmp_path: Path, needle: str, replacement: str
) -> None:
    """The laws catch a tool call that survives a failed or cut-off stream."""
    for source in SOURCE.glob("*.bend"):
        shutil.copyfile(source, tmp_path / source.name)
    implementation = tmp_path / "stream_end.bend"
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
