import os
from pathlib import Path
from typing import Optional, Tuple, List

from penguin.config import get_project_config_paths, WORKSPACE_PATH, load_config


def normalize_path(path: str) -> str:
    from penguin.config import WORKSPACE_PATH as _WP
    # Remove any leading slashes or backslashes
    path = path.lstrip("/\\")
    # Remove 'workspace/' prefix if present
    if path.startswith("workspace/"):
        path = path[len("workspace/") :]
    # Normalize the path to prevent directory traversal
    full_path = os.path.normpath(os.path.join(_WP, path))
    # Security check
    if not full_path.startswith(os.path.abspath(_WP)):
        raise ValueError("Attempted to access a file outside of the workspace.")
    return full_path


def get_allowed_roots(cwd_override: Optional[str] = None) -> Tuple[Path, Path, List[Path]]:
    """Return (project_root, workspace_root, additional_allowed).

    - project_root: git root if available, else CWD (or from PENGUIN_CWD/cwd_override)
    - workspace_root: WORKSPACE_PATH
    - additional_allowed: list of extra directories from config (project.additional_directories)
    """
    cfg = load_config()
    paths = get_project_config_paths(cwd_override)
    project_root = paths['project_root']
    workspace_root = Path(WORKSPACE_PATH)
    additional = cfg.get('project', {}).get('additional_directories', []) or []
    additional_paths: List[Path] = []
    for p in additional:
        try:
            additional_paths.append(Path(p).expanduser().resolve())
        except Exception:
            continue
    return project_root.resolve(), workspace_root.resolve(), additional_paths


def is_path_allowed(target: Path, root_pref: str = 'auto', cwd_override: Optional[str] = None) -> bool:
    """Check whether target path is allowed by project/workspace policy.

    root_pref: 'project' | 'workspace' | 'auto'
      - auto: allow project, workspace, or additional allowlisted directories.
    """
    try:
        target = target.expanduser().resolve()
    except Exception:
        return False

    project_root, workspace_root, additional = get_allowed_roots(cwd_override)

    def _starts_with(parent: Path) -> bool:
        return str(target).startswith(str(parent))

    if root_pref == 'project':
        return _starts_with(project_root) or any(_starts_with(a) for a in additional)
    if root_pref == 'workspace':
        return _starts_with(workspace_root)

    return _starts_with(project_root) or _starts_with(workspace_root) or any(_starts_with(a) for a in additional)


def enforce_allowed_path(target: Path, root_pref: str = 'auto', cwd_override: Optional[str] = None) -> Path:
    """Raise ValueError if target is outside allowed roots; return resolved path otherwise."""
    resolved = target.expanduser().resolve()
    if not is_path_allowed(resolved, root_pref=root_pref, cwd_override=cwd_override):
        raise ValueError(f"Path not allowed by policy: {resolved}")
    return resolved
