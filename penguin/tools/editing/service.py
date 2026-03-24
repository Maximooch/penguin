from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.support import (
    apply_diff_to_file,
    edit_file_with_pattern,
    enhanced_write_to_file,
    insert_lines,
    replace_lines,
    delete_lines,
)
from ..multiedit import MultiEditResult, apply_multiedit

from .contracts import EditOperation, FileEditResult

logger = logging.getLogger(__name__)

_PATCH_FILE_OPERATION_TYPES = {
    "unified_diff",
    "replace_lines",
    "insert_lines",
    "delete_lines",
    "regex_replace",
}


class EditService:
    """Canonical adapter over Penguin's existing edit implementations."""

    def __init__(self, workspace_root: Optional[str] = None):
        self.workspace_root = (
            str(Path(workspace_root).expanduser().resolve()) if workspace_root else None
        )

    def write_file(
        self, path: str, content: str, backup: bool = True
    ) -> FileEditResult:
        """Write a file using the canonical result contract."""

        operation = EditOperation(
            type="write",
            path=path,
            payload={"content": content},
            backup=backup,
        )
        return self.execute(operation)

    def patch_file(self, operation: EditOperation) -> FileEditResult:
        """Apply a single-file patch/edit operation."""

        if operation.type not in _PATCH_FILE_OPERATION_TYPES:
            raise ValueError(f"Unsupported patch_file operation type: {operation.type}")
        return self.execute(operation)

    def patch_files(self, content: str, apply: bool = False) -> FileEditResult:
        """Apply a multi-file edit operation."""

        operation = EditOperation(
            type="multifile_patch",
            payload={"content": content, "apply": apply},
            backup=True,
        )
        return self.execute(operation)

    def execute(self, operation: EditOperation) -> FileEditResult:
        """Execute one canonical edit operation."""

        if operation.type == "write":
            return self._execute_write(operation)
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
        resolved_path = self._resolve_target_path(operation.path)
        existed_before = resolved_path.exists()
        raw_output = enhanced_write_to_file(
            operation.path,
            operation.payload.get("content", ""),
            backup=operation.backup,
            workspace_path=self.workspace_root,
        )
        return self._normalize_single_file_result(
            requested_path=operation.path,
            resolved_path=resolved_path,
            raw_output=raw_output,
            backup_paths=self._expected_backup_paths(
                resolved_path,
                existed_before,
                operation.backup,
                strategy="suffix",
            ),
        )

    def _execute_unified_diff(self, operation: EditOperation) -> FileEditResult:
        resolved_path = self._resolve_target_path(operation.path)
        existed_before = resolved_path.exists()
        raw_output = apply_diff_to_file(
            file_path=operation.path,
            diff_content=operation.payload.get("diff_content", ""),
            backup=operation.backup,
            workspace_path=self.workspace_root,
            return_json=False,
        )
        return self._normalize_single_file_result(
            requested_path=operation.path,
            resolved_path=resolved_path,
            raw_output=raw_output,
            backup_paths=self._expected_backup_paths(
                resolved_path,
                existed_before,
                operation.backup,
                strategy="suffix",
            ),
        )

    def _execute_replace_lines(self, operation: EditOperation) -> FileEditResult:
        resolved_path = self._resolve_target_path(operation.path)
        existed_before = resolved_path.exists()
        raw_output = replace_lines(
            path=str(resolved_path),
            start_line=int(operation.payload["start_line"]),
            end_line=int(operation.payload["end_line"]),
            new_content=operation.payload.get("new_content", ""),
            verify=bool(operation.payload.get("verify", True)),
            workspace_path=self.workspace_root,
        )
        return self._normalize_single_file_result(
            requested_path=operation.path,
            resolved_path=resolved_path,
            raw_output=raw_output,
            backup_paths=self._expected_backup_paths(
                resolved_path,
                existed_before,
                True,
                strategy="append",
            ),
        )

    def _execute_insert_lines(self, operation: EditOperation) -> FileEditResult:
        resolved_path = self._resolve_target_path(operation.path)
        existed_before = resolved_path.exists()
        raw_output = insert_lines(
            path=str(resolved_path),
            after_line=int(operation.payload["after_line"]),
            new_content=operation.payload.get("new_content", ""),
            workspace_path=self.workspace_root,
        )
        return self._normalize_single_file_result(
            requested_path=operation.path,
            resolved_path=resolved_path,
            raw_output=raw_output,
            backup_paths=self._expected_backup_paths(
                resolved_path,
                existed_before,
                True,
                strategy="append",
            ),
        )

    def _execute_delete_lines(self, operation: EditOperation) -> FileEditResult:
        resolved_path = self._resolve_target_path(operation.path)
        existed_before = resolved_path.exists()
        raw_output = delete_lines(
            path=str(resolved_path),
            start_line=int(operation.payload["start_line"]),
            end_line=int(operation.payload["end_line"]),
            workspace_path=self.workspace_root,
        )
        return self._normalize_single_file_result(
            requested_path=operation.path,
            resolved_path=resolved_path,
            raw_output=raw_output,
            backup_paths=self._expected_backup_paths(
                resolved_path,
                existed_before,
                True,
                strategy="append",
            ),
        )

    def _execute_regex_replace(self, operation: EditOperation) -> FileEditResult:
        resolved_path = self._resolve_target_path(operation.path)
        existed_before = resolved_path.exists()
        raw_output = edit_file_with_pattern(
            file_path=operation.path,
            search_pattern=operation.payload.get("search_pattern", ""),
            replacement=operation.payload.get("replacement", ""),
            backup=operation.backup,
            workspace_path=self.workspace_root,
        )
        return self._normalize_single_file_result(
            requested_path=operation.path,
            resolved_path=resolved_path,
            raw_output=raw_output,
            backup_paths=self._expected_backup_paths(
                resolved_path,
                existed_before,
                operation.backup,
                strategy="suffix",
            ),
        )

    def _execute_multifile_patch(self, operation: EditOperation) -> FileEditResult:
        content = str(operation.payload.get("content", ""))
        do_apply = bool(operation.payload.get("apply", False))
        workspace_root = self.workspace_root or os.getcwd()
        result = apply_multiedit(
            content,
            dry_run=(not do_apply),
            workspace_root=workspace_root,
        )
        return self._normalize_multiedit_result(result, apply=do_apply)

    def _normalize_single_file_result(
        self,
        *,
        requested_path: str,
        resolved_path: Path,
        raw_output: Any,
        backup_paths: List[str],
    ) -> FileEditResult:
        message = raw_output if isinstance(raw_output, str) else str(raw_output)
        payload = self._parse_payload(raw_output)
        ok = self._is_success(payload, message)
        error = self._extract_error(payload, message)
        diagnostics = self._extract_diagnostics(payload)
        files = self._extract_files_from_payload(payload)

        if not files and ok and self._result_indicates_change(payload, message):
            display_path = self._display_path(requested_path, resolved_path)
            if display_path:
                files = [display_path]

        return FileEditResult(
            ok=ok,
            files=files,
            message=message,
            diagnostics=diagnostics,
            backup_paths=backup_paths,
            warnings=[],
            error=(None if ok else error),
            data={"legacy_output": message},
        )

    def _normalize_multiedit_result(
        self,
        result: MultiEditResult,
        *,
        apply: bool,
    ) -> FileEditResult:
        normalized_files = self._normalize_paths(result.files_edited)
        normalized_failed = self._normalize_paths(result.files_failed)
        backup_paths = [str(path) for path in result.backup_paths.values()]
        warnings = [] if apply else ["dry-run"]
        error = self._first_error_message(result.error_messages)

        if result.success:
            action = "Applied" if apply else "Prepared"
            message = (
                f"{action} multi-file patch affecting {len(normalized_files)} file(s)"
            )
        else:
            message = error or "Multi-file patch failed"

        legacy_payload = {
            "success": result.success,
            "files": normalized_files,
            "files_edited": list(result.files_edited),
            "files_failed": list(result.files_failed),
            "error_messages": dict(result.error_messages),
            "backup_paths": dict(result.backup_paths),
            "rollback_performed": result.rollback_performed,
            "applied": apply,
        }

        return FileEditResult(
            ok=result.success,
            files=normalized_files,
            message=message,
            diagnostics={},
            backup_paths=backup_paths,
            warnings=warnings,
            error=(None if result.success else error),
            data={
                "applied": apply,
                "files_failed": normalized_failed,
                "error_messages": dict(result.error_messages),
                "rollback_performed": result.rollback_performed,
                "legacy_output": json.dumps(legacy_payload),
            },
        )

    def _resolve_target_path(self, requested_path: str) -> Path:
        path_obj = Path(requested_path).expanduser()
        if not path_obj.is_absolute() and self.workspace_root:
            path_obj = Path(self.workspace_root) / path_obj
        return path_obj.resolve()

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

    def _expected_backup_paths(
        self,
        resolved_path: Path,
        existed_before: bool,
        backup: bool,
        *,
        strategy: str,
    ) -> List[str]:
        if not backup or not existed_before:
            return []
        if strategy == "append":
            return [f"{resolved_path}.bak"]
        return [str(resolved_path.with_suffix(resolved_path.suffix + ".bak"))]

    def _parse_payload(self, raw_output: Any) -> Optional[Dict[str, Any]]:
        if isinstance(raw_output, dict):
            return raw_output
        if not isinstance(raw_output, str):
            return None
        stripped = raw_output.strip()
        if not stripped.startswith("{"):
            return None
        try:
            payload = json.loads(stripped)
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _is_success(self, payload: Optional[Dict[str, Any]], message: str) -> bool:
        if isinstance(payload, dict):
            success = payload.get("success")
            if isinstance(success, bool):
                return success
            status = payload.get("status")
            if isinstance(status, str):
                return status.lower() in {"success", "created"}
            if payload.get("error") is not None:
                return False
        return not message.strip().lower().startswith("error")

    def _extract_error(
        self,
        payload: Optional[Dict[str, Any]],
        message: str,
    ) -> Optional[str]:
        if isinstance(payload, dict):
            explicit_error = payload.get("error")
            if isinstance(explicit_error, str) and explicit_error.strip():
                return explicit_error.strip()
            status = payload.get("status")
            if isinstance(status, str) and status.lower() not in {"success", "created"}:
                structured_message = payload.get("message")
                if isinstance(structured_message, str) and structured_message.strip():
                    return structured_message.strip()
        if message.strip().lower().startswith("error"):
            return message.strip()
        return None

    def _extract_diagnostics(
        self, payload: Optional[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        if not isinstance(payload, dict):
            return {}
        diagnostics = payload.get("diagnostics")
        if not isinstance(diagnostics, dict):
            return {}

        normalized: Dict[str, List[Dict[str, Any]]] = {}
        for raw_path, entries in diagnostics.items():
            if not isinstance(entries, list):
                continue
            path_key = self._normalize_path(str(raw_path))
            if not path_key:
                continue
            normalized[path_key] = [
                entry for entry in entries if isinstance(entry, dict)
            ]
        return normalized

    def _extract_files_from_payload(
        self, payload: Optional[Dict[str, Any]]
    ) -> List[str]:
        if not isinstance(payload, dict):
            return []

        raw_paths: List[str] = []
        for key in ("file",):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                raw_paths.append(value)

        for key in ("files", "created"):
            value = payload.get(key)
            if isinstance(value, list):
                raw_paths.extend(str(item) for item in value if isinstance(item, str))

        return self._normalize_paths(raw_paths)

    def _result_indicates_change(
        self, payload: Optional[Dict[str, Any]], message: str
    ) -> bool:
        if isinstance(payload, dict):
            success = payload.get("success")
            if isinstance(success, bool) and payload.get("files_edited") is not None:
                return bool(payload.get("files_edited"))
            status = payload.get("status")
            if isinstance(status, str):
                return status.lower() in {"success", "created"}

        lowered = message.strip().lower()
        if not lowered:
            return False
        if lowered.startswith("error"):
            return False
        if lowered.startswith("no matches found"):
            return False
        if lowered.startswith("no changes detected"):
            return False
        return True

    def _first_error_message(self, error_messages: Dict[str, str]) -> Optional[str]:
        for value in error_messages.values():
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
