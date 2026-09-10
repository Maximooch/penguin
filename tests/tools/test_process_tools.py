"""Managed command, ownership, notification, and cancellation contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime.process_notifications import prepare_process_step
from penguin.system.execution_context import ExecutionContext
from penguin.tools.process_runtime import ProcessRuntime
from penguin.tools.process_tools import ProcessTools
from penguin.tools.tool_manager import ToolManager

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[ToolManager]:
    monkeypatch.setenv("PENGUIN_YOLO", "1")
    monkeypatch.delenv("PENGUIN_TOOL_TIMEOUT", raising=False)
    result = ToolManager({}, lambda *_args: None, fast_startup=True)
    result._process_runtime = ProcessRuntime(log_dir=tmp_path)
    yield result
    result.process_tools.cleanup()


def test_command_returns_output_or_resumable_handle(manager: ToolManager) -> None:
    context = {"session_id": "one", "agent_id": "agent"}
    quick = manager.execute_tool(
        "execute_command", {"command": "printf 'hello\\n'"}, context
    )
    assert quick["process_status"] == "exited"
    assert quick["returncode"] == 0
    assert "hello" in quick["output"]
    slow = manager.execute_tool(
        "execute_command",
        {"command": "read go; printf 'done\\n'", "yield_time_ms": 0},
        context,
    )
    assert slow["process_status"] == "running"
    pid = slow["process_id"]
    manager.execute_tool(
        "process_write_stdin", {"process_id": pid, "text": "go\n"}, context
    )
    final = manager.process_runtime.poll(pid, wait_ms=2000, wait_for_exit=True)
    assert final["process_status"] == "exited"
    assert "done" in final["output"]


def test_explicit_timeout_preserves_partial_output(manager: ToolManager) -> None:
    result = manager.execute_tool(
        "execute_command",
        {
            "command": "printf 'before-timeout\\n'; read go",
            "timeout_seconds": 0.15,
            "yield_time_ms": 2000,
        },
    )
    assert result["status"] == "error"
    assert result["error"] == "timeout"
    assert result["completion_reason"] == "timeout"
    assert "before-timeout" in result["output"]


def test_timeout_continues_after_yield(manager: ToolManager) -> None:
    result = manager.execute_tool(
        "execute_command",
        {
            "command": "read go",
            "timeout_seconds": 0.1,
            "yield_time_ms": 0,
        },
    )
    final = manager.process_runtime.poll(
        result["process_id"], wait_ms=2000, wait_for_exit=True
    )
    assert final["process_status"] == "exited"
    assert final["error"] == "timeout"


@pytest.mark.parametrize(
    "operation", ["process_poll", "process_stop", "process_write_stdin"]
)
def test_other_sessions_cannot_access_process(
    manager: ToolManager, operation: str
) -> None:
    started = manager.execute_tool(
        "process_start", {"command": "read go"}, {"session_id": "one"}
    )
    result = manager.execute_tool(
        operation,
        {"process_id": started["process_id"], "text": "go\n"},
        {"session_id": "two"},
    )
    assert result["error"] == "unknown_process_id"
    assert (
        manager.process_runtime.poll(started["process_id"])["process_status"]
        == "running"
    )


def test_command_retry_returns_same_process_and_output(manager: ToolManager) -> None:
    context = {"session_id": "one", "tool_call_id": "call-1"}
    args = {"command": "printf 'once\\n'", "yield_time_ms": 2000}
    first = manager.execute_tool("execute_command", args, context)
    retry = manager.execute_tool("execute_command", args, context)
    assert retry == first
    assert len(manager.process_runtime._processes) == 1


@pytest.mark.asyncio
async def test_completion_is_delivered_once_to_owning_conversation(
    manager: ToolManager,
) -> None:
    messages: list[tuple] = []
    core = SimpleNamespace(emit_ui_event=AsyncMock())
    cm = SimpleNamespace(
        core=core,
        conversation=SimpleNamespace(
            add_message=lambda *args, **kwargs: messages.append((args, kwargs))
        ),
    )
    context = ExecutionContext(session_id="one", agent_id="agent")
    prepare_process_step(manager, cm, context)
    result = manager.execute_tool(
        "execute_command", {"command": "read go", "yield_time_ms": 0}, context.as_dict()
    )
    pid = result["process_id"]
    manager.execute_tool(
        "process_write_stdin", {"process_id": pid, "text": "go\n"}, context.as_dict()
    )
    await asyncio.to_thread(manager.process_runtime._processes[pid].reader.join, 2)
    assert len(manager.process_tools.pending(("one", "agent"))) == 1
    other = SimpleNamespace(
        core=None,
        conversation=SimpleNamespace(
            add_message=lambda *args, **kwargs: pytest.fail("wrong conversation")
        ),
    )
    prepare_process_step(
        manager, other, ExecutionContext(session_id="two", agent_id="agent")
    )
    prepare_process_step(manager, cm, context)
    prepare_process_step(manager, cm, context)
    assert len(messages) == 1
    assert pid in messages[0][0][1]
    await asyncio.sleep(0)
    assert core.emit_ui_event.await_count >= 1
    for call in core.emit_ui_event.await_args_list:
        assert call.args[1]["properties"]["sessionID"] == "one"


@pytest.mark.asyncio
async def test_cancellation_stops_command_without_blocking_loop(
    manager: ToolManager,
) -> None:
    task = asyncio.create_task(
        manager.execute_tool_async(
            "execute_command",
            {
                "command": "read go",
                "yield_time_ms": 60000,
            },
        )
    )
    for _ in range(200):
        if manager.process_runtime._processes:
            break
        await asyncio.sleep(0.01)
    assert manager.process_runtime._processes
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)
    assert all(
        record.process.poll() is not None
        for record in manager.process_runtime._processes.values()
    )


def test_completion_racing_with_observation_is_not_requeued(
    manager: ToolManager,
) -> None:
    service = manager.process_tools
    owner = ("one", "agent")
    service.acknowledge(owner, "proc")
    service._on_event(
        "completed", {"process_id": "proc", "session_id": "one", "agent_id": "agent"}
    )
    assert service.pending(owner) == []


@pytest.mark.asyncio
async def test_native_scheduler_quiet_waits_then_delivers_final_output(
    manager: ToolManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from penguin.engine import LoopState
    from penguin.llm.runtime import execute_pending_tool_calls
    from penguin.system.execution_context import execution_context_scope

    monkeypatch.setattr("penguin.tools.process_tools.MIN_PROCESS_WAIT_MS", 1)
    records = []

    class Provider:
        def __init__(self) -> None:
            self.pending: list[dict] = []

        def get_and_clear_pending_tool_calls(self) -> list[dict]:
            calls, self.pending = self.pending, []
            return calls

    provider = Provider()

    async def call(
        name: str, call_id: str, arguments: dict[str, Any]
    ) -> list[dict[str, Any]]:
        provider.pending = [
            {"name": name, "call_id": call_id, "arguments": json.dumps(arguments)}
        ]
        return await execute_pending_tool_calls(
            api_client=SimpleNamespace(client_handler=provider),
            tool_manager=manager,
            persist_action_result=lambda result, context: records.append(
                (result, context)
            ),
        )

    with execution_context_scope(
        ExecutionContext(session_id="native", agent_id="agent")
    ):
        started = await call(
            "execute_command",
            "start",
            {"command": "read go; printf 'done\\n'", "yield_time_ms": 0},
        )
        pid = started[0]["process_id"]
        state = LoopState()
        for index in range(4):
            polled = await call(
                "process_poll", f"poll-{index}", {"process_id": pid, "wait_ms": 0}
            )
            assert polled[0]["process_status"] == "running"
            assert state.check_empty_tool_only("", polled) == (False, None)
        await call("process_write_stdin", "write", {"process_id": pid, "text": "go\n"})
        await asyncio.to_thread(manager.process_runtime._processes[pid].reader.join, 2)
        final = await call("process_poll", "final", {"process_id": pid})
        assert final[0]["process_status"] == "exited"
        assert "done" in final[0]["result"]
        retry = await call("process_poll", "final", {"process_id": pid})
        assert retry[0]["result"] == final[0]["result"]
    assert len(manager.process_runtime._processes) == 1
    assert records[-1][1]["tool_call_id"] == "final"


def test_invalid_command_parameters_do_not_launch_process(manager: ToolManager) -> None:
    for args in ({"timeout_seconds": -1}, {"yield_time_ms": -1}, {"max_chars": -1}):
        result = manager.execute_tool("execute_command", {"command": "read go", **args})
        assert result["status"] == "error"
    assert not manager.process_runtime._processes


@pytest.mark.asyncio
async def test_cancelled_poll_leaves_background_process_running(
    manager: ToolManager,
) -> None:
    started = manager.execute_tool("process_start", {"command": "read go"})
    task = asyncio.create_task(
        manager.execute_tool_async(
            "process_poll",
            {
                "process_id": started["process_id"],
                "wait_ms": 60000,
            },
        )
    )
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert (
        manager.process_runtime.poll(started["process_id"])["process_status"]
        == "running"
    )


def test_registry_reaps_observed_results_and_retains_logs(tmp_path: Path) -> None:
    runtime = ProcessRuntime(log_dir=tmp_path, max_processes=1)
    service = ProcessTools(runtime)
    try:
        first = service.execute("execute_command", {"command": "printf first"}, {})
        second = service.execute("execute_command", {"command": "printf second"}, {})
        assert second["process_status"] == "exited"
        assert first["process_id"] not in runtime._processes
        assert (tmp_path / first["log_path"]).read_text() == "first"
    finally:
        service.cleanup()


@pytest.mark.parametrize("tool_name", ["execute_command", "process_start"])
@pytest.mark.parametrize("directory_kind", ["missing", "none", "invalid", "override"])
def test_launch_uses_resolved_execution_root(
    manager: ToolManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    directory_kind: str,
) -> None:
    from penguin.system.execution_context import execution_context_scope

    root = tmp_path / "project"
    root.mkdir()
    override = tmp_path / "override"
    override.mkdir()
    # Preserve process-wide configuration changed by the public root setters.
    monkeypatch.setenv("PENGUIN_CWD", str(tmp_path))
    monkeypatch.setenv("PENGUIN_WRITE_ROOT", "project")
    manager.set_project_root(root)
    manager.set_execution_root("project")
    arguments = {"command": "pwd"}
    if directory_kind == "override":
        arguments["cwd"] = str(override)
    expected = override if directory_kind == "override" else root
    if directory_kind == "missing":
        result = manager.execute_tool(tool_name, arguments, {"session_id": "root"})
    else:
        directory = str(tmp_path / "missing") if directory_kind == "invalid" else None
        with execution_context_scope(
            ExecutionContext(session_id="root", directory=directory)
        ):
            result = manager.execute_tool(tool_name, arguments)
    final = manager.process_runtime.poll(
        result["process_id"], wait_ms=2000, wait_for_exit=True
    )
    assert final["returncode"] == 0
    assert final["cwd"] == str(expected.resolve())
    assert str(expected.resolve()) in final["output"]


@pytest.mark.parametrize("exit_code", [0, 7])
def test_terminal_outcome_is_identical_after_yield_or_immediate_completion(
    manager: ToolManager,
    exit_code: int,
) -> None:
    immediate = manager.execute_tool(
        "execute_command", {"command": f"exit {exit_code}"}
    )
    started = manager.execute_tool(
        "execute_command",
        {
            "command": f"read go; exit {exit_code}",
            "yield_time_ms": 0,
        },
    )
    pid = started["process_id"]
    manager.execute_tool("process_write_stdin", {"process_id": pid, "text": "go\n"})
    manager.process_runtime._processes[pid].reader.join(timeout=2)
    notifications = manager.process_tools.pending(("", "agent"))
    resumed = manager.execute_tool("process_poll", {"process_id": pid})
    expected_status, expected_error = (
        ("completed", None) if exit_code == 0 else ("error", "command_failed")
    )
    assert len(notifications) == 1
    for result in (immediate, resumed, notifications[0]):
        assert result["process_status"] == "exited"
        assert result["returncode"] == exit_code
        assert result["status"] == expected_status
        assert result["error"] == expected_error
    notice = manager.process_runtime.poll(pid)
    assert notice["status"] == expected_status
