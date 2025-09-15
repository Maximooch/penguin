#!/usr/bin/env python3
"""
Shadow worktree test: apply a patch in a shadow branch/worktree and commit.
Skips if git is unavailable.
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
        print("⚠️  git not available; skipping shadow test")
        return 0

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "init", str(root)], check=False)
        (root / "a.txt").write_text("A\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=False)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "init"], check=False)

        d1 = generate_diff_patch("A\n", "AA\n", "a.txt")
        patch_text = d1

        os.environ["PENGUIN_PATCH_ROBUST"] = "1"
        os.environ["PENGUIN_PATCH_SHADOW"] = "1"

        res = apply_unified_patch(patch_text, workspace_path=str(root), backup=True, return_json=True)
        ok = ('"status": "success"' in res) and ('"commit"' in res) and ('"worktree"' in res)
        return 0 if assert_true(ok, "shadow worktree apply returned success with commit metadata") else 1


if __name__ == "__main__":
    raise SystemExit(main())

