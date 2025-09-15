#!/usr/bin/env python3
"""
Stress: mixed multi-file patch (create + modify) with a deliberate failure at the end.
Verifies atomic rollback semantics: no partial changes applied and new files removed.
"""

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

        # Prepare 300 existing files
        existing = []
        for i in range(300):
            p = root / f"mod/exists_{i:03d}.txt"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"value_{i}\n", encoding="utf-8")
            existing.append(p)

        # Build modifications for existing files
        patches = []
        for i, p in enumerate(existing):
            d = generate_diff_patch(f"value_{i}\n", f"VALUE_{i}\n", str(p))
            patches.append(d)

        # Build 300 new files
        for i in range(300):
            rel = f"new/created_{i:03d}.txt"
            patches.append(build_new_file_patch(rel, f"hello_{i}"))

        # Add a final failing hunk against a non-existent range to force rollback
        bad = "\n".join([
            f"--- a/bad/target.txt",
            f"+++ b/bad/target.txt",
            "@@ -10,1 +10,1 @@",
            "-zzz",
            "+ZZZ",
            "",
        ])
        patches.append(bad)

        multi = "".join(patches)

        res = apply_unified_patch(multi, workspace_path=str(root), backup=True, return_json=False)
        ok = True
        ok &= assert_true(isinstance(res, str) and res.startswith("Error applying diff"), "apply reported error (as expected)")

        # Verify nothing changed: existing content intact, no new files present
        for i, p in enumerate(existing):
            if p.exists():
                content = p.read_text(encoding="utf-8")
                ok &= assert_true(content == f"value_{i}\n", f"existing file unchanged: {p.name}")
            else:
                ok &= assert_true(False, f"existing file missing: {p.name}")

        new_any = list((root / "new").rglob("*.txt"))
        ok &= assert_true(len(new_any) == 0, "no created files remain after rollback")

        if not ok:
            failures += 1

    if failures == 0:
        print("\n🎉 multiedit mixed/rollback stress passed")
        return 0
    else:
        print(f"\n❌ {failures} failure(s) in multiedit mixed stress test")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

