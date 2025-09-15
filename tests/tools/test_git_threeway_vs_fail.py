#!/usr/bin/env python3
"""
Context drift vs 3-way fallback visibility test.

- First apply should fail without three-way
- Raw git attempts are printed (check and 3-way, with and without --index)
- Library robust path is exercised next and printed
"""

import os
import subprocess
import tempfile
import json
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

        # Plain unidiff from difflib
        base_patch = generate_diff_patch("a\nb\nc\n", "a\nB\nc\n", str(target))

        # Drift the file (current becomes 'bb') and STAGE it so index reflects drift
        target.write_text("a\nbb\nc\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", str(target.relative_to(root))], check=False)

        # Robust mode on
        os.environ["PENGUIN_PATCH_ROBUST"] = "1"
        if "PENGUIN_PATCH_THREEWAY" in os.environ:
            del os.environ["PENGUIN_PATCH_THREEWAY"]

        # No-3way attempt should fail
        res_fail = apply_unified_patch(base_patch, workspace_path=str(root), backup=True, return_json=False)
        print(f"[DEBUG] no-3way apply_unified_patch result: {res_fail!r}")
        ok1 = assert_true(isinstance(res_fail, str) and res_fail.startswith("Error applying diff"), "fails without three-way on drift")

        # 3-way on: test raw git and library
        os.environ["PENGUIN_PATCH_THREEWAY"] = "1"

        # Repo-relative version of the plain unidiff
        abs_str = str(target)
        rel_str = str(target.relative_to(root))
        patch_rel = base_patch.replace(f"a/{abs_str}", f"a/{rel_str}").replace(f"b/{abs_str}", f"b/{rel_str}")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tf:
            tf.write(patch_rel)
            tf.flush()
            rel_patch_file = tf.name
        chk = subprocess.run(["git", "-C", str(root), "apply", "--check", rel_patch_file], capture_output=True, text=True)
        print(f"[DEBUG] git apply --check (plain) rc={chk.returncode} stderr={chk.stderr.strip()!r}")
        app3 = subprocess.run(["git", "-C", str(root), "apply", "--3way", rel_patch_file], capture_output=True, text=True)
        print(f"[DEBUG] git apply --3way (plain) rc={app3.returncode} stderr={app3.stderr.strip()!r}")
        app3idx = subprocess.run(["git", "-C", str(root), "apply", "--3way", "--index", rel_patch_file], capture_output=True, text=True)
        print(f"[DEBUG] git apply --3way --index (plain) rc={app3idx.returncode} stderr={app3idx.stderr.strip()!r}")

        # Git-style patch with index headers
        def make_git_patch() -> str:
            orig = target.read_text(encoding="utf-8")
            try:
                target.write_text("a\nB\nc\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(root), "add", str(target.relative_to(root))], check=False)
                proc = subprocess.run(["git", "-C", str(root), "diff", "--cached", "--", str(target.relative_to(root))], capture_output=True, text=True, check=False)
                return proc.stdout
            finally:
                subprocess.run(["git", "-C", str(root), "reset", "--hard", "HEAD"], check=False)
                target.write_text("a\nbb\nc\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(root), "add", str(target.relative_to(root))], check=False)

        git_patch = make_git_patch()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as tf:
            tf.write(git_patch)
            tf.flush()
            rel_git_patch = tf.name
        chk_g = subprocess.run(["git", "-C", str(root), "apply", "--check", rel_git_patch], capture_output=True, text=True)
        print(f"[DEBUG] git apply --check (git) rc={chk_g.returncode} stderr={chk_g.stderr.strip()!r}")
        app3_g = subprocess.run(["git", "-C", str(root), "apply", "--3way", rel_git_patch], capture_output=True, text=True)
        print(f"[DEBUG] git apply --3way (git) rc={app3_g.returncode} stderr={app3_g.stderr.strip()!r}")
        app3idx_g = subprocess.run(["git", "-C", str(root), "apply", "--3way", "--index", rel_git_patch], capture_output=True, text=True)
        print(f"[DEBUG] git apply --3way --index (git) rc={app3idx_g.returncode} stderr={app3idx_g.stderr.strip()!r}")

        # Reset any changes from raw git attempts before library call
        subprocess.run(["git", "-C", str(root), "reset", "--hard", "HEAD"], check=False)
        # Reintroduce drift (and stage) so the repo reflects our intended test state
        target.write_text("a\nbb\nc\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", str(target.relative_to(root))], check=False)

        # Library robust path with plain patch – we now expect a clean failure (rollback) due to conflict
        res_ok_plain = apply_unified_patch(base_patch, workspace_path=str(root), backup=True, return_json=True)
        print(f"[DEBUG] 3way apply_unified_patch (plain) result: {res_ok_plain!r}")
        ok2_plain = False
        try:
            parsed = json.loads(res_ok_plain)
            ok2_plain = isinstance(parsed, dict) and parsed.get("status") == "error"
        except Exception:
            ok2_plain = isinstance(res_ok_plain, str) and res_ok_plain.startswith("Error applying diff")

        # Verify working file content was rolled back/unmodified by the failed apply
        try:
            content_now = target.read_text(encoding="utf-8")
            rolled_back = content_now == "a\nbb\nc\n"
        except Exception:
            rolled_back = False
        print(f"[DEBUG] file content after library attempt: {content_now!r}")

        ok2 = ok2_plain and rolled_back
        ok2 = assert_true(ok2, "clean failure with rollback on three-way conflict")

        if not (ok1 and ok2):
            failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
