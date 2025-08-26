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


def get_allowed_roots(cwd_override: Optional[str] = None) -> Tuple[Path, Path, List[Path], List[Path]]:
    """Return (project_root, workspace_root, project_additional, context_additional).

    Honors project.root_strategy: 'git-root' (default) or 'cwd'.
    """
    cfg = load_config()

    # Determine project root based on strategy
    strategy = (cfg.get('project', {}).get('root_strategy') or 'git-root').lower()
    if strategy == 'cwd':
        try:
            start_dir = Path(cwd_override or os.environ.get('PENGUIN_CWD') or os.getcwd()).resolve()
        except Exception:
            start_dir = Path.cwd().resolve()
        project_root = start_dir
    else:
        paths = get_project_config_paths(cwd_override)
        project_root = paths['project_root']

    workspace_root = Path(WORKSPACE_PATH)

    proj_add_list = cfg.get('project', {}).get('additional_directories', []) or []
    ctx_add_list = cfg.get('context', {}).get('additional_paths', []) or []

    project_additional: List[Path] = []
    for p in proj_add_list:
        try:
            project_additional.append(Path(p).expanduser().resolve())
        except Exception:
            continue

    context_additional: List[Path] = []
    for p in ctx_add_list:
        try:
            context_additional.append(Path(p).expanduser().resolve())
        except Exception:
            continue

    return (
        project_root.resolve(),
        workspace_root.resolve(),
        project_additional,
        context_additional,
    )


def is_path_allowed(target: Path, root_pref: str = 'auto', cwd_override: Optional[str] = None) -> bool:
    """Check whether target path is allowed by project/workspace policy.

    root_pref: 'project' | 'workspace' | 'auto'
      - auto: allow project, workspace, or additional allowlisted directories.
    """
    try:
        target = target.expanduser().resolve()
    except Exception:
        return False

    project_root, workspace_root, project_additional, context_additional = get_allowed_roots(cwd_override)

    def _starts_with(parent: Path) -> bool:
        return str(target).startswith(str(parent))

    if root_pref == 'project':
        return _starts_with(project_root) or any(_starts_with(a) for a in project_additional)
    if root_pref == 'workspace':
        return _starts_with(workspace_root) or any(_starts_with(a) for a in context_additional)

    return (
        _starts_with(project_root)
        or _starts_with(workspace_root)
        or any(_starts_with(a) for a in project_additional)
        or any(_starts_with(a) for a in context_additional)
    )


def get_default_write_root() -> str:
    """Return default write root from config.defaults.write_root (project|workspace)."""
    cfg = load_config()
    val = (cfg.get('defaults', {}).get('write_root') or 'project').lower()
    return 'workspace' if val == 'workspace' else 'project'


def enforce_allowed_path(target: Path, root_pref: str = 'auto', cwd_override: Optional[str] = None) -> Path:
    """Raise ValueError if target is outside allowed roots; return resolved path otherwise."""
    resolved = target.expanduser().resolve()
    if not is_path_allowed(resolved, root_pref=root_pref, cwd_override=cwd_override):
        raise ValueError(f"Path not allowed by policy: {resolved}")
    return resolved
