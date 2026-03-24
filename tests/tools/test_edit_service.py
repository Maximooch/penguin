from __future__ import annotations

import json
import shutil
from pathlib import Path

from penguin.tools.editing.contracts import EditOperation, FileEditResult
from penguin.tools.editing.service import EditService
from penguin.tools.core.support import generate_diff_patch


def test_edit_service_write_file_returns_structured_result(tmp_path: Path) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_write_service"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        service = EditService(workspace_root=str(workspace))

        result = service.write_file("notes.txt", "hello\n", backup=True)

        assert isinstance(result, FileEditResult)
        assert result.ok is True
        assert result.files == ["notes.txt"]
        assert result.error is None
        assert result.render_legacy_output().startswith("New file created:")
        assert (workspace / "notes.txt").read_text(encoding="utf-8") == "hello\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_edit_service_patch_file_returns_structured_result(tmp_path: Path) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_patch_service"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "src" / "main.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("line1\nline2\nline3\n", encoding="utf-8")

        service = EditService(workspace_root=str(workspace))
        operation = EditOperation(
            type="replace_lines",
            path="src/main.py",
            payload={
                "start_line": 2,
                "end_line": 2,
                "new_content": "line2_updated",
                "verify": False,
            },
        )

        result = service.patch_file(operation)

        assert isinstance(result, FileEditResult)
        assert result.ok is True
        assert result.files == ["src/main.py"]
        assert result.error is None
        assert result.backup_paths == [str(target) + ".bak"]
        assert "Replaced lines 2-2" in result.message
        assert "--- a/src/main.py" in result.render_legacy_output()
        assert target.read_text(encoding="utf-8") == "line1\nline2_updated\nline3\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_edit_service_patch_file_supports_unified_diff(tmp_path: Path) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_diff_service"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        target = workspace / "pkg" / "mod.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("print('old')\n", encoding="utf-8")

        service = EditService(workspace_root=str(workspace))
        diff = generate_diff_patch("print('old')\n", "print('new')\n", "pkg/mod.py")
        operation = EditOperation(
            type="unified_diff",
            path="pkg/mod.py",
            payload={"diff_content": diff},
        )

        result = service.patch_file(operation)

        assert isinstance(result, FileEditResult)
        assert result.ok is True
        assert result.files == ["pkg/mod.py"]
        assert result.error is None
        assert result.backup_paths == [str(target.with_suffix(target.suffix + ".bak"))]
        assert result.render_legacy_output().startswith("Successfully applied diff")
        assert target.read_text(encoding="utf-8") == "print('new')\n"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def test_edit_service_patch_files_returns_structured_result(tmp_path: Path) -> None:
    workspace = Path.cwd() / ".tmp-track-a-tests" / f"{tmp_path.name}_multiedit_service"
    try:
        workspace.mkdir(parents=True, exist_ok=True)
        first = workspace / "a.txt"
        second = workspace / "b.txt"
        first.write_text("hello\nworld\n", encoding="utf-8")
        second.write_text("x\ny\n", encoding="utf-8")

        service = EditService(workspace_root=str(workspace))
        patch_one = generate_diff_patch("hello\nworld\n", "hello\nPENGUIN\n", "a.txt")
        patch_two = generate_diff_patch("x\ny\n", "x\nY\n", "b.txt")

        result = service.patch_files(
            f"a.txt:\n{patch_one}\n\nb.txt:\n{patch_two}\n",
            apply=True,
        )

        assert isinstance(result, FileEditResult)
        assert result.ok is True
        assert result.files == ["a.txt", "b.txt"]
        assert result.error is None
        assert result.data["applied"] is True

        legacy_payload = json.loads(result.render_legacy_output())
        assert legacy_payload["success"] is True
        assert legacy_payload["applied"] is True
        assert str(first.resolve()) in legacy_payload["files_edited"]
        assert str(second.resolve()) in legacy_payload["files_edited"]
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
