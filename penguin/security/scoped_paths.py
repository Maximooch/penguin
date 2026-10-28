"""Immutable filesystem roots owned by the current execution scope."""

from pathlib import Path

from penguin.system.execution_context import get_current_execution_context


def persisted_roots(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value or len(value) > 34:
        raise ValueError("Invalid persisted execution roots")
    if any(
        not isinstance(path, str)
        or not Path(path).is_absolute()
        or str(Path(path).resolve()) != path
        or not Path(path).is_dir()
        for path in value
    ):
        raise ValueError("Persisted execution roots are not canonical directories")
    return tuple(value)


def execution_roots() -> tuple[Path, ...] | None:
    context = get_current_execution_context()
    if context is None or context.allowed_roots is None:
        return None
    # These are already canonical roots, not paths to resolve again after a
    # directory is replaced by a symlink during an active turn.
    roots = tuple(Path(path) for path in context.allowed_roots)
    if any(not root.is_absolute() for root in roots):
        raise ValueError("Execution roots must be absolute")
    return roots


def enforce_execution_path(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    roots = execution_roots()
    if roots is not None and not any(resolved.is_relative_to(root) for root in roots):
        raise ValueError(
            f"Path is outside this execution's authorized roots: {resolved}"
        )
    return resolved
