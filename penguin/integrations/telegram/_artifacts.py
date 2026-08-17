"""Artifact discovery and send-time path validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def validated_artifact_path(payload: Mapping[str, Any], max_bytes: int) -> Path:
    """Revalidate a queued artifact against its enqueue-time canonical root."""

    path = Path(str(payload.get("path") or ""))
    root = Path(str(payload.get("allowed_root") or ""))
    try:
        if not path.is_absolute() or not root.is_absolute():
            raise ValueError("artifact paths must be absolute")
        if path.is_symlink() or root.is_symlink():
            raise ValueError("artifact paths must not be symlinks")
        resolved = path.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
        if resolved != path or resolved_root != root or not resolved_root.is_dir():
            raise ValueError("artifact path changed after enqueue")
        resolved.relative_to(resolved_root)
        if not resolved.is_file() or resolved.stat().st_size > max_bytes:
            raise ValueError("artifact is unavailable or exceeds the size limit")
    except (OSError, ValueError) as exc:
        raise ValueError("Telegram artifact is unsafe or unavailable") from exc
    return resolved


def artifact_paths(result: Mapping[str, Any]) -> list[str]:
    """Find paths exposed through explicit artifact projection fields only."""

    found: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, str):
            found.append(value)
            return
        if isinstance(value, Mapping):
            for key in ("path", "file_path", "image_path"):
                child = value.get(key)
                if isinstance(child, str):
                    found.append(child)
            visit(value.get("artifact"))
            visit(value.get("artifacts"))
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result.get("artifact"))
    visit(result.get("artifacts"))
    actions = result.get("action_results")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, Mapping):
                visit(action.get("artifact"))
                visit(action.get("artifacts"))
    return list(dict.fromkeys(found))[:20]
