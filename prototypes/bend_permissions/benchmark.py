"""Reproducible CPU experiment; timings include child startup and text output.

Run from the repository root with `python prototypes/bend_permissions/benchmark.py`.
No dependencies, production imports, persistent binaries, or GPU use.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parent


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    """Run a child with captured diagnostics and a finite failure timeout."""
    return subprocess.run(
        [str(arg) for arg in args],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


def reference(depth: int, work: int) -> int:
    """Compute the independent affine recurrence in logarithmic time."""
    mask = 0xFFFFFFFF
    multiplier, increment = 1, 0
    a, c = 1664525, 1013904223
    while work:
        if work & 1:
            multiplier = multiplier * a & mask
            increment = (increment * a + c) & mask
        c = c * (a + 1) & mask
        a = a * a & mask
        work >>= 1
    return (
        sum(
            (multiplier * seed + increment) & mask
            for seed in range(2**depth, 2 ** (depth + 1))
        )
        & mask
    )


def python_loop(depth: int, work: int) -> int:
    """Time actual Python work, not the faster algebraic checksum oracle."""
    total = 0
    for seed in range(2**depth, 2 ** (depth + 1)):
        for _ in range(work):
            seed = (seed * 1664525 + 1013904223) & 0xFFFFFFFF
        total = (total + seed) & 0xFFFFFFFF
    return total


def measure(command: list[str | Path], expected: str) -> float:
    """Validate every observed result before retaining its elapsed time."""
    start = time.perf_counter()
    actual = run(*command).stdout.strip()
    elapsed = time.perf_counter() - start
    if actual != expected:
        raise ValueError(f"checksum mismatch: {actual!r} != {expected!r}")
    return elapsed * 1000


def main() -> None:
    """Build temporary binaries and print raw samples plus summary as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--depth", type=int, default=12)
    parser.add_argument("--work", type=int, default=10000)
    args = parser.parse_args()
    if args.samples < 1 or not 0 <= args.depth <= 18 or not 0 <= args.work <= 1000000:
        parser.error("samples >= 1, depth 0..18, and work 0..1000000 required")
    compiler = (
        os.environ.get("BEND_BIN")
        or shutil.which("bend")
        or str(Path.home() / ".bend/bin/bend")
    )
    result = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "logical_cpus": os.cpu_count(),
        "python": platform.python_version(),
        "bend": run(compiler, "version").stdout.strip(),
        "depth": args.depth,
        "work_per_leaf": args.work,
        "leaves": 2**args.depth,
        "samples": args.samples,
        "timing_scope": "wall ms including process start and stdout; CPU only",
    }
    with tempfile.TemporaryDirectory(prefix="penguin-bend-benchmark-") as directory:
        root = Path(directory)
        for name in ("runner", "scoring"):
            start = time.perf_counter()
            run(compiler, SOURCE / f"{name}.bend", "-o", root / name)
            result[f"{name}_build_ms"] = (time.perf_counter() - start) * 1000
        expected = str(reference(args.depth, args.work))
        result["checksum"] = expected
        jobs = {}
        for threads in sorted({1, min(4, os.cpu_count() or 1), os.cpu_count() or 1}):
            for forks in sorted({0, min(4, args.depth), args.depth}):
                label = f"scoring_threads={threads}_forks={forks}"
                jobs[label] = (
                    [
                        root / "scoring",
                        "--gpu",
                        "off",
                        "--threads",
                        str(threads),
                        str(args.depth),
                        str(forks),
                        str(args.work),
                    ],
                    expected,
                )
        jobs["one_permission_chain"] = (
            [root / "runner", "--threads", "1", "aqd"],
            "deny",
        )
        samples = {label: [] for label in jobs}
        for command, wanted in jobs.values():
            measure(command, wanted)  # One warmup per configuration.
        rng = random.Random(20261014)
        for _ in range(args.samples):
            labels = list(jobs)
            rng.shuffle(labels)
            for label in labels:
                command, wanted = jobs[label]
                samples[label].append(measure(command, wanted))
        result["measurements"] = {
            label: {"median_ms": statistics.median(values), "samples_ms": values}
            for label, values in samples.items()
        }
        # Smaller identical workload keeps the interpreted baseline practical.
        depth, work = 10, 1000
        expected = reference(depth, work)
        start = time.perf_counter()
        actual = python_loop(depth, work)
        result["python_baseline"] = {
            "depth": depth,
            "work_per_leaf": work,
            "elapsed_ms": (time.perf_counter() - start) * 1000,
            "scope": "one in-process Python loop sample; not a Penguin hot path",
        }
        if actual != expected:
            raise ValueError("Python baseline checksum mismatch")
        result["python_baseline"]["bend_one_thread_ms"] = measure(
            [root / "scoring", "--threads", "1", str(depth), "0", str(work)],
            str(expected),
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
