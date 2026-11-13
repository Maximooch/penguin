"""Opt-in Bend model checks against Penguin's actual retry predicate.

Run with PENGUIN_TEST_BEND=1. Model proofs do not verify Python or transport I/O.
"""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from penguin.llm.contracts import ErrorCategory, LLMError
from penguin.llm.runtime import should_retry_provider_failure

SOURCE = Path(__file__).resolve().parents[2] / "prototypes" / "bend_runtime"
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
def binary(compiler: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    executable = tmp_path_factory.mktemp("bend-retry") / "retry"
    run(compiler, SOURCE / "retry.bend", "-o", executable)
    return executable


def test_retry_laws(compiler: str) -> None:
    assert "ALL PROOFS CHECK" in run(compiler, SOURCE / "PROOF.bend").stdout


@pytest.mark.parametrize("threads", [1, 4])
def test_all_retry_inputs_against_python(binary: Path, threads: int) -> None:
    """32 Boolean cases x response forms x every canonical error category."""
    observed = run(binary, "--threads", str(threads)).stdout.strip()
    cases = list(itertools.product((False, True), repeat=5))
    assert len(observed) == len(cases)
    for (exists, retryable, emitted, tool, blocked), actual in zip(cases, observed):
        responses = (
            ["partial answer", "\n actual response", "🔥"]
            if blocked
            else [None, "", " \n\t", "Error: overloaded", "[Error: disconnected]"]
        )
        for category, response in itertools.product(ErrorCategory, responses):
            error = (
                LLMError(message="synthetic", category=category, retryable=retryable)
                if exists
                else None
            )
            expected = should_retry_provider_failure(
                provider_error=error,
                response=response,
                streamed_assistant_chunk=emitted,
                pending_tool_call=tool,
            )
            assert actual == str(int(expected)), (
                exists,
                retryable,
                emitted,
                tool,
                blocked,
                category,
                response,
            )


def test_emitted_text_mutation_rejected(compiler: str, tmp_path: Path) -> None:
    """Prove the laws catch a retry that might duplicate already-emitted output."""
    for source in SOURCE.glob("*.bend"):
        shutil.copyfile(source, tmp_path / source.name)
    implementation = tmp_path / "retry.bend"
    text = implementation.read_text()
    needle = "case True{} True{} False{} False{} False{}:"
    assert text.count(needle) == 1
    implementation.write_text(
        text.replace(needle, "case True{} True{} _ False{} False{}:")
    )
    result = subprocess.run(
        [compiler, str(tmp_path / "PROOF.bend")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert "SOME PROOFS FAIL" in result.stdout + result.stderr
