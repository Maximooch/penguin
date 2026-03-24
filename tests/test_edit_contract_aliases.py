from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from penguin.tools.editing.registry import (
    get_edit_tool_public_names,
    get_edit_tool_schema_map,
)
from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionType, parse_action


EDIT_ACTION_TYPES = (
    ActionType.WRITE_FILE,
    ActionType.PATCH_FILE,
    ActionType.PATCH_FILES,
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

    patch_file_schema = next(
        tool for tool in tool_manager.get_tools() if tool["name"] == "patch_file"
    )
    patch_files_schema = next(
        tool for tool in tool_manager.get_tools() if tool["name"] == "patch_files"
    )

    assert "operation" in patch_file_schema["input_schema"]["properties"]
    assert patch_file_schema["input_schema"]["required"] == ["path", "operation"]
    assert "operations" in patch_files_schema["input_schema"]["properties"]


def test_tool_manager_edit_schemas_match_shared_registry() -> None:
    tool_manager = ToolManager(
        config={}, log_error_func=_dummy_log_error, fast_startup=True
    )

    schema_map = {
        tool["name"]: tool
        for tool in tool_manager.get_tools()
        if tool["name"] in get_edit_tool_public_names()
    }

    assert schema_map == get_edit_tool_schema_map()


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


def test_write_file_can_overwrite_existing_file_with_workspace_context(
    tmp_path: Path,
) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_write_overwrite"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "notes.txt"
        target.write_text("old\n", encoding="utf-8")

        tool_manager = ToolManager(
            config={}, log_error_func=_dummy_log_error, fast_startup=True
        )
        result = tool_manager.execute_tool(
            "write_file",
            {"path": "notes.txt", "content": "new\n", "backup": True},
            context={
                "directory": str(workspace),
                "project_root": str(workspace),
                "workspace_root": str(workspace),
            },
        )

        assert isinstance(result, str)
        assert result.startswith("Changes applied to")
        assert target.read_text(encoding="utf-8") == "new\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_patch_file_insert_lines_validation_returns_clear_error(tmp_path: Path) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_insert_validation"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "notes.txt"
        target.write_text("line1\nline2\n", encoding="utf-8")

        tool_manager = ToolManager(
            config={}, log_error_func=_dummy_log_error, fast_startup=True
        )
        result = tool_manager.execute_tool(
            "patch_file",
            {
                "path": "notes.txt",
                "operation": {"type": "insert_lines", "new_content": "inserted"},
            },
            context={
                "directory": str(workspace),
                "project_root": str(workspace),
                "workspace_root": str(workspace),
            },
        )
        assert isinstance(result, str)
        payload = json.loads(result)

        assert (
            payload["error"] == "patch_file insert_lines requires integer 'after_line'"
        )
        assert payload["tool"] == "patch_file"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_patch_files_structured_operations_execute_with_workspace_context(
    tmp_path: Path,
) -> None:
    workspace = (
        Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_patch_files_structured"
    )
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        first = workspace / "a.txt"
        second = workspace / "b.txt"
        first.write_text("hello\nworld\n", encoding="utf-8")
        second.write_text("one\ntwo\n", encoding="utf-8")

        tool_manager = ToolManager(
            config={}, log_error_func=_dummy_log_error, fast_startup=True
        )
        result = tool_manager.execute_tool(
            "patch_files",
            {
                "apply": True,
                "operations": [
                    {
                        "path": "a.txt",
                        "operation": {
                            "type": "replace_lines",
                            "start_line": 2,
                            "end_line": 2,
                            "new_content": "PENGUIN",
                            "verify": False,
                        },
                    },
                    {
                        "path": "b.txt",
                        "operation": {
                            "type": "insert_lines",
                            "after_line": 2,
                            "new_content": "three",
                        },
                    },
                ],
            },
            context={
                "directory": str(workspace),
                "project_root": str(workspace),
                "workspace_root": str(workspace),
            },
        )
        assert isinstance(result, str)
        payload = json.loads(result)

        assert payload["success"] is True
        assert payload["applied"] is True
        assert first.read_text(encoding="utf-8") == "hello\nPENGUIN\n"
        assert second.read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_patch_files_legacy_content_executes_with_workspace_context(
    tmp_path: Path,
) -> None:
    workspace = (
        Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_patch_files_legacy"
    )
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "foo.py"
        target.write_text("print('old')\n", encoding="utf-8")
        diff_content = (
            "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-print('old')\n+print('new')\n"
        )

        tool_manager = ToolManager(
            config={}, log_error_func=_dummy_log_error, fast_startup=True
        )
        result = tool_manager.execute_tool(
            "patch_files",
            {"content": f"foo.py:\n{diff_content}\n", "apply": True},
            context={
                "directory": str(workspace),
                "project_root": str(workspace),
                "workspace_root": str(workspace),
            },
        )
        assert isinstance(result, str)
        payload = json.loads(result)

        assert payload["success"] is True
        assert payload["applied"] is True
        assert target.read_text(encoding="utf-8") == "print('new')\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_legacy_apply_diff_wrapper_routes_through_patch_file(monkeypatch) -> None:
    tool_manager = ToolManager(
        config={}, log_error_func=_dummy_log_error, fast_startup=True
    )
    captured: dict[str, object] = {}

    def _fake_patch_file(tool_input: dict, *, file_root=None):
        captured["tool_input"] = dict(tool_input)
        captured["file_root"] = file_root
        return "ok"

    monkeypatch.setattr(tool_manager, "_execute_patch_file", _fake_patch_file)

    result = tool_manager._execute_apply_diff(
        {
            "file_path": "src/main.py",
            "diff_content": "--- a/src/main.py\n+++ b/src/main.py\n",
            "backup": False,
        },
        file_root="/tmp/workspace",
    )

    assert result == "ok"
    assert captured == {
        "tool_input": {
            "path": "src/main.py",
            "operation": {
                "type": "unified_diff",
                "diff_content": "--- a/src/main.py\n+++ b/src/main.py\n",
            },
            "backup": False,
            "_warnings": [
                "Deprecated patch_file payload: legacy apply_diff wrapper is deprecated; use patch_file instead."
            ],
        },
        "file_root": "/tmp/workspace",
    }


def test_legacy_multiedit_wrapper_routes_through_patch_files(monkeypatch) -> None:
    tool_manager = ToolManager(
        config={}, log_error_func=_dummy_log_error, fast_startup=True
    )
    captured: dict[str, object] = {}

    def _fake_patch_files(tool_input: dict, *, file_root=None):
        captured["tool_input"] = dict(tool_input)
        captured["file_root"] = file_root
        return "ok"

    monkeypatch.setattr(tool_manager, "_execute_patch_files", _fake_patch_files)

    result = tool_manager._execute_multiedit(
        {"content": "a.py:\n@@ -1 +1 @@\n-a\n+b\n", "apply": True},
        file_root="/tmp/workspace",
    )

    assert result == "ok"
    assert captured == {
        "tool_input": {
            "content": "a.py:\n@@ -1 +1 @@\n-a\n+b\n",
            "apply": True,
            "backup": True,
            "_warnings": [
                "Deprecated patch_files payload: legacy multiedit wrapper is deprecated; use patch_files instead."
            ],
        },
        "file_root": "/tmp/workspace",
    }
