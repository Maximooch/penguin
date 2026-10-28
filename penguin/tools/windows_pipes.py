"""Bounded synchronous pipe polling for Windows subprocesses.

Windows selectors accept sockets, not subprocess pipes. PeekNamedPipe lets the
single capture worker drain ready pipes without blocking on a quiet stream.
"""

from __future__ import annotations

import ctypes
import msvcrt
import selectors
import threading
import time
from ctypes import wintypes
from typing import Any

__all__ = ["PipeSelector", "set_nonblocking"]

_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel.PeekNamedPipe.argtypes = [
    wintypes.HANDLE,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
_kernel.PeekNamedPipe.restype = wintypes.BOOL
_kernel.SetNamedPipeHandleState.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
    ctypes.c_void_p,
]
_kernel.SetNamedPipeHandleState.restype = wintypes.BOOL


def set_nonblocking(fd: int) -> None:
    """Set PIPE_NOWAIT, including on Python versions before 3.12."""
    mode = wintypes.DWORD(1)
    if not _kernel.SetNamedPipeHandleState(
        msvcrt.get_osfhandle(fd), ctypes.byref(mode), None, None
    ):
        raise ctypes.WinError(ctypes.get_last_error())


class PipeSelector:
    """Small read-only selector adapter for anonymous subprocess pipes."""

    def __init__(self, stop_event: threading.Event | None = None) -> None:
        self._keys: dict[int, selectors.SelectorKey] = {}
        self._stop_event = stop_event or threading.Event()

    def __enter__(self) -> PipeSelector:
        return self

    def __exit__(self, *_args: Any) -> None:
        self._keys.clear()

    def register(self, pipe: Any, events: int, data: str) -> None:
        self._keys[pipe.fileno()] = selectors.SelectorKey(
            pipe, pipe.fileno(), events, data
        )

    def unregister(self, pipe: Any) -> None:
        del self._keys[pipe.fileno()]

    def get_map(self) -> dict[int, selectors.SelectorKey]:
        return self._keys

    def select(self, timeout: float) -> list[tuple[selectors.SelectorKey, int]]:
        """Return readable or closed pipes, waiting at most the given duration."""
        deadline = time.monotonic() + timeout
        while True:
            ready = []
            for fd, key in self._keys.items():
                available = wintypes.DWORD()
                if not _kernel.PeekNamedPipe(
                    msvcrt.get_osfhandle(fd),
                    None,
                    0,
                    None,
                    ctypes.byref(available),
                    None,
                ):
                    error = ctypes.get_last_error()
                    if error not in (109, 232):  # broken pipe / no data (closed)
                        raise ctypes.WinError(error)
                    ready.append((key, key.events))
                elif available.value:
                    ready.append((key, key.events))
            remaining = deadline - time.monotonic()
            if ready or remaining <= 0 or self._stop_event.is_set():
                return ready
            # Anonymous Windows pipes cannot be selected. Bound readiness scans
            # to the capture cadence and block between scans, including when
            # both streams have closed but the child is still running.
            self._stop_event.wait(min(remaining, 0.02))
            if time.monotonic() >= deadline:
                return []
