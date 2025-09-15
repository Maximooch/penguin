#!/usr/bin/env python3
"""
Context drift vs 3-way fallback:
- Without three-way: patch fails and rolls back
- With three-way: patch applies successfully
Skips if git unavailable.
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
        print("⚠️  git not available; skipping three-way vs fail test")
        return 0

    failures = 0
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "init", str(root)], check=False)
        target = root / "file.txt"
        target.write_text("a\nb\nc\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=False)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "init"], check=False)

        # Create a patch against base replacing b -> B
        base_patch = generate_diff_patch("a\nb\nc\n", "a\nB\nc\n", str(target))

        # Drift the file content so context mismatches slightly (b -> bb)
        target.write_text("a\nbb\nc\n", encoding="utf-8")

        # Without three-way: expect failure
        os.environ["PENGUIN_PATCH_ROBUST"] = "1"
        if "PENGUIN_PATCH_THREEWAY" in os.environ:
            del os.environ["PENGUIN_PATCH_THREEWAY"]
        res_fail = apply_unified_patch(base_patch, workspace_path=str(root), backup=True, return_json=False)
        ok1 = assert_true(isinstance(res_fail, str) and res_fail.startswith("Error applying diff"), "fails without three-way on drift")

        # With three-way: expect success
        os.environ["PENGUIN_PATCH_THREEWAY"] = "1"
        res_ok = apply_unified_patch(base_patch, workspace_path=str(root), backup=True, return_json=True)
        ok2 = assert_true('"status": "success"' in res_ok, "succeeds with three-way fallback")

        if not (ok1 and ok2):
            failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

