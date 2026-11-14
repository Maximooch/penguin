"""A file left half-written by a failed edit is restored too (SM-56)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from penguin.tools.editing.service import EditService

if TYPE_CHECKING:
    import pytest


def test_file_that_failed_mid_write_is_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_text("a old", encoding="utf-8")
    second.write_text("b old", encoding="utf-8")
    real_write_text = Path.write_text

    def write_text(self: Path, data: str, *args, **kwargs):
        if self == second and data == "b new":
            real_write_text(self, "b ne", *args, **kwargs)  # truncated write
            raise OSError("disk full")
        return real_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write_text)
    service = EditService(workspace_root=str(tmp_path))
    changes = [
        {
            "requested_path": name,
            "resolved_path": str(path),
            "old_content": f"{name[0]} old",
            "new_content": f"{name[0]} new",
            "existed_before": True,
        }
        for name, path in (("a.txt", first), ("b.txt", second))
    ]

    result = service._commit_text_changes(
        changes, tool_name="multiedit", warnings=[], success_message="ok"
    )

    assert "disk full" in str(result)

    assert first.read_text(encoding="utf-8") == "a old"
    assert second.read_text(encoding="utf-8") == "b old"
