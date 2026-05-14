from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.support import generate_diff_patch
from .contracts import EditOperation, FileEditResult

logger = logging.getLogger(__name__)

_PATCH_FILE_OPERATION_TYPES = {
    "exact_replace",
    "apply_patch",
    "unified_diff",
    "replace_lines",
    "insert_lines",
    "delete_lines",
    "regex_replace",
}
_EDIT_SHAPE_MAX_BYTES = 2_000_000


class EditService:
    """Canonical adapter over Penguin's existing edit implementations."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = (
            str(Path(workspace_root).expanduser().resolve()) if workspace_root else None
        )

    def write_file(
        self,
        path: str,
        content: str,
        backup: bool = True,
        warnings: Optional[List[str]] = None,
    ) -> FileEditResult:
        """Write a file using the canonical result contract."""

        operation = EditOperation(
            type="write",
            path=path,
            payload={"content": content},
            backup=backup,
            warnings=list(warnings or []),
        )
        return self.execute(operation)

    def edit_file(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
        warnings: Optional[List[str]] = None,
    ) -> FileEditResult:
        """Replace exact text in one file after matching current contents.

        Args:
            path: File path to edit, resolved inside the workspace root when set.
            old_string: Exact current text that must be present before writing.
            new_string: Replacement text to write in place of ``old_string``.
            replace_all: When true, replace every exact match; otherwise exactly
                one match is required.
            warnings: Parser/runtime warnings to attach to the edit result.

        Returns:
            FileEditResult describing success, failure, changed files, and diff.

        Raises:
            ValueError: If exact_replace validation fails or the path escapes the
                workspace.
            OSError: If reading or writing the target file fails.
        """

        operation = EditOperation(
            type="exact_replace",
            path=path,
            payload={
                "old_string": old_string,
                "new_string": new_string,
                "replace_all": replace_all,
            },
            backup=False,
            warnings=list(warnings or []),
        )
        return self.execute(operation)

    def apply_patch(
        self,
        patch: str,
        *,
        warnings: Optional[List[str]] = None,
    ) -> FileEditResult:
        """Apply a Codex-style contextual patch after validating all hunks.

        Args:
            patch: Codex-style patch text containing add, delete, update, or move
                hunks with surrounding context.
            warnings: Parser/runtime warnings to attach to the edit result.

        Returns:
            FileEditResult describing success, failure, changed files, and diff.

        Raises:
            ValueError: If patch syntax or hunk context validation fails, or if
                any target path escapes the workspace.
            OSError: If reading or writing any touched file fails.
        """

        operation = EditOperation(
            type="apply_patch",
            payload={"patch": patch},
            backup=False,
            warnings=list(warnings or []),
        )
        return self.execute(operation)

    def patch_file(self, operation: EditOperation) -> FileEditResult:
        """Apply a single-file patch/edit operation."""

        if operation.type not in _PATCH_FILE_OPERATION_TYPES:
            raise ValueError(f"Unsupported patch_file operation type: {operation.type}")
        return self.execute(operation)

    def patch_files(
        self,
        content: str = "",
        apply: bool = False,
        operations: Optional[List[EditOperation]] = None,
        backup: bool = True,
        warnings: Optional[List[str]] = None,
    ) -> FileEditResult:
        """Apply a multi-file edit operation."""

        operation = EditOperation(
            type="multifile_patch",
            payload={
                "content": content,
                "apply": apply,
                "operations": operations or [],
            },
            backup=backup,
            warnings=list(warnings or []),
        )
        return self.execute(operation)

    def execute(self, operation: EditOperation) -> FileEditResult:
        """Execute one canonical edit operation."""

        if operation.type == "write":
            return self._execute_write(operation)
        if operation.type == "exact_replace":
            return self._execute_exact_replace(operation)
        if operation.type == "apply_patch":
            return self._execute_context_patch(operation)
        if operation.type == "multifile_patch":
            return self._execute_multifile_patch(operation)
        if operation.type == "unified_diff":
            return self._execute_unified_diff(operation)
        if operation.type == "replace_lines":
            return self._execute_replace_lines(operation)
        if operation.type == "insert_lines":
            return self._execute_insert_lines(operation)
        if operation.type == "delete_lines":
            return self._execute_delete_lines(operation)
        if operation.type == "regex_replace":
            return self._execute_regex_replace(operation)
        raise ValueError(f"Unsupported edit operation type: {operation.type}")

    def _execute_write(self, operation: EditOperation) -> FileEditResult:
        try:
            resolved_path = self._resolve_target_path(operation.path)
        except ValueError as exc:
            return self._failure_result(
                "write_file",
                str(exc),
                requested_paths=[operation.path],
                warnings=operation.warnings,
            )
        content = str(operation.payload.get("content", ""))
        return self._write_full_content(
            requested_path=operation.path,
            resolved_path=resolved_path,
            new_content=content,
            tool_name="write_file",
            warnings=operation.warnings,
            success_message_prefix="Wrote",
        )

    def _execute_exact_replace(self, operation: EditOperation) -> FileEditResult:
        try:
            resolved_path = self._resolve_target_path(operation.path)
        except ValueError as exc:
            return self._failure_result(
                "edit_file",
                str(exc),
                requested_paths=[operation.path],
                warnings=operation.warnings,
            )
        old_string = operation.payload.get("old_string")
        new_string = operation.payload.get("new_string")
        replace_all = bool(operation.payload.get("replace_all", False))

        if not isinstance(old_string, str) or old_string == "":
            return self._failure_result(
                "edit_file",
                "edit_file requires a non-empty old_string",
                requested_paths=[operation.path],
                warnings=operation.warnings,
            )
        if not isinstance(new_string, str):
            return self._failure_result(
                "edit_file",
                "edit_file requires new_string",
                requested_paths=[operation.path],
                warnings=operation.warnings,
            )
        if old_string == new_string:
            return self._failure_result(
                "edit_file",
                "edit_file old_string and new_string are identical",
                requested_paths=[operation.path],
                warnings=operation.warnings,
            )

        try:
            original = self._read_required_text(resolved_path)
        except ValueError as exc:
            return self._failure_result(
                "edit_file",
                str(exc),
                requested_paths=[operation.path],
                warnings=operation.warnings,
            )

        occurrences = original.count(old_string)
        if occurrences == 0:
            return self._failure_result(
                "edit_file",
                "edit_file old_string was not found in current file contents",
                requested_paths=[operation.path],
                warnings=operation.warnings,
            )
        if occurrences > 1 and not replace_all:
            return self._failure_result(
                "edit_file",
                "edit_file old_string matched multiple locations; "
                "set replace_all=true or provide more context",
                requested_paths=[operation.path],
                warnings=operation.warnings,
                diagnostics={
                    self._display_path(operation.path, resolved_path): [
                        {"matches": occurrences}
                    ]
                },
            )

        if replace_all:
            new_content = original.replace(old_string, new_string)
        else:
            new_content = original.replace(old_string, new_string, 1)

        display_path = self._display_path(operation.path, resolved_path)
        return self._commit_text_changes(
            [
                {
                    "requested_path": operation.path,
                    "resolved_path": resolved_path,
                    "old_content": original,
                    "new_content": new_content,
                    "existed_before": True,
                }
            ],
            tool_name="edit_file",
            warnings=operation.warnings,
            success_message=(
                f"Edited {display_path} with exact replacement"
            ),
            data={
                "replace_all": replace_all,
                "matches_replaced": occurrences if replace_all else 1,
            },
        )

    def _execute_context_patch(self, operation: EditOperation) -> FileEditResult:
        patch_text = operation.payload.get("patch")
        if not isinstance(patch_text, str) or not patch_text.strip():
            return self._failure_result(
                "apply_patch",
                "apply_patch requires non-empty patch text",
                warnings=operation.warnings,
            )

        try:
            planned_changes = self._plan_context_patch(patch_text)
        except ValueError as exc:
            return self._failure_result(
                "apply_patch",
                str(exc),
                warnings=operation.warnings,
            )

        return self._commit_text_changes(
            planned_changes,
            tool_name="apply_patch",
            warnings=operation.warnings,
            success_message=f"Applied patch to {len(planned_changes)} file(s)",
            data={"patch_chars": len(patch_text)},
        )

    def _execute_unified_diff(self, operation: EditOperation) -> FileEditResult:
        return self._deprecated_edit_result(
            operation,
            "unified_diff is deprecated; use apply_patch with Codex-style "
            "contextual hunks",
        )

    def _execute_replace_lines(self, operation: EditOperation) -> FileEditResult:
        return self._deprecated_edit_result(
            operation,
            "replace_lines is deprecated because line coordinates go stale; "
            "use edit_file or apply_patch",
        )

    def _execute_insert_lines(self, operation: EditOperation) -> FileEditResult:
        return self._deprecated_edit_result(
            operation,
            "insert_lines is deprecated because line coordinates go stale; "
            "use edit_file or apply_patch",
        )

    def _execute_delete_lines(self, operation: EditOperation) -> FileEditResult:
        return self._deprecated_edit_result(
            operation,
            "delete_lines is deprecated because line coordinates go stale; "
            "use edit_file or apply_patch",
        )

    def _execute_regex_replace(self, operation: EditOperation) -> FileEditResult:
        return self._deprecated_edit_result(
            operation,
            "regex_replace is deprecated; use edit_file with exact "
            "old_string/new_string or apply_patch",
        )

    def _execute_multifile_patch(self, operation: EditOperation) -> FileEditResult:
        return self._failure_result(
            "patch_files",
            "patch_files is deprecated; use apply_patch for contextual "
            "multi-file patches",
            requested_paths=[
                op.path
                for op in operation.payload.get("operations", [])
                if isinstance(op, EditOperation)
            ],
            warnings=operation.warnings,
        )

    def _write_full_content(
        self,
        *,
        requested_path: str,
        resolved_path: Path,
        new_content: str,
        tool_name: str,
        warnings: List[str],
        success_message_prefix: str,
    ) -> FileEditResult:
        if resolved_path.exists() and not resolved_path.is_file():
            return self._failure_result(
                tool_name,
                f"{requested_path or resolved_path} is not a file",
                requested_paths=[requested_path],
                warnings=warnings,
            )

        old_content = (
            resolved_path.read_text(encoding="utf-8")
            if resolved_path.exists()
            else ""
        )
        display_path = self._display_path(requested_path, resolved_path)
        action = "created" if not resolved_path.exists() else "updated"
        return self._commit_text_changes(
            [
                {
                    "requested_path": requested_path,
                    "resolved_path": resolved_path,
                    "old_content": old_content,
                    "new_content": new_content,
                    "existed_before": resolved_path.exists(),
                }
            ],
            tool_name=tool_name,
            warnings=warnings,
            success_message=f"{success_message_prefix} {display_path} ({action})",
        )

    def _deprecated_edit_result(
        self, operation: EditOperation, message: str
    ) -> FileEditResult:
        warnings = self._unique_strings([*operation.warnings, message])
        return self._failure_result(
            operation.type,
            message,
            requested_paths=[operation.path],
            warnings=warnings,
        )

    def _read_required_text(self, resolved_path: Path) -> str:
        if not resolved_path.exists():
            raise ValueError(f"{resolved_path} does not exist")
        if not resolved_path.is_file():
            raise ValueError(f"{resolved_path} is not a file")
        return resolved_path.read_text(encoding="utf-8")

    def _commit_text_changes(
        self,
        changes: List[Dict[str, Any]],
        *,
        tool_name: str,
        warnings: List[str],
        success_message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> FileEditResult:
        if not changes:
            return self._failure_result(
                tool_name,
                f"{tool_name} produced no file changes",
                warnings=warnings,
            )

        markdown_errors: List[str] = []
        for change in changes:
            new_content = change.get("new_content")
            if not isinstance(new_content, str):
                continue
            markdown_errors.extend(
                self._markdown_sanity_errors(
                    Path(change["resolved_path"]),
                    self._display_path(
                        str(change.get("requested_path", "")),
                        Path(change["resolved_path"]),
                    ),
                    new_content,
                )
            )
        if markdown_errors:
            return self._failure_result(
                tool_name,
                "Markdown sanity check failed: " + "; ".join(markdown_errors),
                requested_paths=[
                    str(change.get("requested_path", "")) for change in changes
                ],
                warnings=warnings,
            )

        display_files: List[str] = []
        resolved_files: List[str] = []
        diffs: List[str] = []
        snapshots: List[Dict[str, Any]] = []
        started = time.perf_counter()

        for change in changes:
            requested_path = str(change.get("requested_path", ""))
            resolved_path = Path(change["resolved_path"])
            old_content = str(change.get("old_content", ""))
            new_content = change.get("new_content")
            display_path = self._display_path(requested_path, resolved_path)
            display_files.append(display_path)
            resolved_files.append(str(resolved_path))
            diff_new_content = new_content if isinstance(new_content, str) else ""
            diff = generate_diff_patch(old_content, diff_new_content, display_path)
            if diff:
                diffs.append(diff)
            snapshots.append(
                {
                    "resolved_path": resolved_path,
                    "old_content": old_content,
                    "existed_before": bool(change.get("existed_before", False)),
                }
            )

        logger.info(
            "edit.safe.commit.start tool=%s files=%s warnings=%s",
            tool_name,
            display_files,
            warnings,
        )
        written: List[Dict[str, Any]] = []
        try:
            for change, snapshot in zip(changes, snapshots):
                resolved_path = Path(change["resolved_path"])
                new_content = change.get("new_content")
                resolved_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(new_content, str):
                    resolved_path.write_text(new_content, encoding="utf-8")
                else:
                    resolved_path.unlink()
                written.append(snapshot)
        except Exception as exc:
            for snapshot in reversed(written):
                path = Path(snapshot["resolved_path"])
                try:
                    if snapshot["existed_before"]:
                        path.write_text(str(snapshot["old_content"]), encoding="utf-8")
                    elif path.exists():
                        path.unlink()
                except Exception:
                    logger.exception("Failed to rollback safe edit for %s", path)
            return self._failure_result(
                tool_name,
                f"{tool_name} failed while writing files: {exc}",
                requested_paths=display_files,
                warnings=warnings,
            )

        after_shapes = {
            display: self._safe_file_shape(Path(resolved))
            for display, resolved in zip(display_files, resolved_files)
        }
        diff_text = "\n".join(diffs)
        legacy_payload = {
            "success": True,
            "tool": tool_name,
            "files": display_files,
            "files_edited": display_files,
            "files_failed": [],
            "backup_paths": {},
            "warnings": self._unique_strings(warnings),
            "diff": diff_text,
        }
        result_data = {
            "legacy_output": json.dumps(legacy_payload),
            "resolved_files": resolved_files,
            "after_shapes": after_shapes,
            "duration_ms": (time.perf_counter() - started) * 1000,
        }
        result_data.update(data or {})
        logger.info(
            "edit.safe.commit.done tool=%s files=%s duration_ms=%.2f",
            tool_name,
            display_files,
            result_data["duration_ms"],
        )
        return FileEditResult(
            ok=True,
            files=display_files,
            message=success_message,
            backup_paths=[],
            warnings=self._unique_strings(warnings),
            data=result_data,
        )

    def _failure_result(
        self,
        tool_name: str,
        message: str,
        *,
        requested_paths: Optional[List[str]] = None,
        warnings: Optional[List[str]] = None,
        diagnostics: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> FileEditResult:
        files = self._normalize_paths(requested_paths or [])
        unique_warnings = self._unique_strings(warnings or [])
        legacy_payload = {
            "success": False,
            "tool": tool_name,
            "files": files,
            "files_edited": [],
            "files_failed": files,
            "error": message,
            "error_messages": {path or tool_name: message for path in files}
            or {tool_name: message},
            "backup_paths": {},
            "warnings": unique_warnings,
        }
        return FileEditResult(
            ok=False,
            files=files,
            message=message,
            diagnostics=diagnostics or {},
            backup_paths=[],
            warnings=unique_warnings,
            error=message,
            data={"legacy_output": json.dumps(legacy_payload)},
        )

    def _markdown_sanity_errors(
        self, resolved_path: Path, display_path: str, content: str
    ) -> List[str]:
        if resolved_path.suffix.lower() not in {".md", ".mdx"}:
            return []

        errors: List[str] = []
        lines = content.splitlines()
        active_fence: Optional[tuple[str, int, int]] = None
        for line_number, line in enumerate(lines, start=1):
            match = re.match(r"^\s*(```+|~~~+)", line)
            if not match:
                continue
            marker = match.group(1)
            marker_char = marker[0]
            marker_len = len(marker)
            if active_fence is None:
                active_fence = (marker_char, marker_len, line_number)
            elif marker_char == active_fence[0] and marker_len >= active_fence[1]:
                active_fence = None
        if active_fence is not None:
            errors.append(
                f"{display_path} has an unclosed fenced code block opened "
                f"on line {active_fence[2]}"
            )

        previous_heading: Optional[str] = None
        previous_heading_line = 0
        nonblank_since_heading = 0
        for line_number, line in enumerate(lines, start=1):
            heading_match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
            if heading_match:
                heading_text = re.sub(r"\s+", " ", heading_match.group(2).strip())
                heading_key = f"{len(heading_match.group(1))}:{heading_text.lower()}"
                if (
                    previous_heading == heading_key
                    and nonblank_since_heading <= 2
                ):
                    errors.append(
                        f"{display_path} has duplicate nearby heading "
                        f"'{heading_text}' on lines {previous_heading_line} "
                        f"and {line_number}"
                    )
                previous_heading = heading_key
                previous_heading_line = line_number
                nonblank_since_heading = 0
            elif line.strip():
                nonblank_since_heading += 1

        for line_number, line in enumerate(lines, start=1):
            if not self._is_markdown_table_separator(line):
                continue
            previous_line = self._nearest_nonblank_line(lines, line_number - 2, -1)
            next_line = self._nearest_nonblank_line(lines, line_number, 1)
            if previous_line is None or "|" not in previous_line:
                errors.append(
                    f"{display_path} has a table separator without a header "
                    f"near line {line_number}"
                )
            if next_line is None or "|" not in next_line:
                errors.append(
                    f"{display_path} has a table separator without rows "
                    f"near line {line_number}"
                )
        return errors

    def _is_markdown_table_separator(self, line: str) -> bool:
        stripped = line.strip()
        if "|" not in stripped:
            return False
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            return False
        return all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)

    def _nearest_nonblank_line(
        self, lines: List[str], start_index: int, direction: int
    ) -> Optional[str]:
        index = start_index
        while 0 <= index < len(lines):
            if lines[index].strip():
                return lines[index]
            index += direction
        return None

    def _plan_context_patch(self, patch_text: str) -> List[Dict[str, Any]]:
        actions = self._parse_context_patch(patch_text)
        originals: Dict[Path, Dict[str, Any]] = {}
        current_contents: Dict[Path, Optional[str]] = {}
        requested_paths: Dict[Path, str] = {}

        for action in actions:
            kind = action["kind"]
            path = self._resolve_target_path(str(action["path"]))
            requested_path = str(action["path"])
            requested_paths.setdefault(path, requested_path)

            if path not in originals:
                existed = path.exists()
                old_content = self._read_required_text(path) if existed else ""
                originals[path] = {
                    "old_content": old_content,
                    "existed_before": existed,
                }
                current_contents[path] = old_content if existed else None

            if kind == "add":
                if current_contents.get(path) is not None:
                    raise ValueError(
                        f"Add File target already exists: {requested_path}"
                    )
                current_contents[path] = "".join(action["lines"])
                continue

            if kind == "delete":
                if current_contents.get(path) is None:
                    raise ValueError(
                        f"Delete File target does not exist: {requested_path}"
                    )
                current_contents[path] = None
                continue

            if kind != "update":
                raise ValueError(f"Unsupported patch action: {kind}")
            current_content = current_contents.get(path)
            if current_content is None:
                raise ValueError(f"Update File target does not exist: {requested_path}")
            updated_content = self._apply_update_hunks(
                current_content,
                action["hunks"],
                requested_path,
            )
            move_to = action.get("move_to")
            if isinstance(move_to, str) and move_to.strip():
                target_path = self._resolve_target_path(move_to)
                requested_paths.setdefault(target_path, move_to)
                if target_path not in originals:
                    existed = target_path.exists()
                    old_content = (
                        self._read_required_text(target_path) if existed else ""
                    )
                    originals[target_path] = {
                        "old_content": old_content,
                        "existed_before": existed,
                    }
                    current_contents[target_path] = old_content if existed else None
                if current_contents.get(target_path) is not None:
                    raise ValueError(f"Move target already exists: {move_to}")
                current_contents[path] = None
                current_contents[target_path] = updated_content
            else:
                current_contents[path] = updated_content

        changes: List[Dict[str, Any]] = []
        for path, original in originals.items():
            new_content = current_contents.get(path)
            old_content = str(original["old_content"])
            if new_content == old_content:
                continue
            changes.append(
                {
                    "requested_path": requested_paths.get(path, str(path)),
                    "resolved_path": path,
                    "old_content": old_content,
                    "new_content": new_content,
                    "existed_before": bool(original["existed_before"]),
                }
            )
        if not changes:
            raise ValueError("apply_patch produced no file changes")
        return changes

    def _parse_context_patch(self, patch_text: str) -> List[Dict[str, Any]]:
        lines = patch_text.splitlines(keepends=True)
        if len(lines) < 2:
            raise ValueError("apply_patch requires Begin Patch and End Patch markers")
        if lines[0].rstrip("\r\n") != "*** Begin Patch":
            raise ValueError("apply_patch must start with *** Begin Patch")
        if lines[-1].rstrip("\r\n") != "*** End Patch":
            raise ValueError("apply_patch must end with *** End Patch")

        actions: List[Dict[str, Any]] = []
        index = 1
        while index < len(lines) - 1:
            header = lines[index].rstrip("\r\n")
            if not header:
                index += 1
                continue
            if header.startswith("*** Add File: "):
                path = self._parse_patch_path(header, "*** Add File: ")
                index += 1
                added_lines: List[str] = []
                while index < len(lines) - 1 and not self._is_context_patch_header(
                    lines[index]
                ):
                    raw_line = lines[index]
                    if not raw_line.startswith("+"):
                        raise ValueError(
                            f"Add File {path} contains a line without '+' prefix"
                        )
                    added_lines.append(raw_line[1:])
                    index += 1
                actions.append({"kind": "add", "path": path, "lines": added_lines})
                continue
            if header.startswith("*** Delete File: "):
                path = self._parse_patch_path(header, "*** Delete File: ")
                actions.append({"kind": "delete", "path": path})
                index += 1
                continue
            if header.startswith("*** Update File: "):
                path = self._parse_patch_path(header, "*** Update File: ")
                index += 1
                move_to: Optional[str] = None
                if index < len(lines) - 1:
                    move_header = lines[index].rstrip("\r\n")
                    if move_header.startswith("*** Move to: "):
                        move_to = self._parse_patch_path(move_header, "*** Move to: ")
                        index += 1
                hunks: List[Dict[str, List[str]]] = []
                current_hunk: Optional[Dict[str, List[str]]] = None
                while index < len(lines) - 1 and not self._is_context_patch_header(
                    lines[index]
                ):
                    raw_line = lines[index]
                    stripped = raw_line.rstrip("\r\n")
                    if stripped.startswith("@@"):
                        current_hunk = {"old": [], "new": []}
                        hunks.append(current_hunk)
                        index += 1
                        continue
                    if stripped == "*** End of File":
                        index += 1
                        continue
                    if stripped.startswith("\\ No newline at end of file"):
                        index += 1
                        continue
                    if current_hunk is None:
                        current_hunk = {"old": [], "new": []}
                        hunks.append(current_hunk)
                    if raw_line.startswith(" "):
                        content = raw_line[1:]
                        current_hunk["old"].append(content)
                        current_hunk["new"].append(content)
                    elif raw_line.startswith("-"):
                        current_hunk["old"].append(raw_line[1:])
                    elif raw_line.startswith("+"):
                        current_hunk["new"].append(raw_line[1:])
                    else:
                        raise ValueError(
                            f"Update File {path} contains an invalid hunk line: "
                            f"{stripped[:80]}"
                        )
                    index += 1
                if not hunks:
                    raise ValueError(f"Update File {path} has no hunks")
                actions.append(
                    {
                        "kind": "update",
                        "path": path,
                        "move_to": move_to,
                        "hunks": hunks,
                    }
                )
                continue
            raise ValueError(f"Unsupported apply_patch header: {header}")
        return actions

    def _parse_patch_path(self, header: str, prefix: str) -> str:
        path = header[len(prefix) :].strip()
        if not path:
            raise ValueError(f"{prefix.strip()} requires a path")
        return path

    def _is_context_patch_header(self, line: str) -> bool:
        stripped = line.rstrip("\r\n")
        return (
            stripped.startswith("*** Add File: ")
            or stripped.startswith("*** Delete File: ")
            or stripped.startswith("*** Update File: ")
            or stripped.startswith("*** End Patch")
        )

    def _apply_update_hunks(
        self,
        content: str,
        hunks: List[Dict[str, List[str]]],
        display_path: str,
    ) -> str:
        current_lines = content.splitlines(keepends=True)
        cursor = 0
        for hunk_index, hunk in enumerate(hunks, start=1):
            old_lines = hunk.get("old", [])
            new_lines = hunk.get("new", [])
            if not old_lines:
                raise ValueError(
                    f"Patch hunk {hunk_index} for {display_path} has no context; "
                    "add exact context lines"
                )
            matches = self._find_line_sequence_matches(
                current_lines,
                old_lines,
                start_index=cursor,
            )
            if not matches:
                raise ValueError(
                    f"Patch context for {display_path} hunk {hunk_index} was not found"
                )
            if len(matches) > 1:
                raise ValueError(
                    f"Patch context for {display_path} hunk {hunk_index} is ambiguous"
                )
            match_index = matches[0]
            current_lines = (
                current_lines[:match_index]
                + new_lines
                + current_lines[match_index + len(old_lines) :]
            )
            cursor = match_index + len(new_lines)
        return "".join(current_lines)

    def _find_line_sequence_matches(
        self,
        haystack: List[str],
        needle: List[str],
        *,
        start_index: int,
    ) -> List[int]:
        if not needle or len(needle) > len(haystack):
            return []
        matches: List[int] = []
        max_index = len(haystack) - len(needle)
        for index in range(max(0, start_index), max_index + 1):
            if haystack[index : index + len(needle)] == needle:
                matches.append(index)
        return matches

    def _safe_file_shape(self, path: Path) -> Dict[str, Any]:
        """Return bounded file size/line diagnostics without reading huge files."""

        if not path.exists() or not path.is_file():
            return {"exists": False, "bytes": 0, "chars": 0, "lines": 0}
        try:
            size = path.stat().st_size
        except Exception:
            return {"exists": True, "bytes": None, "chars": None, "lines": None}
        if size > _EDIT_SHAPE_MAX_BYTES:
            return {
                "exists": True,
                "bytes": size,
                "chars": None,
                "lines": None,
                "skipped": "file_too_large",
            }
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return {"exists": True, "bytes": size, "chars": None, "lines": None}
        return {
            "exists": True,
            "bytes": size,
            "chars": len(content),
            "lines": len(content.splitlines()),
        }

    def _unique_strings(self, values: Iterable[str]) -> List[str]:
        """Return deduplicated non-empty strings in insertion order."""
        items: List[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            items.append(text)
        return items

    def _resolve_target_path(self, requested_path: str) -> Path:
        path_obj = Path(requested_path).expanduser()
        workspace_root = (
            Path(self.workspace_root).expanduser().resolve()
            if self.workspace_root
            else None
        )
        if not path_obj.is_absolute() and workspace_root is not None:
            path_obj = workspace_root / path_obj
        resolved_path = path_obj.resolve()
        if workspace_root is not None:
            try:
                resolved_path.relative_to(workspace_root)
            except ValueError as exc:
                raise ValueError(
                    f"Path escapes workspace root: {requested_path}"
                ) from exc
        return resolved_path

    def _display_path(self, requested_path: str, resolved_path: Path) -> str:
        requested = (requested_path or "").strip()
        if requested and not Path(requested).is_absolute():
            return requested
        if self.workspace_root:
            try:
                return str(resolved_path.relative_to(Path(self.workspace_root)))
            except Exception:
                pass
        return str(resolved_path)

    def _normalize_path(self, path_value: str) -> str:
        candidate = str(path_value or "").strip()
        if not candidate:
            return ""
        path_obj = Path(candidate).expanduser()
        if not path_obj.is_absolute():
            return candidate
        if self.workspace_root:
            try:
                return str(path_obj.resolve().relative_to(Path(self.workspace_root)))
            except Exception:
                pass
        return str(path_obj.resolve())

    def _normalize_paths(self, paths: Iterable[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for path_value in paths:
            normalized_path = self._normalize_path(path_value)
            if not normalized_path or normalized_path in seen:
                continue
            normalized.append(normalized_path)
            seen.add(normalized_path)
        return normalized
