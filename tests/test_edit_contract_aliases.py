from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionType, parse_action


EDIT_ACTION_TYPES = (
    ActionType.ENHANCED_WRITE,
    ActionType.APPLY_DIFF,
    ActionType.MULTIEDIT,
    ActionType.EDIT_WITH_PATTERN,
    ActionType.REPLACE_LINES,
    ActionType.INSERT_LINES,
    ActionType.DELETE_LINES,
)

EDIT_ACTION_NAMES = {action_type.value for action_type in EDIT_ACTION_TYPES}


def _dummy_log_error(exc: Exception, context: str = "") -> None:
    del exc, context


@pytest.mark.parametrize("action_type", EDIT_ACTION_TYPES)
def test_parse_action_detects_current_edit_action_tags(
    action_type: ActionType,
) -> None:
    actions = parse_action(f"<{action_type.value}>payload</{action_type.value}>")

    assert [action.action_type for action in actions] == [action_type]


def test_tool_manager_schema_exposes_current_public_edit_tools() -> None:
    tool_manager = ToolManager(
        config={}, log_error_func=_dummy_log_error, fast_startup=True
    )

    schema_names = {tool["name"] for tool in tool_manager.get_tools()}

    assert {
        "write_file",
        "patch_file",
        "patch_files",
    }.issubset(schema_names)


def test_tool_manager_centralizes_legacy_edit_aliases() -> None:
    tool_manager = ToolManager(
        config={}, log_error_func=_dummy_log_error, fast_startup=True
    )

    aliases = tool_manager.get_tool_aliases()

    assert aliases == {
        "write_to_file": "write_file",
        "enhanced_write": "write_file",
        "apply_diff": "patch_file",
        "edit_with_pattern": "patch_file",
        "replace_lines": "patch_file",
        "insert_lines": "patch_file",
        "delete_lines": "patch_file",
        "multiedit_apply": "patch_files",
        "multiedit": "patch_files",
    }


def test_get_responses_tools_returns_canonical_edit_names_only() -> None:
    tool_manager = ToolManager(
        config={}, log_error_func=_dummy_log_error, fast_startup=True
    )

    names = {
        tool["function"]["name"]
        for tool in tool_manager.get_responses_tools()
        if tool.get("type") == "function"
    }

    assert {"write_file", "patch_file", "patch_files"}.issubset(names)
    assert "write_to_file" not in names
    assert "apply_diff" not in names
    assert "multiedit_apply" not in names


def test_execute_tool_accepts_legacy_write_alias(tmp_path: Path) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_write_alias"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        tool_manager = ToolManager(
            config={}, log_error_func=_dummy_log_error, fast_startup=True
        )

        result = tool_manager.execute_tool(
            "write_to_file",
            {"path": "alias.txt", "content": "hello\n", "backup": True},
            context={
                "directory": str(workspace),
                "project_root": str(workspace),
                "workspace_root": str(workspace),
            },
        )

        assert isinstance(result, str)
        assert (workspace / "alias.txt").read_text(encoding="utf-8") == "hello\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_execute_tool_accepts_legacy_patch_alias(tmp_path: Path) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_patch_alias"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "src" / "main.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("print('old')\n", encoding="utf-8")

        tool_manager = ToolManager(
            config={}, log_error_func=_dummy_log_error, fast_startup=True
        )
        diff_content = (
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -1 +1 @@\n"
            "-print('old')\n"
            "+print('new')\n"
        )

        result = tool_manager.execute_tool(
            "apply_diff",
            {
                "file_path": "src/main.py",
                "diff_content": diff_content,
                "backup": True,
            },
            context={
                "directory": str(workspace),
                "project_root": str(workspace),
                "workspace_root": str(workspace),
            },
        )

        assert isinstance(result, str)
        assert result.startswith("Successfully applied diff")
        assert target.read_text(encoding="utf-8") == "print('new')\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
