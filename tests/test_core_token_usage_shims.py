"""Core shim coverage for extracted token usage helpers."""

from __future__ import annotations

from typing import Any

from penguin.core import PenguinCore


def test_update_token_display_delegates_to_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def _emit_token_display_update(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(
        "penguin.core.core_token_usage_runtime.emit_token_display_update",
        _emit_token_display_update,
    )

    core.update_token_display()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (core,)
    assert sorted(kwargs) == ["log"]
