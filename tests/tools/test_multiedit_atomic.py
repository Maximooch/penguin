#!/usr/bin/env python3
"""
Atomic multi-file edit tests for the multiedit facade and unified patch backend.
Print + exit style.
"""

import tempfile
from pathlib import Path

from penguin.tools.multiedit import apply_multiedit
from penguin.tools.core.support import generate_diff_patch, apply_unified_patch


def assert_true(cond: bool, msg: str) -> bool:
    if cond:
        print(f"✅ {msg}")
        return True
    else:
        print(f"❌ {msg}")
        return False


def build_new_file_patch(rel_path: str, content: str) -> str:
    lines = content.splitlines()
    body = ["@@ -0,0 +%d @@" % (len(lines))]
    for ln in lines:
        body.append("+" + ln)
    return "\n".join([
        f"--- /dev/null",
        f"+++ b/{rel_path}",
        *body,
        "",
    ])


def main() -> int:
    failures = 0

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # Prepare files
        f1 = root / "a.txt"
        f1.write_text("hello\nworld\n", encoding="utf-8")
        f2 = root / "b.txt"
        f2.write_text("x\ny\n", encoding="utf-8")

        # Build per-file blocks (dry-run)
        d1 = generate_diff_patch("hello\nworld\n", "hello\nPENGUIN\n", "a.txt")
        d2 = generate_diff_patch("x\ny\n", "x\nY\n", "b.txt")
        block = f"a.txt:\n{d1}\n\n" + f"b.txt:\n{d2}\n"

        res = apply_multiedit(block, dry_run=True, workspace_root=str(root))
        ok = True
        ok &= assert_true(res.success, "dry-run multiedit success")
        ok &= assert_true(len(res.files_edited) == 2, "dry-run reports both files")
        failures += 0 if ok else 1

        # Apply successfully
        res2 = apply_multiedit(block, dry_run=False, workspace_root=str(root))
        ok = True
        ok &= assert_true(res2.success, "apply multiedit success")
        ok &= assert_true(f1.read_text(encoding="utf-8").splitlines()[1] == "PENGUIN", "a.txt updated")
        ok &= assert_true(f2.read_text(encoding="utf-8").splitlines()[1] == "Y", "b.txt updated")
        failures += 0 if ok else 1

        # New file creation + rollback on error
        f3_rel = "new/created.txt"
        patch_new = build_new_file_patch(f3_rel, "alpha\nbeta")
        # Invalid hunk for a.txt (force failure)
        bad = "\n".join([
            f"--- a/a.txt",
            f"+++ b/a.txt",
            "@@ -10,1 +10,1 @@",  # out-of-range to trigger mismatch
            "-zzz",
            "+ZZZ",
            "",
        ])
        multi = patch_new + bad
        res3 = apply_unified_patch(multi, workspace_path=str(root), backup=True, return_json=False)
        ok = True
        ok &= assert_true(isinstance(res3, str) and res3.startswith("Error applying diff"), "multi-file failure reported")
        ok &= assert_true(not (root / f3_rel).exists(), "new file rolled back on failure")
        failures += 0 if ok else 1

    if failures == 0:
        print("\n🎉 multiedit atomic tests passed")
        return 0
    else:
        print(f"\n❌ {failures} failure(s) in multiedit atomic tests")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
