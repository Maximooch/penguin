#!/usr/bin/env python3
"""
Tests for project instructions auto-loading and truncation flag.
Print + exit code style.
"""

import tempfile
from pathlib import Path

from penguin.system.context_window import ContextWindowManager


def assert_true(cond: bool, msg: str) -> bool:
    if cond:
        print(f"✅ {msg}")
        return True
    else:
        print(f"❌ {msg}")
        return False


def main() -> int:
    failures = 0
    # Provide small max_tokens via dummy config-like object
    class _MC:
        max_tokens = 2048

    cwm = ContextWindowManager(model_config=_MC())

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # Case 1: README only
        (root / "README.md").write_text("hello readme", encoding="utf-8")
        content, info = cwm.load_project_instructions(str(root))
        ok = True
        ok &= assert_true("README.md" in info.get("loaded_files", []), "fallback to README when others absent")
        ok &= assert_true("Project Overview" in content, "README section labeled")
        failures += 0 if ok else 1

        # Case 2: AGENTS.md exists, preferred over README
        (root / "AGENTS.md").write_text("agents spec", encoding="utf-8")
        content, info = cwm.load_project_instructions(str(root))
        ok = True
        ok &= assert_true("AGENTS.md" in info.get("loaded_files", []), "AGENTS.md preferred over README")
        ok &= assert_true("Agent Specifications" in content, "AGENTS section labeled")
        failures += 0 if ok else 1

        # Case 3: PENGUIN.md exists, preferred above all
        (root / "PENGUIN.md").write_text("penguin rules", encoding="utf-8")
        content, info = cwm.load_project_instructions(str(root))
        ok = True
        ok &= assert_true("PENGUIN.md" in info.get("loaded_files", []), "PENGUIN.md preferred above all")
        ok &= assert_true("Project Instructions" in content, "PENGUIN section labeled")
        failures += 0 if ok else 1

        # Case 4: truncation
        long_text = "x" * 5000  # exceeds all caps
        (root / "PENGUIN.md").write_text(long_text, encoding="utf-8")
        content, info = cwm.load_project_instructions(str(root))
        ok = True
        ok &= assert_true("(truncated)" in content, "content shows truncation marker")
        ok &= assert_true(info.get("truncated") is True, "debug_info.truncated is True when truncated")
        failures += 0 if ok else 1

    if failures == 0:
        print("\n🎉 Context autoload tests passed")
        return 0
    else:
        print(f"\n❌ {failures} failure(s) in context autoload tests")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
