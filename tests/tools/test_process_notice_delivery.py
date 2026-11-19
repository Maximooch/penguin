"""Background-process notices are delivered once and their sinks do not pile up.

Covers SM-25: a completion notice was peeked and only later acknowledged, so
two steps could both persist it; event listeners were bound every step and
never released; and cancelling a process tool waited on its worker thread
without a limit.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime.process_notifications import (
    prepare_process_step,
    process_session_scope,
)
from penguin.system.execution_context import ExecutionContext
from penguin.tools.process_runtime import ProcessRuntime
from penguin.tools.tool_manager import ToolManager

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

OWNER = ("one", "agent")


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ToolManager]:
    monkeypatch.setenv("PENGUIN_YOLO", "1")
    monkeypatch.delenv("PENGUIN_TOOL_TIMEOUT", raising=False)
    result = ToolManager({}, lambda *_args: None, fast_startup=True)
    result._process_runtime = ProcessRuntime(log_dir=tmp_path)
    yield result
    result.process_tools.cleanup()


def _notice(process_id: str = "proc_done") -> dict[str, Any]:
    return {
        "process_id": process_id,
        "session_id": OWNER[0],
        "agent_id": OWNER[1],
        "returncode": 0,
        "completion_reason": "exited",
    }


def _conversation(add_message: Any) -> SimpleNamespace:
    return SimpleNamespace(
        core=None, conversation=SimpleNamespace(add_message=add_message)
    )


def test_two_steps_at_once_persist_a_notice_once(manager: ToolManager) -> None:
    manager.process_tools._on_event("completed", _notice())
    context = ExecutionContext(session_id=OWNER[0], agent_id=OWNER[1])
    messages: list[str] = []
    first_inside = threading.Event()
    release_first = threading.Event()
    first: threading.Thread

    def add_message(_role: str, content: str, **_kwargs: Any) -> None:
        messages.append(content)
        if threading.current_thread() is first:
            first_inside.set()
            release_first.wait(2)

    cm = _conversation(add_message)
    first = threading.Thread(target=prepare_process_step, args=(manager, cm, context))
    first.start()
    assert first_inside.wait(2)
    prepare_process_step(manager, cm, context)
    release_first.set()
    first.join(timeout=2)

    assert len(messages) == 1


def test_a_notice_that_failed_to_persist_is_delivered_next_step(
    manager: ToolManager,
) -> None:
    manager.process_tools._on_event("completed", _notice())
    context = ExecutionContext(session_id=OWNER[0], agent_id=OWNER[1])

    def failing(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    with pytest.raises(OSError):
        prepare_process_step(manager, _conversation(failing), context)
    messages: list[str] = []
    prepare_process_step(
        manager, _conversation(lambda _role, text, **_k: messages.append(text)), context
    )

    assert len(messages) == 1


class _Engine:
    current_agent_id = OWNER[1]

    def __init__(self, manager: ToolManager, emit: AsyncMock) -> None:
        self.manager = manager
        self.cm = SimpleNamespace(
            core=SimpleNamespace(emit_ui_event=emit),
            conversation=SimpleNamespace(add_message=lambda *_a, **_k: None),
        )

    def _resolve_components(self, _agent_id: str | None) -> tuple[Any, ...]:
        return self.cm, None, self.manager, None

    def _conversation_session_id(self, _cm: Any) -> str:
        return OWNER[0]


@pytest.mark.asyncio
async def test_a_step_with_no_process_leaves_no_listener(manager: ToolManager) -> None:
    @process_session_scope
    async def step(_engine: Any) -> str:
        return "answered"

    assert await step(_Engine(manager, AsyncMock())) == "answered"

    assert OWNER not in manager.process_tools._listeners


@pytest.mark.asyncio
async def test_a_listener_outlives_its_step_only_until_the_process_ends(
    manager: ToolManager,
) -> None:
    emit = AsyncMock()
    started: dict[str, Any] = {}

    @process_session_scope
    async def step(_engine: Any) -> None:
        started.update(
            manager.execute_tool(
                "process_start",
                {"command": "read go", "stdin": True},
                {"session_id": OWNER[0], "agent_id": OWNER[1]},
            )
        )

    await step(_Engine(manager, emit))
    assert OWNER in manager.process_tools._listeners

    manager.process_runtime.write_stdin(started["process_id"], "go\n")
    for _ in range(300):
        kinds = [call.args[1]["type"] for call in emit.await_args_list]
        if OWNER not in manager.process_tools._listeners and any(
            kind == "notification.process.completed" for kind in kinds
        ):
            break
        await asyncio.sleep(0.01)

    assert OWNER not in manager.process_tools._listeners
    assert "notification.process.completed" in [
        call.args[1]["type"] for call in emit.await_args_list
    ]


@pytest.mark.asyncio
async def test_cancelling_a_stuck_process_tool_returns_within_the_grace(
    manager: ToolManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "penguin.tools.async_dispatch.PROCESS_CANCEL_GRACE_SECONDS", 0.2, raising=False
    )
    stuck = threading.Event()
    entered = threading.Event()

    def blocked(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        entered.set()
        stuck.wait(10)
        return {"status": "completed"}

    monkeypatch.setattr(manager, "execute_tool", blocked)
    task = asyncio.create_task(
        manager.execute_tool_async("process_poll", {"process_id": "proc_x"})
    )
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    began = time.monotonic()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert time.monotonic() - began < 1.5
    finally:
        stuck.set()
