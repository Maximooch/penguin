from __future__ import annotations

from pathlib import Path

from penguin.tools.tool_manager import ToolManager


def _dummy_log_error(exc: Exception, context: str = "") -> None:
    del exc, context


def test_create_file_respects_effective_project_root(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    tool_manager = ToolManager(
        config={},
        log_error_func=_dummy_log_error,
        fast_startup=True,
    )
    tool_manager.set_project_root(project_root)
    tool_manager.set_execution_root("project")

    result = tool_manager.execute_tool(
        "create_file",
        {"path": "random_test.py", "content": "print(30)\n"},
        context={
            "directory": str(project_root),
            "project_root": str(project_root),
            "workspace_root": str(project_root),
        },
    )

    created = project_root / "random_test.py"
    assert created.exists()
    assert created.read_text() == "print(30)\n"
    assert "File created successfully" in str(result)
