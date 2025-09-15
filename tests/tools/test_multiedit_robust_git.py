#!/usr/bin/env python3
"""
Robust backend test for apply_unified_patch using git apply --check/--3way.
Skips gracefully if git not available.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from penguin.tools.core.support import generate_diff_patch, apply_unified_patch


def assert_true(cond: bool, msg: str) -> bool:
    if cond:
        print(f"✅ {msg}")
        return True
    else:
        print(f"❌ {msg}")
        return False


def has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return True
    except Exception:
        return False


def main() -> int:
    if not has_git():
        print("⚠️  git not available; skipping robust git test")
        return 0

    failures = 0

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # Init repo
        subprocess.run(["git", "init", str(root)], check=False)
        (root / "a.txt").write_text("A\n", encoding="utf-8")
        (root / "b.txt").write_text("B\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=False)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "init"], check=False)

        d1 = generate_diff_patch("A\n", "AA\n", "a.txt")
        d2 = generate_diff_patch("B\n", "BB\n", "b.txt")
        patch = d1 + d2

        # Enable robust path via env
        os.environ["PENGUIN_PATCH_ROBUST"] = "1"

        res = apply_unified_patch(patch, workspace_path=str(root), backup=True, return_json=True)
        ok = assert_true('"status": "success"' in res, "robust git backend applied patch successfully")
        failures += 0 if ok else 1

    if failures == 0:
        print("\n🎉 Robust git apply tests passed")
        return 0
    else:
        print(f"\n❌ {failures} failure(s) in robust git apply tests")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
