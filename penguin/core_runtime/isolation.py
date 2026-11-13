"""Opt-in task-local runtime services; legacy singleton behavior stays default."""

from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from typing import Any

_current: ContextVar["RuntimeServices | None"] = ContextVar(
    "penguin_runtime_services", default=None
)


class RuntimeServices:
    def __init__(self):
        self.values: dict[str, Any] = {}
        self.lock = RLock()

    @contextmanager
    def activate(self):
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)


def scoped_service(key: str, factory: Callable[[], Any]) -> Any:
    scope = _current.get()
    if scope is None:
        return None
    with scope.lock:
        if key not in scope.values:
            value = factory()
            if value is not None:
                scope.values[key] = value
            return value
        return scope.values[key]


def set_scoped_service(key: str, value: Any) -> bool:
    scope = _current.get()
    if scope is None:
        return False
    with scope.lock:
        scope.values[key] = value
    return True


def runtime_isolated() -> bool:
    return _current.get() is not None
