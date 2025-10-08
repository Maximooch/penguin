#!/usr/bin/env python3
"""
Runtime tests for MultiEdit.apply_multiedit.

Validates:
- Creating a new file when the patch targets a missing path.
"""

from pathlib import Path

import pytest

from penguin.tools.multiedit import MultiEdit
from penguin.tools.core.support import generate_diff_patch


def _make_multiedit_block(filename: str, diff: str) -> str:
    """Format a single-file multiedit block."""
    diff_body = diff if diff.endswith("\n") else f"{diff}\n"
    return f"{filename}:\n{diff_body}"


def test_multiedit_creates_new_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure multiedit can create a brand-new file when applying a patch."""
    monkeypatch.setenv("PENGUIN_WORKSPACE", str(tmp_path))
    me = MultiEdit(workspace_root=str(tmp_path))

    diff = generate_diff_patch("", "print('hi')\n", "foo.py")
    block = _make_multiedit_block("foo.py", diff)

    result = me.apply_multiedit(block, dry_run=False)

    assert result.success, f"multiedit failed: {result.error_messages}"

    created = tmp_path / "foo.py"
    assert created.exists(), "expected foo.py to be created"
    assert created.read_text() == "print('hi')\n"
