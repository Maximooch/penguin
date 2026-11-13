"""Opt-in Bend/Python contracts for PR 123; run on its base and head."""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from penguin.tools.runtime import image_artifacts_from_action_result

SOURCE = Path(
    os.environ.get(
        "BEND_IMAGE_SOURCE",
        str(Path(__file__).resolve().parents[2] / "prototypes/bend_image_delivery"),
    )
)
pytestmark = pytest.mark.skipif(
    os.environ.get("PENGUIN_TEST_BEND") != "1", reason="opt-in Bend verification"
)


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(arg) for arg in args],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def compiler() -> str:
    return (
        os.environ.get("BEND_BIN")
        or shutil.which("bend")
        or str(Path.home() / ".bend/bin/bend")
    )


@pytest.fixture(scope="module")
def binary(compiler: str, tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("bend-image") / "policy"
    run(compiler, SOURCE / "policy.bend", "-o", target)
    return target


def test_laws(compiler: str) -> None:
    assert "ALL PROOFS CHECK" in run(compiler, SOURCE / "PROOF.bend").stdout


@pytest.mark.parametrize("threads", [1, 4])
def test_image_gate_matches_python(binary: Path, threads: int) -> None:
    observed = run(binary, "--threads", str(threads)).stdout.strip()
    cases = list(itertools.product((False, True), repeat=3))
    assert len(observed) == len(cases)
    mismatches = []
    for (done, error, usable_path), bit in zip(cases, observed):
        for action, status, path in itertools.product(
            ("read_image", "browser_harness_screenshot"),
            ("completed",) if done else ("error", "cancelled", "running", "pending"),
            ("synthetic.png", "  synthetic.png  ") if usable_path else (None, "", "  "),
        ):
            for shape in ("artifact", "fallback"):
                result = {"action": action, "status": status}
                if error:
                    result["error"] = "synthetic failure"
                if shape == "artifact":
                    result["artifact"] = {"type": "image", "image_path": path}
                else:
                    result["image_path"] = path
                artifacts = image_artifacts_from_action_result(result)
                if bool(artifacts) != (bit == "1"):
                    mismatches.append((done, error, usable_path, action, status, shape))
                if artifacts:
                    assert artifacts[0]["image_path"] == "synthetic.png"
    assert not mismatches, mismatches


@pytest.mark.parametrize("mutation", ["ignore_failure", "drop_success"])
def test_mutations_rejected(compiler: str, tmp_path: Path, mutation: str) -> None:
    for source in SOURCE.glob("*.bend"):
        shutil.copyfile(source, tmp_path / source.name)
    implementation = tmp_path / "policy.bend"
    original = implementation.read_text()
    if mutation == "ignore_failure":
        modified = original.replace(
            "case True{} False{} True{}:", "case _ False{} True{}:"
        )
    else:
        modified = original.replace("      True{}", "      False{}", 1)
    assert modified != original
    implementation.write_text(modified)
    result = subprocess.run(
        [compiler, str(tmp_path / "PROOF.bend")],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert "SOME PROOFS FAIL" in result.stdout + result.stderr
