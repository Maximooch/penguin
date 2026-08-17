"""Environment and path normalization for CLI startup."""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path

__all__ = ["preconfigure_cli_environment", "set_cli_workspace_path"]

logger = logging.getLogger(__name__)


def set_cli_workspace_path(workspace_path: str | Path) -> Path:
    """Normalize and propagate a workspace override before core construction."""

    resolved_workspace = Path(workspace_path).expanduser().resolve()
    os.environ["PENGUIN_WORKSPACE"] = str(resolved_workspace)
    try:
        config_module = importlib.import_module("penguin.config")
        config_module.WORKSPACE_PATH = resolved_workspace
    except Exception:
        logger.debug(
            "Unable to sync workspace override into penguin.config", exc_info=True
        )
    return resolved_workspace


def preconfigure_cli_environment(
    workspace: Path | None,
    project: str | None,
    root: str | None,
    *,
    default_workspace: str | Path,
) -> tuple[Path | None, Path]:
    """Normalize execution-root and workspace hints before loading config."""

    workspace_source = workspace or os.environ.get(
        "PENGUIN_WORKSPACE", str(default_workspace)
    )
    resolved_workspace = set_cli_workspace_path(workspace_source)
    os.environ["PENGUIN_CWD"] = str(Path.cwd().resolve())
    os.environ.pop("PENGUIN_PROJECT_ROOT", None)

    resolved_project_path: Path | None = None
    if project:
        candidates = [
            Path(project).expanduser(),
            resolved_workspace / "projects" / project,
        ]
        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_dir():
                    resolved_project_path = candidate.resolve()
                    os.environ["PENGUIN_PROJECT_ROOT"] = str(resolved_project_path)
                    os.environ["PENGUIN_CWD"] = str(resolved_project_path)
                    break
            except OSError:
                continue

    root_mode = (root or "project").lower()
    if root_mode in {"project", "workspace"}:
        os.environ["PENGUIN_WRITE_ROOT"] = root_mode
        if root_mode == "workspace":
            os.environ["PENGUIN_CWD"] = str(resolved_workspace)
        elif resolved_project_path is not None:
            os.environ["PENGUIN_CWD"] = str(resolved_project_path)

    return resolved_project_path, resolved_workspace
