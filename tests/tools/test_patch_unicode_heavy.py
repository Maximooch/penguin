#!/usr/bin/env python3
"""
Unicode/emoji heavy patch application to exercise encoding and diff logic.
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


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        f = root / "uni.txt"
        orig = "naïve café 😊\nΣυναρτήσεις 日本語 línea\n"
        upd = "naïve café 🚀\nΣυναρτήσεις 日本語 línea – long—dash\n"
        f.write_text(orig, encoding="utf-8")
        patch = generate_diff_patch(orig, upd, str(f))
        res = apply_unified_patch(patch, workspace_path=str(root), backup=True, return_json=True)
        ok = '"status": "success"' in res and f.read_text(encoding="utf-8") == upd
        return 0 if assert_true(ok, "unicode/emoji patch applied successfully") else 1


if __name__ == "__main__":
    raise SystemExit(main())

