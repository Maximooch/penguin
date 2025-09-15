#!/usr/bin/env python3
"""
Snapshot-style checks for prompt modes using print + exit code style.

Validates that:
- Direct/explain/terse/review modes include essential invariants and persistence directive
- Bench_minimal mode is minimal but still contains core rules
"""

from typing import List, Tuple


def assert_true(cond: bool, msg: str) -> bool:
    if cond:
        print(f"✅ {msg}")
        return True
    else:
        print(f"❌ {msg}")
        return False


def main() -> int:
    failures = 0
    try:
        from penguin.system_prompt import get_system_prompt
    except Exception as e:
        print(f"❌ Failed to import get_system_prompt: {e}")
        return 1

    modes = ["direct", "bench_minimal", "terse", "explain", "review"]
    results: List[Tuple[str, str]] = []
    for m in modes:
        try:
            prompt = get_system_prompt(m)
            results.append((m, prompt))
        except Exception as e:
            print(f"❌ Failed to build prompt for mode '{m}': {e}")
            failures += 1

    # Core invariants expected in full modes
    core_needles = [
        "Pre-write existence check",
        "Edits must be safe",
        "Respect permissions",
        "Post-verify touched files only",
        "Avoid destructive ops",
    ]
    persistence_needles = [
        "Execution Persistence (Guarded)",
        "Continue working until the user's task is fully complete.",
    ]

    for mode, prompt in results:
        print(f"\n--- Checking mode: {mode} ---")
        if mode == "bench_minimal":
            ok = True
            ok &= assert_true("You are Penguin, a software engineering agent." in prompt, "bench_minimal header present")
            ok &= assert_true("Continue working until task completion" in prompt, "bench_minimal persistence gist present")
            failures += 0 if ok else 1
            continue

        ok = True
        ok &= assert_true(all(n in prompt for n in core_needles), f"{mode}: essential invariants present")
        ok &= assert_true(all(n in prompt for n in persistence_needles), f"{mode}: persistence directive present")
        failures += 0 if ok else 1

    if failures == 0:
        print("\n🎉 Prompt mode snapshot checks passed")
        return 0
    else:
        print(f"\n❌ {failures} failure(s) in prompt mode snapshot checks")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
