#!/usr/bin/env python3
"""
Runtime tests for MultiEdit.apply_multiedit.

Validates:
- Creating a new file when the patch targets a missing path.
"""

import json
import shutil
from pathlib import Path

import pytest

from penguin.tools.tool_manager import ToolManager
from penguin.tools.multiedit import FileEdit, MultiEdit
from penguin.tools.core.support import generate_diff_patch


def _make_multiedit_block(filename: str, diff: str) -> str:
    """Format a single-file multiedit block."""
    diff_body = diff if diff.endswith("\n") else f"{diff}\n"
    return f"{filename}:\n{diff_body}"


def _dummy_log_error(exc: Exception, context: str = "") -> None:
    del exc, context


def test_multiedit_creates_new_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_multiedit_rollback_removes_created_file(tmp_path: Path) -> None:
    me = MultiEdit(workspace_root=str(tmp_path))
    target = tmp_path / "created.py"
    edit = FileEdit(file_path=str(target), diff_content="")
    edit.applied = True
    edit.original_existed = False
    target.write_text("new\n", encoding="utf-8")

    assert me.rollback_changes([edit]) is True
    assert not target.exists()


def test_tool_manager_multiedit_apply_returns_deprecation_error(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "foo.py"
        target.write_text("print('old')\n", encoding="utf-8")

        diff = generate_diff_patch("print('old')\n", "print('new')\n", "foo.py")
        block = _make_multiedit_block("foo.py", diff)

        tool_manager = ToolManager(
            config={}, log_error_func=_dummy_log_error, fast_startup=True
        )
        result = tool_manager._execute_multiedit(
            {"content": block, "apply": True}, file_root=str(workspace)
        )
        payload = json.loads(result)

        assert payload["success"] is False
        assert payload["tool"] == "patch_files"
        assert "deprecated" in payload["error"]
        assert payload["files_failed"] == []
        assert payload["error_messages"] == {
            "patch_files": (
                "patch_files is deprecated; use apply_patch for contextual "
                "multi-file patches"
            )
        }
        assert payload["backup_paths"] == {}
        assert target.read_text(encoding="utf-8") == "print('old')\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
