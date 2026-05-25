"""Core shim coverage for extracted core state helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from penguin.core import PenguinCore


def test_core_state_methods_delegate_to_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _validate_path(*args: Any, **kwargs: Any) -> None:
        calls.append(("validate", args, kwargs))

    def _register_progress_callback(*args: Any, **kwargs: Any) -> None:
        calls.append(("register", args, kwargs))

    def _notify_progress(*args: Any, **kwargs: Any) -> None:
        calls.append(("notify", args, kwargs))

    def _reset_context(*args: Any, **kwargs: Any) -> None:
        calls.append(("reset", args, kwargs))

    monkeypatch.setattr(
        "penguin.core.core_state_runtime.validate_path",
        _validate_path,
    )
    monkeypatch.setattr(
        "penguin.core.core_state_runtime.register_progress_callback",
        _register_progress_callback,
    )
    monkeypatch.setattr(
        "penguin.core.core_state_runtime.notify_progress",
        _notify_progress,
    )
    monkeypatch.setattr(
        "penguin.core.core_state_runtime.reset_context",
        _reset_context,
    )

    def callback(_iteration: int, _maximum: int, _message: str | None) -> None:
        return None

    workspace = Path("/tmp/penguin")

    core.validate_path(workspace)
    core.register_progress_callback(callback)
    core.notify_progress(1, 3, "step")
    core.reset_context()

    assert calls[0] == ("validate", (workspace,), {})
    assert calls[1] == ("register", (core, callback), {})
    assert calls[2] == ("notify", (core, 1, 3, "step"), {})
    assert calls[3][0] == "reset"
    assert calls[3][1] == (core,)
    assert sorted(calls[3][2]) == ["diagnostics_manager"]
