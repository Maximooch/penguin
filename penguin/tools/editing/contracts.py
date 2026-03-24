from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional


EditOpType = Literal[
    "write",
    "unified_diff",
    "replace_lines",
    "insert_lines",
    "delete_lines",
    "regex_replace",
    "multifile_patch",
]


@dataclass
class EditOperation:
    """Canonical description of one file edit request."""

    type: EditOpType
    path: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    backup: bool = True


@dataclass
class FileEditResult:
    """Canonical normalized result for file edit operations."""

    ok: bool
    files: List[str] = field(default_factory=list)
    message: str = ""
    diagnostics: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    backup_paths: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable representation of the edit result."""

        payload: Dict[str, Any] = {
            "ok": self.ok,
            "files": list(self.files),
            "message": self.message,
            "diagnostics": dict(self.diagnostics),
            "backup_paths": list(self.backup_paths),
            "warnings": list(self.warnings),
            "error": self.error,
        }
        if self.data:
            payload["data"] = dict(self.data)
        return payload

    def render_legacy_output(self) -> str:
        """Return the transitional legacy tool output string."""

        legacy_output = self.data.get("legacy_output")
        if isinstance(legacy_output, str) and legacy_output:
            return legacy_output
        if self.message:
            return self.message
        if self.error:
            return self.error
        return json.dumps(self.to_dict())
