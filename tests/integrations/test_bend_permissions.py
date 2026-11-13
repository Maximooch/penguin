"""Opt-in native Bend/Penguin contracts; no compiler needed by default.

Run with PENGUIN_TEST_BEND=1 pytest -q tests/integrations/test_bend_permissions.py.
BEND_BIN may point to a specific compiler. All builds/mutations use pytest temp dirs.
"""

from __future__ import annotations

import itertools
import os
import random
import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from penguin.security.permission_engine import (
    Operation,
    PermissionEnforcer,
    PermissionResult,
    PolicyEngine,
)

SOURCE = Path(__file__).resolve().parents[2] / "prototypes" / "bend_permissions"
RESULTS = {
    "a": PermissionResult.ALLOW,
    "q": PermissionResult.ASK,
    "d": PermissionResult.DENY,
}
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("PENGUIN_TEST_BEND") != "1",
        reason="native Bend experiments require PENGUIN_TEST_BEND=1",
    ),
]


def run(*args: str | Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a bounded native experiment, retaining stdout and stderr on failure."""
    return subprocess.run(
        [str(arg) for arg in args],
        capture_output=True,
        text=True,
        timeout=120,
        check=check,
    )


@pytest.fixture(autouse=True)
def disable_ambient_yolo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Do not inherit permission bypasses from the developer shell."""
    monkeypatch.delenv("PENGUIN_YOLO", raising=False)


@pytest.fixture(scope="module")
def compiler() -> str:
    """Fail an explicitly requested experiment if its compiler is unavailable."""
    requested = os.environ.get("BEND_BIN")
    candidate = requested or shutil.which("bend") or str(Path.home() / ".bend/bin/bend")
    if not Path(candidate).is_file() and not shutil.which(candidate):
        pytest.fail(f"Bend compiler not found: {candidate}")
    return candidate


@pytest.fixture(scope="module")
def binaries(
    compiler: str, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Path]:
    """Compile each checked-in executable once outside the repository."""
    root = tmp_path_factory.mktemp("bend-native")
    result = {}
    for name in ("runner", "scoring"):
        result[name] = root / name
        run(compiler, SOURCE / f"{name}.bend", "-o", result[name])
    return result


class FixedPolicy(PolicyEngine):
    """Record calls and return a controlled outcome or injected error."""

    def __init__(
        self, name: str, outcome: PermissionResult | Exception, calls: list[str]
    ) -> None:
        super().__init__()
        self.name = name
        self.outcome = outcome
        self.calls = calls

    def check_operation(
        self, op: Operation, resource: str, context: dict | None = None
    ) -> tuple[PermissionResult, str]:
        self.calls.append(self.name)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome, self.name


def enforcer_for(text: str) -> tuple[PermissionEnforcer, list[str]]:
    """Use the real enforcer but isolate audit storage from the experiment."""
    enforcer = PermissionEnforcer()
    enforcer._log_check = Mock()
    calls: list[str] = []
    for index, char in enumerate(text):
        enforcer.add_policy(FixedPolicy(str(index), RESULTS[char], calls))
    return enforcer, calls


def check(enforcer: PermissionEnforcer) -> PermissionResult:
    """Exercise an actual write decision without performing any write."""
    return enforcer.check(Operation.FILESYSTEM_WRITE, "experiment.txt")


def test_laws(compiler: str) -> None:
    assert "ALL PROOFS CHECK" in run(compiler, SOURCE / "PROOF.bend").stdout


@pytest.mark.parametrize("threads", [1, 4])
def test_exhaustive_chains(binaries: dict[str, Path], threads: int) -> None:
    """All 364 chains of length 0..5 agree with Python, including short circuit."""
    cases = [
        "".join(values)
        for size in range(6)
        for values in itertools.product("aqd", repeat=size)
    ]
    output = run(
        binaries["runner"], "--threads", str(threads), *cases
    ).stdout.splitlines()
    assert len(output) == len(cases)
    for text, observed in zip(cases, output):
        enforcer, calls = enforcer_for(text)
        expected = check(enforcer)
        assert observed == expected.value, text
        visited = text.index("d") + 1 if "d" in text else len(text)
        assert calls == [str(i) for i in range(visited)]


@pytest.mark.parametrize("threads", [1, 4])
def test_long_chains(binaries: dict[str, Path], threads: int) -> None:
    rng = random.Random(20261014)
    cases = ["a" * 257, "a" * 256 + "q", "a" * 256 + "d", "d" + "q" * 256]
    cases += ["".join(rng.choices("aqd", k=129)) for _ in range(20)]
    output = run(
        binaries["runner"], "--threads", str(threads), *cases
    ).stdout.splitlines()
    assert output == [check(enforcer_for(text)[0]).value for text in cases]


@pytest.mark.parametrize("text", ["x", "allow", "a?d", "A", "q\nd"])
def test_invalid_boundary_rejected(binaries: dict[str, Path], text: str) -> None:
    result = run(binaries["runner"], text, check=False)
    assert result.returncode == 2
    assert not result.stdout.strip()
    assert "invalid decision" in result.stderr


@pytest.mark.parametrize(
    ("mode", "expected", "visited"),
    [
        ("ordinary", "deny", ["0", "1"]),
        ("disabled_deny", "ask", ["0"]),
        ("disabled_all", "allow", []),
        ("yolo", "allow", []),
        ("allowlist", "allow", []),
        ("exception_only", "allow", ["error"]),
        ("exception_then_ask", "ask", ["error", "0"]),
        ("exception_then_deny", "deny", ["error", "1"]),
        ("priority", "deny", ["1"]),
    ],
)
def test_python_boundary_characterization(
    mode: str, expected: str, visited: list[str]
) -> None:
    """Document behavior excluded from the algebra, not endorse fail-open errors."""
    enforcer, calls = enforcer_for("qd")
    if mode == "disabled_deny":
        enforcer._policies[1].disable()
    elif mode == "disabled_all":
        for policy in enforcer._policies:
            policy.disable()
    elif mode == "yolo":
        enforcer.set_yolo(True)
    elif mode == "allowlist":
        enforcer.add_session_allowlist("filesystem.write:experiment.txt")
    elif mode.startswith("exception"):
        original = enforcer._policies
        enforcer._policies = []
        enforcer.add_policy(FixedPolicy("error", RuntimeError("injected"), calls))
        if mode == "exception_then_ask":
            enforcer.add_policy(original[0])
        if mode == "exception_then_deny":
            enforcer.add_policy(original[1])
    elif mode == "priority":
        deny = enforcer._policies[1]
        enforcer._policies = enforcer._policies[:1]
        deny.priority = 10
        enforcer.add_policy(deny)
    assert check(enforcer).value == expected
    assert calls == visited
    enforcer._log_check.assert_called_once()


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("case Deny{} _:\n      Deny{}", "case Deny{} _:\n      Allow{}"),
        ("case _ Deny{}:\n      Deny{}", "case _ Deny{}:\n      Allow{}"),
        ("case Ask{} _:\n      Ask{}", "case Ask{} _:\n      Allow{}"),
        ("case Allow{} Allow{}:\n      Allow{}", "case Allow{} Allow{}:\n      Ask{}"),
        ("      combine(a, b)", "      a"),
        ("case Leaf{decision}:\n      decision", "case Leaf{decision}:\n      Allow{}"),
    ],
)
def test_proof_rejects_mutants(
    compiler: str, tmp_path: Path, old: str, new: str
) -> None:
    for name in ("permissions.bend", "LAWS.bend", "PROOF.bend"):
        shutil.copyfile(SOURCE / name, tmp_path / name)
    code = tmp_path / "permissions.bend"
    original = code.read_text()
    assert original.count(old) == 1
    code.write_text(original.replace(old, new))
    result = run(compiler, tmp_path / "PROOF.bend", check=False)
    assert result.returncode != 0
    assert "SOME PROOFS FAIL" in result.stdout + result.stderr


def python_score(depth: int, work: int) -> int:
    """Independent fixed-width reference for the synthetic native kernel."""
    total = 0
    for seed in range(2**depth, 2 ** (depth + 1)):
        state = seed
        for _ in range(work):
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        total = (total + state) & 0xFFFFFFFF
    return total


@pytest.mark.parametrize("threads", [1, 4])
@pytest.mark.parametrize(
    ("depth", "forks", "work"),
    [(0, 0, 0), (4, 0, 17), (4, 2, 17), (4, 4, 17), (8, 4, 128)],
)
def test_scoring_checksum(
    binaries: dict[str, Path], threads: int, depth: int, forks: int, work: int
) -> None:
    result = run(
        binaries["scoring"],
        "--threads",
        str(threads),
        str(depth),
        str(forks),
        str(work),
    )
    assert int(result.stdout) == python_score(depth, work)
