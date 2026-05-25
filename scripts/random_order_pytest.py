"""Run a pytest selection in a deterministic shuffled order.

This is a local Phase 8 assault helper for finding order/env/cache leakage
without adding a pytest plugin or changing the default suite gate.
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


DEFAULT_SELECTION = [
    "tests/core_runtime/test_action_mapping.py",
    "tests/tools/test_process_runtime.py",
    "tests/llm/test_provider_reliability_properties.py",
]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect pytest node ids, shuffle them, and run the shuffled order."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="Base random seed. Defaults to 1.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of shuffled runs. Each run increments the seed.",
    )
    parser.add_argument(
        "--max-tests",
        type=int,
        default=0,
        help="Optional cap after shuffling, useful for a quick smoke sample.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help=(
            "Optional pytest selection after '--'. Defaults to a fast Phase 8 "
            "runtime/property pack."
        ),
    )
    return parser.parse_args(argv)


def _clean_pytest_args(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args


def _collect_nodeids(pytest_args: list[str]) -> list[str]:
    command = [sys.executable, "-m", "pytest", "--collect-only", "-q", *pytest_args]
    print(f"[random-order-pytest] collect: {' '.join(command)}", flush=True)
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise SystemExit(result.returncode)

    nodeids = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip() and ".py::" in line
    ]
    if not nodeids:
        print("[random-order-pytest] no tests collected", file=sys.stderr)
        raise SystemExit(5)
    return nodeids


def _shuffled_nodeids(
    nodeids: list[str],
    *,
    seed: int,
    max_tests: int,
) -> list[str]:
    shuffled = list(nodeids)
    random.Random(seed).shuffle(shuffled)
    if max_tests > 0:
        return shuffled[:max_tests]
    return shuffled


def main(argv: Sequence[str] | None = None) -> int:
    parsed = _parse_args(sys.argv[1:] if argv is None else argv)
    pytest_args = _clean_pytest_args(list(parsed.pytest_args)) or DEFAULT_SELECTION
    count = max(parsed.count, 1)
    max_tests = max(parsed.max_tests, 0)
    nodeids = _collect_nodeids(pytest_args)

    for run_index in range(count):
        seed = parsed.seed + run_index
        shuffled = _shuffled_nodeids(nodeids, seed=seed, max_tests=max_tests)
        command = [sys.executable, "-m", "pytest", "-q", *shuffled]
        print(
            "[random-order-pytest] "
            f"run {run_index + 1}/{count}: seed={seed} tests={len(shuffled)}",
            flush=True,
        )
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            print(
                "[random-order-pytest] "
                f"failed with seed={seed} exit_code={result.returncode}",
                file=sys.stderr,
            )
            return result.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
