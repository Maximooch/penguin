from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.security.permission_engine import Operation
from penguin.security.tool_permissions import get_tool_operations
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
)
from penguin.tools.artifact_tools import PublishArtifactTool
from penguin.tools.tool_manager import ToolManager

if TYPE_CHECKING:
    from pathlib import Path


def test_publish_artifact_is_explicit_and_request_root_scoped(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    report = project / "report.txt"
    report.write_text("report", encoding="utf-8")
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    context = ExecutionContext(
        directory=str(project),
        project_root=str(project),
        workspace_root=str(project),
    )

    with execution_context_scope(context):
        published = PublishArtifactTool().execute("report.txt")
        rejected = PublishArtifactTool().execute(str(outside))

    assert published == {
        "result": "Artifact ready for delivery: report.txt",
        "artifact": {
            "type": "file",
            "path": str(report),
            "file_name": "report.txt",
            "mime_type": "text/plain",
        },
    }
    assert rejected == {"error": "artifact path is outside request workspace"}


def test_publish_artifact_rejects_symlinks(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    target = project / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = project / "link.txt"
    link.symlink_to(target)

    with execution_context_scope(ExecutionContext(directory=str(project))):
        result = PublishArtifactTool().execute(str(link))

    assert result == {"error": "artifact path must not be a symlink"}


def test_tool_manager_registers_and_dispatches_publish_artifact(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    report = project / "report.txt"
    report.write_text("report", encoding="utf-8")
    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    manager._permission_enabled = False
    schema = manager.get_available_tool_schemas()["publish_artifact"]

    with execution_context_scope(ExecutionContext(directory=str(project))):
        result = manager.execute_tool(
            "publish_artifact",
            {"path": "report.txt"},
        )

    assert schema["x-penguin-permissions"]["requires_approval"] is True
    assert get_tool_operations("publish_artifact") == [
        Operation.FILESYSTEM_READ,
        Operation.NETWORK_POST,
    ]
    assert result["artifact"]["path"] == str(report)
