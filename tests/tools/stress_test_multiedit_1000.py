#!/usr/bin/env python3
"""
Stress test: apply a unified patch creating 1000 small files atomically.
Prints timing; exits 0 on success.
"""

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


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        start = time.time()
        patches = []
        for i in range(1000):
            rel = f"bulk/file_{i:04d}.txt"
            patches.append(build_new_file_patch(rel, f"hello {i}"))
        patch_text = "\n".join(patches)
        res = apply_unified_patch(patch_text, workspace_path=str(root), backup=True, return_json=True)

        ok = '"status": "success"' in res
        dur = time.time() - start
        if ok:
            print(f"✅ Created 1000 files atomically in {dur:.2f}s")
            return 0
        else:
            print(f"❌ Failed to create 1000 files: {res}")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
