"""Core shim coverage for extracted multi-agent coordinator helpers."""

from __future__ import annotations

from typing import Any

from penguin.core import PenguinCore


def test_get_coordinator_delegates_to_multi_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    coordinator = object()

    def _get_core_coordinator(*args: Any, **kwargs: Any) -> object:
        calls.append((args, kwargs))
        return coordinator

    facade_globals = PenguinCore.get_coordinator.__globals__
    monkeypatch.setattr(
        facade_globals["multi_coordinator_runtime"],
        "get_core_coordinator",
        _get_core_coordinator,
    )

    assert core.get_coordinator() is coordinator
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (core,)
    assert sorted(kwargs) == ["log"]
