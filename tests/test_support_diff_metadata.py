"""Tests for diff-rich edit tool outputs."""

from __future__ import annotations

import shutil
from pathlib import Path

from penguin.tools.core.support import edit_file_with_pattern, replace_lines


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_replace_lines_output_includes_unified_diff(tmp_path: Path) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / tmp_path.name
    try:
        target = workspace / "src" / "main.py"
        _write(target, "line1\nline2\nline3\n")

        result = replace_lines(
            path=str(target),
            start_line=2,
            end_line=2,
            new_content="line2_updated",
            verify=False,
            workspace_path=str(workspace),
        )

        assert "Replaced lines 2-2" in result
        assert "--- a/src/main.py" in result
        assert "+++ b/src/main.py" in result
        assert "-line2" in result
        assert "+line2_updated" in result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_edit_with_pattern_output_uses_workspace_relative_diff_path(
    tmp_path: Path,
) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / tmp_path.name
    try:
        target = workspace / "src" / "settings.py"
        _write(target, "DEBUG = False\n")

        result = edit_file_with_pattern(
            file_path="src/settings.py",
            search_pattern=r"DEBUG = False",
            replacement="DEBUG = True",
            backup=False,
            workspace_path=str(workspace),
        )

        assert "Successfully edited" in result
        assert "--- a/src/settings.py" in result
        assert "+++ b/src/settings.py" in result
        assert "+DEBUG = True" in result
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
