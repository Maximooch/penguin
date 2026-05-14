from __future__ import annotations

import json
from pathlib import Path

from penguin.tools.editing.contracts import EditOperation, FileEditResult
from penguin.tools.editing.service import EditService


def _bak_files(root: Path) -> list[Path]:
    return list(root.rglob("*.bak"))


def test_edit_file_exact_replacement_success_without_backup(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("# Notes\n\nold value\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))

    result = service.edit_file("notes.md", "old value\n", "new value\n")

    assert isinstance(result, FileEditResult)
    assert result.ok is True
    assert result.files == ["notes.md"]
    assert result.backup_paths == []
    assert target.read_text(encoding="utf-8") == "# Notes\n\nnew value\n"
    assert _bak_files(tmp_path) == []


def test_edit_file_missing_old_string_fails_without_writing(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))

    result = service.edit_file("notes.txt", "missing\n", "replacement\n")

    assert result.ok is False
    assert "not found" in result.error
    assert target.read_text(encoding="utf-8") == "alpha\nbeta\n"
    assert _bak_files(tmp_path) == []


def test_edit_file_ambiguous_old_string_requires_replace_all(
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("same\nsame\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))

    ambiguous = service.edit_file("notes.txt", "same\n", "changed\n")

    assert ambiguous.ok is False
    assert "multiple locations" in ambiguous.error
    assert target.read_text(encoding="utf-8") == "same\nsame\n"

    replace_all = service.edit_file(
        "notes.txt",
        "same\n",
        "changed\n",
        replace_all=True,
    )

    assert replace_all.ok is True
    assert target.read_text(encoding="utf-8") == "changed\nchanged\n"
    assert replace_all.data["matches_replaced"] == 2


def test_apply_patch_contextual_hunk_success_without_backup(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src" / "main.py"
    target.parent.mkdir()
    target.write_text("def value():\n    return 1\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))
    patch = """*** Begin Patch
*** Update File: src/main.py
@@
 def value():
-    return 1
+    return 2
*** End Patch
"""

    result = service.apply_patch(patch)

    assert result.ok is True
    assert result.files == ["src/main.py"]
    assert target.read_text(encoding="utf-8") == "def value():\n    return 2\n"
    payload = json.loads(result.render_legacy_output())
    assert payload["success"] is True
    assert "+    return 2" in payload["diff"]
    assert _bak_files(tmp_path) == []


def test_edit_file_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("old\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))

    result = service.edit_file(str(outside), "old\n", "new\n")

    assert result.ok is False
    assert "escapes workspace root" in result.error
    assert outside.read_text(encoding="utf-8") == "old\n"


def test_apply_patch_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    service = EditService(workspace_root=str(tmp_path))
    outside_name = f"{tmp_path.name}-patch-outside.txt"
    patch = f"""*** Begin Patch
*** Add File: ../{outside_name}
+content
*** End Patch
"""

    result = service.apply_patch(patch)

    assert result.ok is False
    assert "escapes workspace root" in result.error
    assert not (tmp_path.parent / outside_name).exists()


def test_apply_patch_missing_context_fails_atomically(tmp_path: Path) -> None:
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("alpha\n", encoding="utf-8")
    second.write_text("beta\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))
    patch = """*** Begin Patch
*** Update File: a.txt
@@
-alpha
+ALPHA
*** Update File: b.txt
@@
-missing
+BETA
*** End Patch
"""

    result = service.apply_patch(patch)

    assert result.ok is False
    assert "context" in result.error
    assert first.read_text(encoding="utf-8") == "alpha\n"
    assert second.read_text(encoding="utf-8") == "beta\n"
    assert _bak_files(tmp_path) == []


def test_apply_patch_rejects_ambiguous_context(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("x\nsame\nx\nsame\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))
    patch = """*** Begin Patch
*** Update File: notes.txt
@@
-same
+changed
*** End Patch
"""

    result = service.apply_patch(patch)

    assert result.ok is False
    assert "ambiguous" in result.error
    assert target.read_text(encoding="utf-8") == "x\nsame\nx\nsame\n"


def test_legacy_line_coordinate_patch_fails_without_writing(
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))

    result = service.patch_file(
        EditOperation(
            type="replace_lines",
            path="notes.txt",
            payload={"start_line": 2, "end_line": 2, "new_content": "TWO"},
        )
    )

    assert result.ok is False
    assert "deprecated" in result.error
    assert target.read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    assert _bak_files(tmp_path) == []


def test_structured_patch_files_regression_fails_without_stale_coordinates(
    tmp_path: Path,
) -> None:
    target = tmp_path / "doc.md"
    target.write_text("# Doc\n\nalpha\nbeta\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))

    result = service.patch_files(
        apply=True,
        operations=[
            EditOperation(
                type="insert_lines",
                path="doc.md",
                payload={"after_line": 1, "new_content": "inserted"},
            ),
            EditOperation(
                type="replace_lines",
                path="doc.md",
                payload={"start_line": 4, "end_line": 4, "new_content": "BETA"},
            ),
        ],
    )

    assert result.ok is False
    assert "deprecated" in result.error
    assert target.read_text(encoding="utf-8") == "# Doc\n\nalpha\nbeta\n"
    assert _bak_files(tmp_path) == []


def test_markdown_sanity_rejects_broken_fence_before_write(
    tmp_path: Path,
) -> None:
    target = tmp_path / "doc.md"
    target.write_text("# Doc\n\nbody\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))

    result = service.edit_file("doc.md", "body\n", "```python\nprint('x')\n")

    assert result.ok is False
    assert "Markdown sanity check failed" in result.error
    assert target.read_text(encoding="utf-8") == "# Doc\n\nbody\n"


def test_markdown_sanity_rejects_broken_table_before_write(
    tmp_path: Path,
) -> None:
    target = tmp_path / "doc.md"
    target.write_text("# Doc\n\nbody\n", encoding="utf-8")
    service = EditService(workspace_root=str(tmp_path))

    result = service.edit_file("doc.md", "body\n", "|---|---|\n")

    assert result.ok is False
    assert "table separator" in result.error
    assert target.read_text(encoding="utf-8") == "# Doc\n\nbody\n"
