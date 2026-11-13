"""Request-scoped client tool routing; no shared backend mutation."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_PROVIDERS: ContextVar[dict[int, Any]] = ContextVar("client_tool_providers", default={})


@contextmanager
def client_tool_scope(manager: Any, provider: Any) -> Iterator[None]:
    token = _PROVIDERS.set({**_PROVIDERS.get(), id(manager): provider})
    try:
        yield
    finally:
        _PROVIDERS.reset(token)


def active_client_tools(manager: Any) -> Any:
    return _PROVIDERS.get().get(id(manager))
