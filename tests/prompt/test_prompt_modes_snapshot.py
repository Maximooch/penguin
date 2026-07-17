#!/usr/bin/env python3
"""Snapshot-style checks for the canonical prompt mode renderer."""

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
        from penguin.prompt.profiles import list_available_modes
        from penguin.system_prompt import get_system_prompt
    except Exception as e:
        print(f"❌ Failed to import get_system_prompt: {e}")
        return 1

    modes = list_available_modes()
    results: List[Tuple[str, str]] = []
    for m in modes:
        try:
            prompt = get_system_prompt(m)
            results.append((m, prompt))
        except Exception as e:
            print(f"❌ Failed to build prompt for mode '{m}': {e}")
            failures += 1

    # Core invariants expected in every supported mode.
    core_needles = [
        "## Engineering discipline",
        "## Operating contract",
        "## Tool Invocation Protocol",
        "### finish_task",
    ]

    for mode, prompt in results:
        print(f"\n--- Checking mode: {mode} ---")
        ok = True
        ok &= assert_true(
            all(n in prompt for n in core_needles),
            f"{mode}: core runtime contract present",
        )
        ok &= assert_true(
            "Minimum 5-12 tool calls" not in prompt,
            f"{mode}: no arbitrary tool-call quota",
        )
        failures += 0 if ok else 1

    if failures == 0:
        print("\n🎉 Prompt mode snapshot checks passed")
        return 0
    else:
        print(f"\n❌ {failures} failure(s) in prompt mode snapshot checks")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
