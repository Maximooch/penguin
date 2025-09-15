#!/usr/bin/env python3
"""
Burst of new-file creations outside workspace under workspace-only policy.
Expect all to be denied with no files created.
"""

import os
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


def build_new_file_patch(abs_path: str, content: str) -> str:
    lines = content.splitlines()
    body = ["@@ -0,0 +%d @@" % (len(lines))]
    for ln in lines:
        body.append("+" + ln)
    return "\n".join([
        f"--- /dev/null",
        f"+++ b/{abs_path}",
        *body,
        "",
    ])


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as workspace:
        ws = Path(workspace)
        # Policy: workspace only
        os.environ["PENGUIN_WRITE_ROOT"] = "workspace"

        # Attempt to create files in an external tmp dir outside workspace
        with tempfile.TemporaryDirectory() as ext:
            ext_root = Path(ext)
            patches = []
            targets = []
            for i in range(10):
                abs_target = str((ext_root / f"ext_{i:02d}.txt").resolve())
                patches.append(build_new_file_patch(abs_target, f"x{i}"))
                targets.append(Path(abs_target))
            multi = "".join(patches)

            res = apply_unified_patch(multi, workspace_path=str(ws), backup=True, return_json=False)
            ok = assert_true(isinstance(res, str) and res.startswith("Error applying diff"), "external new-file creation denied")

            # Ensure none were created
            for tgt in targets:
                ok &= assert_true(not tgt.exists(), f"external target not created: {tgt.name}")
            if not ok:
                failures += 1

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

