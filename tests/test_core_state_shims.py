"""Core shim coverage for extracted core state helpers."""

from __future__ import annotations

import asyncio
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

    def _reset_state(*args: Any, **kwargs: Any) -> None:
        calls.append(("reset_state", args, kwargs))

    def _list_context_files(*args: Any, **kwargs: Any) -> list[dict[str, str]]:
        calls.append(("list_context_files", args, kwargs))
        return [{"path": "README.md"}]

    def _create_snapshot(*args: Any, **kwargs: Any) -> str:
        calls.append(("create_snapshot", args, kwargs))
        return "snapshot_1"

    def _restore_snapshot(*args: Any, **kwargs: Any) -> bool:
        calls.append(("restore_snapshot", args, kwargs))
        return True

    def _branch_from_snapshot(*args: Any, **kwargs: Any) -> str:
        calls.append(("branch_from_snapshot", args, kwargs))
        return "snapshot_branch"

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
    monkeypatch.setattr(
        "penguin.core.core_state_runtime.reset_state",
        _reset_state,
    )
    monkeypatch.setattr(
        "penguin.core.core_state_runtime.list_context_files",
        _list_context_files,
    )
    monkeypatch.setattr(
        "penguin.core.core_state_runtime.create_snapshot",
        _create_snapshot,
    )
    monkeypatch.setattr(
        "penguin.core.core_state_runtime.restore_snapshot",
        _restore_snapshot,
    )
    monkeypatch.setattr(
        "penguin.core.core_state_runtime.branch_from_snapshot",
        _branch_from_snapshot,
    )

    def callback(_iteration: int, _maximum: int, _message: str | None) -> None:
        return None

    workspace = Path("/tmp/penguin")

    core.validate_path(workspace)
    core.register_progress_callback(callback)
    core.notify_progress(1, 3, "step")
    core.reset_context()
    asyncio.run(core.reset_state())
    assert core.list_context_files() == [{"path": "README.md"}]
    assert core.create_snapshot({"name": "save"}) == "snapshot_1"
    assert core.restore_snapshot("snapshot_1") is True
    assert (
        core.branch_from_snapshot("snapshot_1", {"name": "branch"}) == "snapshot_branch"
    )

    assert calls[0] == ("validate", (workspace,), {})
    assert calls[1] == ("register", (core, callback), {})
    assert calls[2] == ("notify", (core, 1, 3, "step"), {})
    assert calls[3][0] == "reset"
    assert calls[3][1] == (core,)
    assert sorted(calls[3][2]) == ["diagnostics_manager"]
    assert calls[4][0] == "reset_state"
    assert calls[4][1] == (core,)
    assert sorted(calls[4][2]) == ["diagnostics_manager"]
    assert calls[5] == ("list_context_files", (core,), {})
    assert calls[6] == ("create_snapshot", (core,), {"meta": {"name": "save"}})
    assert calls[7] == ("restore_snapshot", (core, "snapshot_1"), {})
    assert calls[8] == (
        "branch_from_snapshot",
        (core, "snapshot_1"),
        {"meta": {"name": "branch"}},
    )
