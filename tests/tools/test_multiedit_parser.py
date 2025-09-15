#!/usr/bin/env python3
"""
Parser tests for MultiEdit.parse_multiedit_block.

Covers:
- Start-of-string first header (no leading newline)
- Leading newline before first header

Print + exit code style.
"""

import tempfile
from pathlib import Path

from penguin.tools.multiedit import MultiEdit
from penguin.tools.core.support import generate_diff_patch


def assert_true(cond: bool, msg: str) -> bool:
    if cond:
        print(f"✅ {msg}")
        return True
    else:
        print(f"❌ {msg}")
        return False


def check_block(block: str, root: Path) -> bool:
    me = MultiEdit(workspace_root=str(root))
    edits = me.parse_multiedit_block(block)
    ok = True
    ok &= assert_true(len(edits) == 2, "parsed two file sections")
    if len(edits) == 2:
        ok &= assert_true(edits[0].file_path.endswith(str((root / 'a.txt').resolve())), "first file path resolved")
        ok &= assert_true(edits[1].file_path.endswith(str((root / 'b.txt').resolve())), "second file path resolved")
        ok &= assert_true(edits[0].diff_content.startswith('--- ') and '@@' in edits[0].diff_content, "first diff has headers + hunk")
        ok &= assert_true(edits[1].diff_content.startswith('--- ') and '@@' in edits[1].diff_content, "second diff has headers + hunk")
    return ok


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d1 = generate_diff_patch("x\n", "X\n", "a.txt")
        d2 = generate_diff_patch("y\n", "Y\n", "b.txt")

        # Case 1: header at start-of-string
        block1 = f"a.txt:\n{d1}\n\n" + f"b.txt:\n{d2}\n"
        if not check_block(block1, root):
            failures += 1

        # Case 2: leading newline before first header
        block2 = "\n" + block1
        if not check_block(block2, root):
            failures += 1

    if failures == 0:
        print("\n🎉 multiedit parser tests passed")
        return 0
    else:
        print(f"\n❌ {failures} failure(s) in multiedit parser tests")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

