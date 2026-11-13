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


def _windows_delete_access(path: Path) -> int:
    """Probe DELETE access to distinguish sharing from ACL/read-only failures.

    Return zero when access is now available, or the Windows error code. A
    conflicting reader may close before this probe runs. Read-only attributes
    and ACL denials still return 5, so they cannot be mistaken for that race.
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
    kernel.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    kernel.GetFileAttributesW.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    attributes = kernel.GetFileAttributesW(str(path))
    if attributes == 0xFFFFFFFF:
        return ctypes.get_last_error()
    if attributes & 1:  # FILE_ATTRIBUTE_READONLY
        return 5
    handle = kernel.CreateFileW(str(path), 0x10000, 7, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        return ctypes.get_last_error()
    kernel.CloseHandle(handle)
    return 0


def _sharing_violation(error: OSError, source: Path, target: Path) -> bool:
    """Retry only Windows sharing/lock errors, never arbitrary access denial."""
    if os.name != "nt":
        return False
    code = getattr(error, "winerror", None)
    if code in (32, 33, 303):  # sharing, lock, or delete-pending conflict
        return True
    if code != 5:
        return False
    source_access = _windows_delete_access(source)
    target_access = _windows_delete_access(target)
    # The helper owns a newly-created sibling source, so directory creation
    # access was already verified. Require DELETE access to be available or
    # explicitly sharing-blocked; never retry a remaining access denial.
    return source_access in (0, 32, 33, 303) and target_access in (0, 2, 3, 32, 33, 303)


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
