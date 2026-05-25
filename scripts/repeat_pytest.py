"""Run a pytest selection repeatedly, stopping at the first failure.

This is a local refactor gate for order/env/cache leakage checks. It is not a
replacement for the default suite; use it on focused clusters before broad
PenguinCore extraction work.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


DEFAULT_SELECTION = [
    "tests/test_core_tool_mapping.py",
    "tests/core_runtime",
    "tests/tools/test_process_runtime.py",
    "tests/llm/test_provider_contract_matrix.py",
    "-q",
]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Repeat a pytest command and stop at the first failure."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of repetitions to run. Defaults to 3.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help=(
            "Optional pytest arguments after '--'. Defaults to the Phase 8 "
            "targeted runtime pack."
        ),
    )
    return parser.parse_args(argv)


def _clean_pytest_args(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args


def main(argv: Sequence[str] | None = None) -> int:
    parsed = _parse_args(sys.argv[1:] if argv is None else argv)
    count = max(parsed.count, 1)
    pytest_args = _clean_pytest_args(list(parsed.pytest_args)) or DEFAULT_SELECTION

    for run_number in range(1, count + 1):
        command = [sys.executable, "-m", "pytest", *pytest_args]
        print(
            f"[repeat-pytest] run {run_number}/{count}: {' '.join(command)}",
            flush=True,
        )
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            print(
                f"[repeat-pytest] failed on run {run_number}/{count} "
                f"with exit code {result.returncode}",
                file=sys.stderr,
            )
            return result.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
