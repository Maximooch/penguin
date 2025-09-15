#!/usr/bin/env python3
"""
Scale: measure throughput creating 500/1000/2000 files atomically.
Prints timing; exits 0 always unless an apply fails.
Skips 2000 case if PENGUIN_SKIP_STRESS=1.
"""

import os
import time
import tempfile
from pathlib import Path

from penguin.tools.core.support import apply_unified_patch


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


def run_case(n: int) -> bool:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        patches = []
        for i in range(n):
            patches.append(build_new_file_patch(f"bulk/f_{i:05d}.txt", f"x{i}"))
        patch_text = "\n".join(patches)
        t0 = time.time()
        res = apply_unified_patch(patch_text, workspace_path=str(root), backup=True, return_json=True)
        dt = time.time() - t0
        ok = '"status": "success"' in res
        if ok:
            print(f"✅ {n} files in {dt:.2f}s ({n/dt:.1f} files/s)")
        else:
            print(f"❌ Failed to apply {n} file patch: {res}")
        return ok


def main() -> int:
    failures = 0
    for n in (500, 1000):
        if not run_case(n):
            failures += 1
    if os.environ.get("PENGUIN_SKIP_STRESS", "0") not in ("1", "true", "yes"):
        if not run_case(2000):
            failures += 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

