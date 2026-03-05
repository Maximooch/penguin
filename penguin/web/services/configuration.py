"""Configuration service helpers for route handlers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from penguin.config import get_project_config_paths, get_user_config_path


def _runtime_config_dict(core: Any) -> dict[str, Any]:
    """Build a normalized runtime config dictionary."""
    runtime = getattr(core, "runtime_config", None)
    if runtime is None:
        return {}

    if hasattr(runtime, "to_dict"):
        payload = runtime.to_dict()
        if isinstance(payload, dict):
            return payload

    fields = (
        "project_root",
        "workspace_root",
        "execution_mode",
        "active_root",
    )
    return {
        key: value
        for key in fields
        if (value := getattr(runtime, key, None)) is not None
    }


def _file_info(path: Path) -> dict[str, Any]:
    """Return file path + existence metadata."""
    return {
        "path": str(path),
        "exists": path.exists(),
    }


def runtime_config_payload(core: Any) -> dict[str, Any]:
    """Build runtime configuration payload."""
    config_dict = _runtime_config_dict(core)
    return {"status": "success", "config": config_dict}


def settings_locations_payload(
    core: Any, *, cwd: Optional[str] = None
) -> dict[str, Any]:
    """Build settings paths + runtime metadata payload."""
    project_paths = get_project_config_paths(cwd_override=cwd)
    global_path = get_user_config_path()

    settings = {
        "runtime": _runtime_config_dict(core),
        "locations": {
            "project": {
                "root": str(project_paths["project_root"]),
                "dir": str(project_paths["dir"]),
                "config": _file_info(project_paths["project"]),
                "local": _file_info(project_paths["local"]),
            },
            "global": {
                "config": _file_info(global_path),
            },
        },
    }

    return {"status": "success", "settings": settings}
