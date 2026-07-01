"""OpenCode TUI adapter lifecycle helpers."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any

from . import opencode_bridge as core_opencode_bridge

AdapterFactory = Callable[..., Any]

__all__ = [
    "AdapterFactory",
    "get_or_create_session_adapter",
    "get_tui_adapter",
]


def get_or_create_session_adapter(
    session_id: str | None,
    *,
    adapters: MutableMapping[str, Any],
    event_bus: Any,
    persist_callback: Any,
    directory: str | None,
    adapter_factory: AdapterFactory | None = None,
) -> Any:
    """Return a session-scoped OpenCode adapter with current directory metadata."""

    sid = session_id or "unknown"
    adapter = adapters.get(sid)
    if adapter is not None:
        _set_adapter_directory(adapter, directory)
        return adapter

    if adapter_factory is None:
        from penguin.tui_adapter import PartEventAdapter

        adapter_factory = PartEventAdapter

    adapter = adapter_factory(
        event_bus,
        persist_callback=persist_callback,
        emit_session_status_events=False,
    )
    set_session = getattr(adapter, "set_session", None)
    if callable(set_session):
        set_session(sid)
    _set_adapter_directory(adapter, directory)
    adapters[sid] = adapter
    return adapter


def get_tui_adapter(
    owner: Any,
    session_id: str | None,
    *,
    execution_context: Any = None,
    adapter_factory: AdapterFactory | None = None,
) -> Any:
    """Return a session-scoped TUI adapter for a core-like owner."""

    sid = session_id or "unknown"
    resolved_directory = core_opencode_bridge.resolve_adapter_directory(
        sid,
        session_directories=getattr(owner, "_opencode_session_directories", None),
        execution_context=execution_context,
        runtime_config=getattr(owner, "runtime_config", None),
    )

    adapters = getattr(owner, "_tui_adapters", None)
    if not isinstance(adapters, dict):
        adapters = {}
        owner._tui_adapters = adapters
    return get_or_create_session_adapter(
        sid,
        adapters=adapters,
        event_bus=owner.event_bus,
        persist_callback=owner._persist_opencode_event,
        directory=resolved_directory,
        adapter_factory=adapter_factory,
    )


def _set_adapter_directory(adapter: Any, directory: str | None) -> None:
    set_directory = getattr(adapter, "set_directory", None)
    if callable(set_directory):
        set_directory(directory)
