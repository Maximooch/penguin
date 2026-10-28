"""Atomic session-file replacement and process-local store synchronization."""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar
from weakref import WeakValueDictionary

if TYPE_CHECKING:
    from _thread import RLock
    from collections.abc import Callable

__all__ = ["atomic_write_text", "store_lock", "synchronized_store"]

logger = logging.getLogger(__name__)
_LOCKS: WeakValueDictionary[str, RLock] = WeakValueDictionary()
_LOCKS_GUARD = threading.Lock()
_RETRY_DELAYS = (0.01, 0.02, 0.04, 0.08, 0.16)
_T = TypeVar("_T")


def store_lock(directory: Path) -> RLock:
    """Share a reentrant lock between live managers of the same directory."""
    key = os.path.normcase(str(directory.resolve()))
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def synchronized_store(method: Callable[..., _T]) -> Callable[..., _T]:
    """Serialize manager state and related file operations in one process."""

    @wraps(method)
    def guarded(self: Any, *args: Any, **kwargs: Any) -> _T:
        with self._store_lock:
            return method(self, *args, **kwargs)

    return guarded


def _windows_delete_is_shared(path: Path) -> bool:
    """Probe DELETE access to distinguish sharing from ACL/read-only failures.

    MoveFileEx may report access denied (5) for an open file. CreateFile reports
    sharing violation (32) for a conflicting handle, while a real access denial
    remains 5. The probe never changes the file and closes successful handles.
    """
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0x10000, 7, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        return ctypes.get_last_error() in (32, 33)
    kernel.CloseHandle(handle)
    return False


def _sharing_violation(error: OSError, source: Path, target: Path) -> bool:
    """Retry only Windows sharing/lock errors, never arbitrary access denial."""
    if os.name != "nt":
        return False
    code = getattr(error, "winerror", None)
    if code in (32, 33):
        return True
    return code == 5 and (
        _windows_delete_is_shared(source) or _windows_delete_is_shared(target)
    )


def _replace(source: Path, target: Path) -> None:
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            os.replace(source, target)
            return
        except OSError as error:
            if attempt == len(_RETRY_DELAYS) or not _sharing_violation(
                error, source, target
            ):
                raise
            time.sleep(_RETRY_DELAYS[attempt])


def atomic_write_text(target: Path, text: str) -> None:
    """Flush a unique sibling file, then replace the target or leave it intact.

    Failed attempts clean up only their own temporary file. Replacement retries
    have a fixed 310ms sleep budget and are limited to confirmed Windows sharing
    violations. The old target is never unlinked or made writable as a fallback.
    """
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        _replace(temporary, target)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Could not clean temporary session file %s",
                    temporary,
                    exc_info=True,
                )
