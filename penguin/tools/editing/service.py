from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..core.support import (
    apply_diff_to_file,
    delete_lines,
    edit_file_with_pattern,
    enhanced_write_to_file,
    insert_lines,
    replace_lines,
)

from .contracts import EditOperation, FileEditResult
from .legacy_multifile import MultiEditResult, apply_multiedit

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
        return self._execute_single_file_operation(
            operation,
            executor=lambda op, _resolved_path: enhanced_write_to_file(
                op.path,
                op.payload.get("content", ""),
                backup=op.backup,
                workspace_path=self.workspace_root,
            ),
            backup_enabled=operation.backup,
            backup_strategy="suffix",
        )

    def _execute_unified_diff(self, operation: EditOperation) -> FileEditResult:
        return self._execute_single_file_operation(
            operation,
            executor=lambda op, _resolved_path: apply_diff_to_file(
                file_path=op.path,
                diff_content=op.payload.get("diff_content", ""),
                backup=op.backup,
                workspace_path=self.workspace_root,
                return_json=False,
            ),
            backup_enabled=operation.backup,
            backup_strategy="suffix",
        )

    def _execute_replace_lines(self, operation: EditOperation) -> FileEditResult:
        return self._execute_single_file_operation(
            operation,
            executor=lambda op, resolved_path: replace_lines(
                path=str(resolved_path),
                start_line=int(op.payload["start_line"]),
                end_line=int(op.payload["end_line"]),
                new_content=op.payload.get("new_content", ""),
                verify=bool(op.payload.get("verify", True)),
                workspace_path=self.workspace_root,
            ),
            backup_enabled=True,
            backup_strategy="append",
        )

    def _execute_insert_lines(self, operation: EditOperation) -> FileEditResult:
        return self._execute_single_file_operation(
            operation,
            executor=lambda op, resolved_path: insert_lines(
                path=str(resolved_path),
                after_line=int(op.payload["after_line"]),
                new_content=op.payload.get("new_content", ""),
                workspace_path=self.workspace_root,
            ),
            backup_enabled=True,
            backup_strategy="append",
        )

    def _execute_delete_lines(self, operation: EditOperation) -> FileEditResult:
        return self._execute_single_file_operation(
            operation,
            executor=lambda op, resolved_path: delete_lines(
                path=str(resolved_path),
                start_line=int(op.payload["start_line"]),
                end_line=int(op.payload["end_line"]),
                workspace_path=self.workspace_root,
            ),
            backup_enabled=True,
            backup_strategy="append",
        )

    def _execute_regex_replace(self, operation: EditOperation) -> FileEditResult:
        return self._execute_single_file_operation(
            operation,
            executor=lambda op, _resolved_path: edit_file_with_pattern(
                file_path=op.path,
                search_pattern=op.payload.get("search_pattern", ""),
                replacement=op.payload.get("replacement", ""),
                backup=op.backup,
                workspace_path=self.workspace_root,
            ),
            backup_enabled=operation.backup,
            backup_strategy="suffix",
        )

    def _execute_multifile_patch(self, operation: EditOperation) -> FileEditResult:
        operations_payload = operation.payload.get("operations")
        if isinstance(operations_payload, list) and operations_payload:
            return self._execute_structured_multifile_patch(
                operations_payload,
                apply=bool(operation.payload.get("apply", False)),
                warnings=operation.warnings,
            )

        content = str(operation.payload.get("content", ""))
        do_apply = bool(operation.payload.get("apply", False))
        workspace_root = self.workspace_root or os.getcwd()
        result = apply_multiedit(
            content,
            dry_run=(not do_apply),
            workspace_root=workspace_root,
        )
        return self._normalize_multiedit_result(
            result,
            apply=do_apply,
            warnings=operation.warnings,
        )

    def _execute_single_file_operation(
        self,
        operation: EditOperation,
        *,
        executor: Callable[[EditOperation, Path], Any],
        backup_enabled: bool,
        backup_strategy: str,
    ) -> FileEditResult:
        """Execute one file operation and normalize the result in one place."""
        resolved_path = self._resolve_target_path(operation.path)
        existed_before = resolved_path.exists()
        raw_output = executor(operation, resolved_path)
        return self._normalize_single_file_result(
            requested_path=operation.path,
            resolved_path=resolved_path,
            raw_output=raw_output,
            warnings=operation.warnings,
            backup_paths=self._expected_backup_paths(
                resolved_path,
                existed_before,
                backup_enabled,
                strategy=backup_strategy,
            ),
            existed_before=existed_before,
        )

    def _execute_structured_multifile_patch(
        self,
        operations: List[Any],
        *,
        apply: bool,
        warnings: Optional[List[str]] = None,
    ) -> FileEditResult:
        base_warnings = list(warnings or [])
        edit_operations = [op for op in operations if isinstance(op, EditOperation)]
        normalized_files = self._normalize_paths(
            [operation.path for operation in edit_operations if operation.path]
        )

        if not edit_operations:
            message = "No valid operations provided for patch_files"
            return FileEditResult(
                ok=False,
                files=[],
                message=message,
                warnings=base_warnings,
                error=message,
                data={
                    "applied": apply,
                    "rollback_performed": False,
                    "legacy_output": json.dumps(
                        {
                            "success": False,
                            "files": [],
                            "files_edited": [],
                            "files_failed": [],
                            "error_messages": {"operations": message},
                            "backup_paths": {},
                            "rollback_performed": False,
                            "applied": apply,
                            "warnings": base_warnings,
                        }
                    ),
                },
            )

        if not apply:
            operation_warnings: List[str] = []
            for operation in edit_operations:
                operation_warnings.extend(operation.warnings)
            dry_run_warnings = [*base_warnings, *operation_warnings, "dry-run"]
            message = (
                f"Prepared structured multi-file patch affecting {len(normalized_files)} "
                "file(s)"
            )
            return FileEditResult(
                ok=True,
                files=normalized_files,
                message=message,
                warnings=dry_run_warnings,
                data={
                    "applied": False,
                    "rollback_performed": False,
                    "legacy_output": json.dumps(
                        {
                            "success": True,
                            "files": normalized_files,
                            "files_edited": normalized_files,
                            "files_failed": [],
                            "error_messages": {},
                            "backup_paths": {},
                            "rollback_performed": False,
                            "applied": False,
                            "warnings": dry_run_warnings,
                        }
                    ),
                },
            )

        applied_records: List[Dict[str, Any]] = []
        files: List[str] = []
        backup_paths: List[str] = []
        diagnostics: Dict[str, List[Dict[str, Any]]] = {}
        aggregated_warnings = list(base_warnings)

        for operation in edit_operations:
            resolved_path = self._resolve_target_path(operation.path)
            existed_before = resolved_path.exists()
            result = self.execute(operation)
            aggregated_warnings.extend(result.warnings)

            if not result.ok:
                rollback_performed = self._rollback_structured_multifile(
                    applied_records
                )
                failed_files = self._normalize_paths([operation.path])
                error_message = (
                    result.error or result.message or "Structured patch failed"
                )
                legacy_payload = {
                    "success": False,
                    "files": list(files),
                    "files_edited": list(files),
                    "files_failed": failed_files,
                    "error_messages": {
                        failed_files[0]
                        if failed_files
                        else "patch_files": error_message
                    },
                    "backup_paths": {
                        record["file"]: record["backup_path"]
                        for record in applied_records
                        if record.get("backup_path")
                    },
                    "rollback_performed": rollback_performed,
                    "applied": True,
                    "warnings": aggregated_warnings,
                }
                return FileEditResult(
                    ok=False,
                    files=list(files),
                    message=error_message,
                    diagnostics=diagnostics,
                    backup_paths=list(backup_paths),
                    warnings=self._unique_strings(aggregated_warnings),
                    error=error_message,
                    data={
                        "applied": True,
                        "rollback_performed": rollback_performed,
                        "legacy_output": json.dumps(legacy_payload),
                    },
                )

            for file_path in result.files:
                if file_path not in files:
                    files.append(file_path)
            for backup_path in result.backup_paths:
                if backup_path not in backup_paths:
                    backup_paths.append(backup_path)
            diagnostics.update(result.diagnostics)
            applied_records.append(
                {
                    "file": result.files[0]
                    if result.files
                    else self._display_path(operation.path, resolved_path),
                    "resolved_path": resolved_path,
                    "existed_before": existed_before,
                    "backup_path": result.backup_paths[0]
                    if result.backup_paths
                    else None,
                }
            )

        success_message = (
            f"Applied structured multi-file patch affecting {len(files)} file(s)"
        )
        legacy_payload = {
            "success": True,
            "files": list(files),
            "files_edited": list(files),
            "files_failed": [],
            "error_messages": {},
            "backup_paths": {
                record["file"]: record["backup_path"]
                for record in applied_records
                if record.get("backup_path")
            },
            "rollback_performed": False,
            "applied": True,
            "warnings": self._unique_strings(aggregated_warnings),
        }
        return FileEditResult(
            ok=True,
            files=list(files),
            message=success_message,
            diagnostics=diagnostics,
            backup_paths=list(backup_paths),
            warnings=self._unique_strings(aggregated_warnings),
            data={
                "applied": True,
                "rollback_performed": False,
                "legacy_output": json.dumps(legacy_payload),
            },
        )

    def _normalize_single_file_result(
        self,
        *,
        requested_path: str,
        resolved_path: Path,
        raw_output: Any,
        warnings: List[str],
        backup_paths: List[str],
        existed_before: bool,
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
            warnings=list(warnings),
            error=(None if ok else error),
            data={
                "legacy_output": message,
                "resolved_files": [str(resolved_path)],
                "existed_before": existed_before,
            },
        )

    def _normalize_multiedit_result(
        self,
        result: MultiEditResult,
        *,
        apply: bool,
        warnings: Optional[List[str]] = None,
    ) -> FileEditResult:
        normalized_files = self._normalize_paths(result.files_edited)
        normalized_failed = self._normalize_paths(result.files_failed)
        backup_paths = [str(path) for path in result.backup_paths.values()]
        result_warnings = list(warnings or [])
        if not apply:
            result_warnings.append("dry-run")
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
            "warnings": self._unique_strings(result_warnings),
        }

        return FileEditResult(
            ok=result.success,
            files=normalized_files,
            message=message,
            diagnostics={},
            backup_paths=backup_paths,
            warnings=self._unique_strings(result_warnings),
            error=(None if result.success else error),
            data={
                "applied": apply,
                "files_failed": normalized_failed,
                "error_messages": dict(result.error_messages),
                "rollback_performed": result.rollback_performed,
                "legacy_output": json.dumps(legacy_payload),
            },
        )

    def _rollback_structured_multifile(
        self, applied_records: List[Dict[str, Any]]
    ) -> bool:
        """Rollback structured multi-file edits using backups or file deletion."""
        success = True
        for record in reversed(applied_records):
            resolved_path = record.get("resolved_path")
            if not isinstance(resolved_path, Path):
                success = False
                continue
            existed_before = bool(record.get("existed_before"))
            backup_path = record.get("backup_path")
            try:
                if existed_before:
                    if isinstance(backup_path, str) and Path(backup_path).exists():
                        shutil.copy2(backup_path, resolved_path)
                    else:
                        success = False
                else:
                    if resolved_path.exists():
                        resolved_path.unlink()
            except Exception:
                logger.exception(
                    "Failed to rollback structured edit for %s", resolved_path
                )
                success = False
        return success

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
