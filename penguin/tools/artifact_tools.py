"""Explicit projection of existing workspace files as outbound artifacts."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from penguin.system.execution_context import get_current_execution_context
from penguin.utils.path_utils import enforce_allowed_path

__all__ = ["PublishArtifactTool"]


class PublishArtifactTool:
    """Validate one existing file and expose a typed artifact descriptor."""

    def execute(self, path: str) -> dict[str, Any]:
        if not isinstance(path, str) or not path.strip():
            return {"error": "path is required"}
        if len(path) > 4096:
            return {"error": "artifact path is too long"}

        try:
            candidate = Path(path).expanduser()
            context = get_current_execution_context()
            base = (
                Path(context.directory).expanduser()
                if context and context.directory
                else None
            )
            if not candidate.is_absolute() and base is not None:
                candidate = base / candidate
            if candidate.is_symlink():
                return {"error": "artifact path must not be a symlink"}
            roots = _request_roots(context) if context is not None else ()
            has_request_root = context is not None and any(
                isinstance(value, str) and bool(value.strip())
                for value in (
                    context.directory,
                    context.project_root,
                    context.workspace_root,
                )
            )
            if has_request_root and not roots:
                return {"error": "request workspace is unavailable"}
            if roots:
                artifact_path = candidate.resolve(strict=True)
                if not any(
                    artifact_path == root or root in artifact_path.parents
                    for root in roots
                ):
                    return {"error": "artifact path is outside request workspace"}
            else:
                artifact_path = enforce_allowed_path(candidate, root_pref="auto")
            if not artifact_path.is_file():
                return {"error": "artifact path is not an existing file"}
        except (OSError, RuntimeError, ValueError) as exc:
            return {"error": f"artifact path is unavailable: {exc}"}

        mime_type = mimetypes.guess_type(artifact_path.name)[0]
        artifact_type = (
            "image" if mime_type and mime_type.startswith("image/") else "file"
        )
        descriptor = {
            "type": artifact_type,
            "path": str(artifact_path),
            "file_name": artifact_path.name,
        }
        if mime_type:
            descriptor["mime_type"] = mime_type
        return {
            "result": f"Artifact ready for delivery: {artifact_path.name}",
            "artifact": descriptor,
        }


def _request_roots(context: Any) -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in (context.directory, context.project_root, context.workspace_root):
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            root = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if root.is_dir() and root not in roots:
            roots.append(root)
    return tuple(roots)
