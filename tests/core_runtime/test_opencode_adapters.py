"""Tests for OpenCode TUI adapter lifecycle helpers."""

from __future__ import annotations

from typing import Any

from penguin.core_runtime import opencode_adapters


class _Adapter:
    def __init__(
        self,
        event_bus: Any,
        *,
        persist_callback: Any = None,
        emit_session_status_events: bool = True,
    ) -> None:
        self.event_bus = event_bus
        self.persist_callback = persist_callback
        self.emit_session_status_events = emit_session_status_events
        self.sessions: list[str] = []
        self.directories: list[str | None] = []

    def set_session(self, session_id: str) -> None:
        self.sessions.append(session_id)

    def set_directory(self, directory: str | None) -> None:
        self.directories.append(directory)


def test_get_or_create_session_adapter_creates_scoped_adapter() -> None:
    adapters: dict[str, Any] = {}
    event_bus = object()
    persist_callback = object()

    adapter = opencode_adapters.get_or_create_session_adapter(
        "session_1",
        adapters=adapters,
        event_bus=event_bus,
        persist_callback=persist_callback,
        directory="/tmp/project",
        adapter_factory=_Adapter,
    )

    assert isinstance(adapter, _Adapter)
    assert adapters["session_1"] is adapter
    assert adapter.event_bus is event_bus
    assert adapter.persist_callback is persist_callback
    assert adapter.emit_session_status_events is False
    assert adapter.sessions == ["session_1"]
    assert adapter.directories == ["/tmp/project"]


def test_get_or_create_session_adapter_reuses_and_refreshes_directory() -> None:
    existing = _Adapter(object())
    adapters: dict[str, Any] = {"session_1": existing}

    def fail_factory(*_args: Any, **_kwargs: Any) -> _Adapter:
        raise AssertionError("existing adapter should be reused")

    adapter = opencode_adapters.get_or_create_session_adapter(
        "session_1",
        adapters=adapters,
        event_bus=object(),
        persist_callback=object(),
        directory="/tmp/next",
        adapter_factory=fail_factory,
    )

    assert adapter is existing
    assert existing.sessions == []
    assert existing.directories == ["/tmp/next"]


def test_get_or_create_session_adapter_uses_unknown_session_fallback() -> None:
    adapters: dict[str, Any] = {}

    adapter = opencode_adapters.get_or_create_session_adapter(
        None,
        adapters=adapters,
        event_bus=object(),
        persist_callback=None,
        directory=None,
        adapter_factory=_Adapter,
    )

    assert adapters["unknown"] is adapter
    assert adapter.sessions == ["unknown"]
    assert adapter.directories == [None]
