"""Legacy multiedit compatibility helpers backed by support patch primitives."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class FileEdit:
    file_path: str
    diff_content: str
    backup_path: Optional[str] = None
    applied: bool = False


@dataclass
class MultiEditResult:
    success: bool
    files_edited: List[str]
    files_failed: List[str]
    error_messages: Dict[str, str]
    backup_paths: Dict[str, str]
    rollback_performed: bool = False


class MultiEdit:
    """Atomic multi-file editor with transactional semantics."""

    def __init__(self, workspace_root: str = "."):
        self.workspace_root = Path(workspace_root).resolve()

    def parse_multiedit_block(self, multiedit_content: str) -> List[FileEdit]:
        edits: List[FileEdit] = []
        sections = re.split(
            r"(?:^|\n)(?![+\-@ ])([a-zA-Z0-9_./-]+):\n",
            multiedit_content,
        )

        for index in range(1, len(sections), 2):
            if index + 1 >= len(sections):
                continue
            filename = sections[index].strip()
            diff_content = sections[index + 1].lstrip("\n")
            file_path = self.workspace_root / filename
            edits.append(FileEdit(file_path=str(file_path), diff_content=diff_content))

        return edits

    def create_backups(self, edits: List[FileEdit]) -> bool:
        for edit in edits:
            file_path = Path(edit.file_path)
            if not file_path.exists():
                continue
            backup_path = f"{edit.file_path}.bak"
            counter = 1
            while Path(backup_path).exists():
                backup_path = f"{edit.file_path}.bak.{counter}"
                counter += 1
            try:
                shutil.copy2(edit.file_path, backup_path)
                edit.backup_path = backup_path
            except Exception:
                return False
        return True

    def _build_unified_patch(self, edits: List[FileEdit]) -> str:
        parts: List[str] = []
        for edit in edits:
            rel_path = str(Path(edit.file_path))
            if re.search(r"^--- ", edit.diff_content, flags=re.M):
                parts.append(
                    edit.diff_content
                    if edit.diff_content.endswith("\n")
                    else edit.diff_content + "\n"
                )
                continue
            header = f"--- a/{rel_path}\n+++ b/{rel_path}\n"
            body = (
                edit.diff_content
                if edit.diff_content.endswith("\n")
                else edit.diff_content + "\n"
            )
            parts.append(header + body)
        return "\n".join(parts)

    def rollback_changes(self, edits: List[FileEdit]) -> bool:
        success = True
        for edit in edits:
            if (
                not edit.applied
                or not edit.backup_path
                or not Path(edit.backup_path).exists()
            ):
                continue
            try:
                shutil.copy2(edit.backup_path, edit.file_path)
                edit.applied = False
            except Exception:
                success = False
        return success

    def cleanup_backups(self, edits: List[FileEdit], keep_backups: bool = True) -> None:
        if keep_backups:
            return
        for edit in edits:
            if edit.backup_path and Path(edit.backup_path).exists():
                try:
                    os.remove(edit.backup_path)
                except Exception:
                    pass

    def apply_multiedit(
        self,
        multiedit_content: str,
        dry_run: bool = True,
    ) -> MultiEditResult:
        edits = self.parse_multiedit_block(multiedit_content)

        if not edits:
            return MultiEditResult(
                success=False,
                files_edited=[],
                files_failed=[],
                error_messages={
                    "parse": "No valid file edits found in multiedit block"
                },
                backup_paths={},
            )

        if dry_run:
            from ..core.support import preview_unified_diff

            for edit in edits:
                preview_unified_diff(edit.diff_content)
            return MultiEditResult(
                success=True,
                files_edited=[edit.file_path for edit in edits],
                files_failed=[],
                error_messages={},
                backup_paths={},
            )

        from ..core.support import apply_diff_to_file, apply_unified_patch

        unified_patch = self._build_unified_patch(edits)
        result = apply_unified_patch(
            unified_patch,
            workspace_path=str(self.workspace_root),
            backup=True,
            return_json=True,
        )

        try:
            import json

            parsed = json.loads(result)
            if isinstance(parsed, dict) and parsed.get("status") == "success":
                files_edited = [str(Path(path)) for path in parsed.get("files", [])]
                return MultiEditResult(
                    success=True,
                    files_edited=files_edited,
                    files_failed=[],
                    error_messages={},
                    backup_paths={},
                )
        except Exception:
            applied_paths: List[str] = []
            created_paths: List[str] = []
            for edit in edits:
                target_path = Path(edit.file_path)
                apply_result = apply_diff_to_file(
                    edit.file_path,
                    edit.diff_content,
                    backup=True,
                    workspace_path=None,
                    return_json=False,
                )

                if (
                    isinstance(apply_result, str)
                    and "File does not exist" in apply_result
                ):
                    try:
                        if not target_path.exists():
                            target_path.parent.mkdir(parents=True, exist_ok=True)
                            target_path.touch()
                            created_paths.append(str(target_path))
                        apply_result = apply_diff_to_file(
                            edit.file_path,
                            edit.diff_content,
                            backup=False,
                            workspace_path=None,
                            return_json=False,
                        )
                    except Exception as create_error:
                        apply_result = (
                            f"Error creating file {target_path}: {create_error}"
                        )

                if isinstance(apply_result, str) and apply_result.lower().startswith(
                    "error"
                ):
                    for previous_path in applied_paths:
                        try:
                            previous = Path(previous_path)
                            backup = previous.with_suffix(previous.suffix + ".bak")
                            if backup.exists():
                                shutil.copy2(backup, previous)
                        except Exception:
                            pass
                    for created in created_paths:
                        try:
                            Path(created).unlink()
                        except Exception:
                            pass
                    return MultiEditResult(
                        success=False,
                        files_edited=applied_paths,
                        files_failed=[edit.file_path],
                        error_messages={"apply": apply_result},
                        backup_paths={},
                        rollback_performed=True,
                    )

                applied_paths.append(edit.file_path)

            return MultiEditResult(
                success=True,
                files_edited=applied_paths,
                files_failed=[],
                error_messages={},
                backup_paths={},
            )


_multiedit = MultiEdit()


def apply_multiedit(
    multiedit_content: str,
    dry_run: bool = True,
    workspace_root: str = ".",
) -> MultiEditResult:
    _multiedit.workspace_root = Path(workspace_root).resolve()
    return _multiedit.apply_multiedit(multiedit_content, dry_run)


__all__ = [
    "FileEdit",
    "MultiEdit",
    "MultiEditResult",
    "apply_multiedit",
]
