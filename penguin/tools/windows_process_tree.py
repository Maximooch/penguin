"""Native Windows fallback for owned process trees when taskkill is unavailable."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import subprocess

__all__ = ["terminate_owned_tree"]


def terminate_owned_tree(process: subprocess.Popen, timeout: float = 2.0) -> None:
    """Stop observed descendants and the retained root process handle.

    psutil uses native process APIs, avoiding taskkill's WMI dependency. Its
    Process.kill() checks creation identity before termination. This remains a
    snapshot-based cleanup, not Job Object ownership of detached descendants.
    """
    import psutil

    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
    except psutil.NoSuchProcess:
        return
    failures = []
    for child in reversed(children):
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass
        except psutil.Error as exc:
            failures.append(str(exc))
    try:
        process.kill()
    except ProcessLookupError:
        pass
    _, alive = psutil.wait_procs(children, timeout=timeout)
    if alive or failures:
        raise OSError(
            f"Native process-tree cleanup incomplete: {len(alive)} survivors; "
            f"{len(failures)} termination errors"
        )
