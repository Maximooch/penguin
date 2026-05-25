"""Core shim coverage for extracted checkpoint helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from penguin.core import PenguinCore


def test_checkpoint_facade_shims_delegate_to_runtime(monkeypatch) -> None:
    conversation_manager = SimpleNamespace()
    core = SimpleNamespace(conversation_manager=conversation_manager)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    facade_globals = PenguinCore.create_checkpoint.__globals__
    checkpoint_runtime = facade_globals["core_checkpoint_runtime"]

    def record(name: str, result: Any = None):
        def _inner(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, args, kwargs))
            return result

        return _inner

    def record_async(name: str, result: Any = None):
        async def _inner(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, args, kwargs))
            return result

        return _inner

    monkeypatch.setattr(
        checkpoint_runtime,
        "create_checkpoint",
        record_async("create_checkpoint", "ckpt_1"),
    )
    monkeypatch.setattr(
        checkpoint_runtime,
        "rollback_to_checkpoint",
        record_async("rollback_to_checkpoint", True),
    )
    monkeypatch.setattr(
        checkpoint_runtime,
        "branch_from_checkpoint",
        record_async("branch_from_checkpoint", "branch_1"),
    )
    monkeypatch.setattr(
        checkpoint_runtime,
        "list_checkpoints",
        record("list_checkpoints", [{"id": "ckpt_1"}]),
    )
    monkeypatch.setattr(
        checkpoint_runtime,
        "cleanup_old_checkpoints",
        record_async("cleanup_old_checkpoints", 2),
    )
    monkeypatch.setattr(
        checkpoint_runtime,
        "get_checkpoint_stats",
        record("get_checkpoint_stats", {"enabled": True}),
    )

    assert (
        asyncio.run(
            PenguinCore.create_checkpoint(
                core,
                name="save",
                description="before work",
            )
        )
        == "ckpt_1"
    )
    assert asyncio.run(PenguinCore.rollback_to_checkpoint(core, "ckpt_1")) is True
    assert (
        asyncio.run(
            PenguinCore.branch_from_checkpoint(
                core,
                "ckpt_1",
                name="branch",
                description="experiment",
            )
        )
        == "branch_1"
    )
    assert PenguinCore.list_checkpoints(core, session_id="session_a", limit=3) == [
        {"id": "ckpt_1"}
    ]
    assert asyncio.run(PenguinCore.cleanup_old_checkpoints(core)) == 2
    assert PenguinCore.get_checkpoint_stats(core) == {"enabled": True}

    assert calls == [
        (
            "create_checkpoint",
            (conversation_manager,),
            {"name": "save", "description": "before work"},
        ),
        ("rollback_to_checkpoint", (conversation_manager, "ckpt_1"), {}),
        (
            "branch_from_checkpoint",
            (conversation_manager, "ckpt_1"),
            {"name": "branch", "description": "experiment"},
        ),
        (
            "list_checkpoints",
            (conversation_manager,),
            {"session_id": "session_a", "limit": 3},
        ),
        ("cleanup_old_checkpoints", (conversation_manager,), {}),
        ("get_checkpoint_stats", (conversation_manager,), {}),
    ]
