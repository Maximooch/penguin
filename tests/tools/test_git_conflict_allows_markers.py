#!/usr/bin/env python3
"""
Verify robust 3-way apply reports structured conflicts and leaves markers.

Flow:
- Init tiny repo with file.txt = a\nb\nc\n
- Create git-style patch (index headers) that changes b->B
- Drift working tree to a\nbb\nc (same line change) and stage it so index reflects drift
- Apply patch via apply_unified_patch with robust + three_way
- Expect JSON { status: "conflict", conflicted: ["file.txt"], message: ... }
- Verify file contains conflict markers
"""

import os
import json
import subprocess
import tempfile
from pathlib import Path

from penguin.tools.core.support import apply_unified_patch


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
        print("⚠️  git not available; skipping conflict test")
        return 0

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        subprocess.run(["git", "init", str(root)], check=False)

        target = root / "file.txt"
        target.write_text("a\nb\nc\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", str(target.relative_to(root))], check=False)
        subprocess.run(["git", "-C", str(root), "commit", "-m", "init"], check=False)

        # Produce git-style patch B change with index headers
        def make_git_patch() -> str:
            orig = target.read_text(encoding="utf-8")
            try:
                target.write_text("a\nB\nc\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(root), "add", str(target.relative_to(root))], check=False)
                proc = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--", str(target.relative_to(root))], capture_output=True, text=True, check=False)
                return proc.stdout
            finally:
                subprocess.run(["git", "-C", str(root), "reset", "--hard", "HEAD"], check=False)
                target.write_text(orig, encoding="utf-8")

        git_patch = make_git_patch()

        # Drift to bb and stage so index reflects drift
        target.write_text("a\nbb\nc\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", str(target.relative_to(root))], check=False)

        # Robust + threeway enabled
        os.environ["PENGUIN_PATCH_ROBUST"] = "1"
        os.environ["PENGUIN_PATCH_THREEWAY"] = "1"

        res = apply_unified_patch(git_patch, workspace_path=str(root), backup=True, return_json=True)
        print(f"[DEBUG] conflict test apply result: {res!r}")
        ok_json = False
        try:
            parsed = json.loads(res)
            ok_json = parsed.get("status") == "conflict" and "file.txt" in (parsed.get("conflicted") or [])
        except Exception:
            ok_json = False
        ok1 = assert_true(ok_json, "structured conflict JSON returned")

        content = target.read_text(encoding="utf-8")
        ok2 = assert_true("<<<<<<<" in content and ">>>>>>>" in content, "conflict markers present in file")

        return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    raise SystemExit(main())

