#!/usr/bin/env python3
"""
Stress: build prompts for all modes repeatedly; verify invariants and measure timing.
"""

import time

from penguin.system_prompt import get_system_prompt


def assert_true(cond: bool, msg: str) -> bool:
    if cond:
        print(f"✅ {msg}")
        return True
    else:
        print(f"❌ {msg}")
        return False


def main() -> int:
    modes = ["direct", "bench_minimal", "terse", "explain", "review"]
    needed = ["Pre-write existence check", "Execution Persistence (Guarded)"]
    t0 = time.time()
    ok = True
    for _ in range(100):
        for m in modes:
            p = get_system_prompt(m)
            if m == "bench_minimal":
                ok &= assert_true("Continue working until task completion" in p, "bench_minimal persistence phrasing present")
            else:
                ok &= assert_true(all(n in p for n in needed), f"{m} invariants/persistence present")
    dt = time.time() - t0
    print(f"Built prompts for all modes 100x in {dt:.2f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

