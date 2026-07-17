#!/usr/bin/env python3
"""Stress-build every prompt mode and print timing plus mode summaries."""

import hashlib
import os
import time

from penguin.prompt.profiles import list_available_modes
from penguin.system_prompt import get_system_prompt


def main() -> int:
    modes = list_available_modes()
    invariants = "## Engineering discipline"
    runtime_contract = "## Operating contract"

    # Collect per-mode stats
    stats = {
        m: {"min_len": None, "max_len": 0, "hash": None, "ok": True} for m in modes
    }

    t0 = time.perf_counter()
    iterations = 100
    for i in range(iterations):
        for m in modes:
            p = get_system_prompt(m)

            # Track length stats
            L = len(p)
            if stats[m]["min_len"] is None or L < stats[m]["min_len"]:
                stats[m]["min_len"] = L
            if L > stats[m]["max_len"]:
                stats[m]["max_len"] = L

            # Capture a stable content hash on first iteration
            if i == 0:
                stats[m]["hash"] = hashlib.sha256(
                    p.encode("utf-8", errors="ignore")
                ).hexdigest()[:12]

            # Checks
            if not (invariants in p and runtime_contract in p):
                stats[m]["ok"] = False

    dt = time.perf_counter() - t0

    # Summaries
    print(f"Built prompts for all modes {iterations}x in {dt:.3f}s")
    # Regression threshold (env-configurable)
    baseline_ms = float(os.environ.get("PENGUIN_PROMPT_BUILD_BASELINE_MS", "250"))
    tolerance = float(os.environ.get("PENGUIN_PROMPT_BUILD_TOLERANCE", "1.5"))
    threshold_s = (baseline_ms / 1000.0) * tolerance
    within_threshold = dt <= threshold_s
    status = "OK" if within_threshold else f"SLOW (>{threshold_s:.3f}s)"
    print(
        f"- timing: {dt:.3f}s (baseline {baseline_ms:.0f}ms x tol "
        f"{tolerance} => {threshold_s:.3f}s) {status}"
    )
    for m in modes:
        status = "OK" if stats[m]["ok"] else "FAIL"
        print(
            f"- {m:<18} len[{stats[m]['min_len']}..{stats[m]['max_len']}] "
            f"hash={stats[m]['hash']} {status}"
        )

    ok_all = all(s["ok"] for s in stats.values()) and within_threshold
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
