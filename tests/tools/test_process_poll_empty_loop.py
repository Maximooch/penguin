"""Regressions for context/bugs/process-poll-empty-loop.md."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from penguin.engine import LoopState
from penguin.tools.process_runtime import ProcessRuntime
from penguin.tools.runtime import (
    ToolCall,
    execute_tool_calls_serially,
    hash_tool_output,
    tool_results_loop_identity,
)


@pytest.fixture
def runtime(tmp_path) -> Iterator[ProcessRuntime]:
    instance = ProcessRuntime(log_dir=tmp_path / "logs")
    try:
        yield instance
    finally:
        instance.cleanup()


@pytest.fixture
def child_command(tmp_path):
    """Run actual pipe I/O using this interpreter on every supported OS."""

    def command(source):
        script = tmp_path / "pipe child.py"
        script.write_text(source, encoding="utf-8")
        argv = [sys.executable, "-u", str(script)]
        return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)

    return command


def _wait_for_stdout(
    runtime: ProcessRuntime, process_id: str, sequence: int = 1
) -> None:
    """Synchronize with the child without consuming its output."""
    record = runtime._processes[process_id]
    with record.changed:
        assert record.changed.wait_for(lambda: record.next_sequence > sequence, 3)


def test_first_default_poll_recovers_ready_output(
    runtime: ProcessRuntime, child_command
) -> None:
    started = runtime.start(child_command("print('hello', flush=True); input()"))
    process_id = started["process_id"]
    _wait_for_stdout(runtime, process_id)

    polled = runtime.poll(process_id)

    assert polled["process_status"] == "running"
    assert "hello" in polled["output"]
    assert runtime.poll(process_id, since_sequence=0)["output"] == polled["output"]


@pytest.mark.parametrize("after_output", [False, True])
def test_returned_cursor_does_not_skip_output(
    runtime: ProcessRuntime, after_output: bool, child_command
) -> None:
    started = runtime.start(
        child_command(
            "input(); print('first', flush=True); "
            "input(); print('second', flush=True); input()"
        )
    )
    process_id = started["process_id"]
    cursor = started["next_sequence"]
    if after_output:
        runtime.write_stdin(process_id, "go\n")
        _wait_for_stdout(runtime, process_id)
        first = runtime.poll(process_id)
        assert "first" in first["output"]
        cursor = first["next_sequence"]

    runtime.write_stdin(process_id, "go\n")
    _wait_for_stdout(runtime, process_id, 2 if after_output else 1)
    polled = runtime.poll(process_id, since_sequence=cursor)
    expected = "second" if after_output else "first"

    # Prove the bytes were captured before asserting cursor-based delivery.
    assert expected in runtime.poll(process_id, since_sequence=0)["output"]
    assert expected in polled["output"]


def test_running_process_can_wait_through_three_empty_polls(
    runtime: ProcessRuntime,
    child_command,
) -> None:
    process_id = runtime.start(child_command("input()"))["process_id"]
    state = LoopState()
    for _ in range(3):
        polled = runtime.poll(process_id)
        assert polled["process_status"] == "running"
        assert polled["output"] == ""
        should_stop, reason = state.check_empty_tool_only("", [polled])
        assert (should_stop, reason) == (False, None)


@pytest.mark.asyncio
async def test_scheduler_preserves_running_process_metadata_and_nonempty_hash(
    runtime: ProcessRuntime,
    child_command,
) -> None:
    process_id = runtime.start(child_command("input()"))["process_id"]

    def execute_call(call: ToolCall) -> dict[str, Any]:
        return runtime.poll(call.arguments["process_id"])

    results = await execute_tool_calls_serially(
        [
            ToolCall(
                id="poll",
                name="process_poll",
                arguments={"process_id": process_id},
                source="responses",
            )
        ],
        execute_call,
    )

    result = results[0]
    assert "status=running" in result.output
    assert result.structured_output["process_status"] == "running"
    assert result.output_hash != hash_tool_output("")
    assert "e3b0c44298fc" not in tool_results_loop_identity(results).summary


def test_quiet_process_has_no_implicit_turn_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr("penguin.tools.process_wait.time.monotonic", lambda: now[0])
    state = LoopState()
    result = {
        "action": "process_poll",
        "status": "completed",
        "process_status": "running",
        "process_id": "proc",
        "next_sequence": 0,
    }
    for elapsed in (0, 120, 600, 3600):
        now[0] = elapsed
        assert state.check_empty_tool_only("", [result]) == (False, None)
    summary = tool_results_loop_identity([result]).summary
    assert "tool_status=completed" in summary
    assert "process_status=running" in summary
    assert "process_id=proc" in summary


def test_terminal_transition_changes_loop_identity_without_new_output() -> None:
    running = {
        "action": "process_poll",
        "status": "completed",
        "process_status": "running",
        "process_id": "proc",
        "next_sequence": 0,
        "result": "No new output.",
    }
    exited = {**running, "process_status": "exited", "returncode": 0}
    assert (
        tool_results_loop_identity([running]).fingerprint
        != tool_results_loop_identity([exited]).fingerprint
    )
    summary = tool_results_loop_identity([exited]).summary
    assert "process_status=exited" in summary
    assert "returncode=0" in summary
    state = LoopState()
    for _ in range(4):
        assert state.check_empty_tool_only("", [running]) == (False, None)
    assert state.check_empty_tool_only("", [exited]) == (False, None)
