from __future__ import annotations

import subprocess
import time
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from penguin.tools.process_runtime import ManagedProcess, ProcessRuntime
from penguin.tools.runtime import ToolCall, tool_call_with_schedule_metadata
from penguin.tools.tool_manager import ToolManager


def _poll_until_output(
    runtime: ProcessRuntime,
    process_id: str,
    expected: str,
    *,
    timeout: float = 2.0,
) -> dict:
    deadline = time.time() + timeout
    snapshot: dict = {}
    while time.time() < deadline:
        snapshot = runtime.poll(process_id)
        if expected in snapshot.get("output", ""):
            return snapshot
        time.sleep(0.05)
    return snapshot


def _poll_until_status(
    runtime: ProcessRuntime,
    process_id: str,
    expected: str,
    *,
    timeout: float = 2.0,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    snapshot: dict[str, Any] = {}
    while time.time() < deadline:
        snapshot = runtime.poll(process_id)
        if snapshot.get("process_status") == expected:
            return snapshot
        time.sleep(0.05)
    return snapshot


def _poll_manager_until_output(
    manager: ToolManager,
    process_id: str,
    expected: str,
    *,
    timeout: float = 2.0,
) -> dict:
    deadline = time.time() + timeout
    snapshot: dict = {}
    while time.time() < deadline:
        snapshot = manager.execute_tool("process_poll", {"process_id": process_id})
        assert isinstance(snapshot, dict)
        if expected in snapshot.get("output", ""):
            return snapshot
        time.sleep(0.05)
    return snapshot


def test_process_runtime_start_poll_and_exit() -> None:
    runtime = ProcessRuntime()

    started = runtime.start("printf 'hello\\n'", env={"PENGUIN_TEST_FLAG": "1"})
    process_id = started["process_id"]
    polled = _poll_until_output(runtime, process_id, "hello")

    assert polled["process_id"] == process_id
    assert polled["env_keys"] == ["PENGUIN_TEST_FLAG"]
    assert "hello" in polled["output"]
    assert polled["next_sequence"] >= 1


def test_process_runtime_writes_stdin_and_stops() -> None:
    runtime = ProcessRuntime()

    started = runtime.start("cat")
    process_id = started["process_id"]
    write_result = runtime.write_stdin(process_id, "ping\n")
    polled = _poll_until_output(runtime, process_id, "ping")
    stopped = runtime.stop(process_id, mode="terminate")

    assert write_result["process_status"] == "running"
    assert "ping" in polled["output"]
    assert stopped["process_status"] == "exited"


def test_process_runtime_captures_stderr() -> None:
    runtime = ProcessRuntime()

    started = runtime.start("printf 'problem\\n' >&2")
    process_id = started["process_id"]
    polled = _poll_until_output(runtime, process_id, "problem")

    assert "[stderr] problem" in polled["output"]


def test_process_runtime_retains_bounded_event_history() -> None:
    runtime = ProcessRuntime(max_events_per_process=2)

    process_id = runtime.start("cat")["process_id"]
    for value in ("one", "two", "three"):
        runtime.write_stdin(process_id, f"{value}\n")
        _poll_until_output(runtime, process_id, value)

    polled = runtime.poll(process_id, since_sequence=0)
    runtime.stop(process_id)

    assert "one" not in polled["output"]
    assert "two" in polled["output"]
    assert "three" in polled["output"]


def test_process_poll_output_is_bounded() -> None:
    runtime = ProcessRuntime()

    process_id = runtime.start("printf 'abcdef\\n'")["process_id"]
    polled = _poll_until_output(runtime, process_id, "abcdef")
    bounded = runtime.poll(process_id, since_sequence=0, max_chars=4)
    empty = runtime.poll(process_id, since_sequence=0, max_chars=0)

    assert "abcdef" in polled["output"]
    assert len(bounded["output"]) <= 4
    assert bounded["truncated"] is True
    assert empty["output"] == ""
    assert empty["truncated"] is True


def test_process_runtime_unknown_process_returns_error() -> None:
    runtime = ProcessRuntime()

    polled = runtime.poll("missing")
    wrote = runtime.write_stdin("missing", "text")
    stopped = runtime.stop("missing")

    assert polled["status"] == "error"
    assert wrote["error"] == "unknown_process_id"
    assert stopped["error"] == "unknown_process_id"


def test_process_runtime_rejects_stdin_after_process_exits() -> None:
    runtime = ProcessRuntime()

    process_id = runtime.start("printf 'done\\n'")["process_id"]
    exited = _poll_until_status(runtime, process_id, "exited")
    wrote = runtime.write_stdin(process_id, "too late\n")

    assert exited["process_status"] == "exited"
    assert wrote["status"] == "error"
    assert wrote["error"] == "process_not_running"


def test_process_runtime_captures_large_stdout_and_stderr() -> None:
    runtime = ProcessRuntime()

    command = (
        "python3 -c 'import sys; "
        'sys.stdout.write("O" * 5000); sys.stdout.flush(); '
        'sys.stderr.write("E" * 5000); sys.stderr.flush()\''
    )
    process_id = runtime.start(command)["process_id"]
    polled = _poll_until_status(runtime, process_id, "exited")

    assert polled["process_status"] == "exited"
    assert polled["output"].count("O") == 5000
    assert polled["output"].count("E") == 5000
    assert "[stdout]" in polled["output"]
    assert "[stderr]" in polled["output"]


def test_process_runtime_captures_interleaved_streams() -> None:
    runtime = ProcessRuntime()

    command = (
        "python3 -c 'import sys, time; "
        'sys.stdout.write("out1\\\\n"); sys.stdout.flush(); '
        "time.sleep(0.02); "
        'sys.stderr.write("err1\\\\n"); sys.stderr.flush(); '
        "time.sleep(0.02); "
        'sys.stdout.write("out2\\\\n"); sys.stdout.flush(); '
        'sys.stderr.write("err2\\\\n"); sys.stderr.flush()\''
    )
    process_id = runtime.start(command)["process_id"]
    polled = _poll_until_status(runtime, process_id, "exited")

    assert "[stdout]" in polled["output"]
    assert "[stderr]" in polled["output"]
    assert "out1" in polled["output"]
    assert "out2" in polled["output"]
    assert "err1" in polled["output"]
    assert "err2" in polled["output"]


class _TimeoutThenKillProcess:
    stdin = None
    stdout = None
    stderr = None

    def __init__(self) -> None:
        self.terminated = False
        self.killed = False
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        if not self.killed:
            raise subprocess.TimeoutExpired("ignore TERM", timeout)
        return -9

    def send_signal(self, signal_number: int) -> None:
        del signal_number
        self.terminate()


class _BrokenStdin:
    def write(self, text: str) -> int:
        del text
        raise BrokenPipeError("stdin closed")

    def flush(self) -> None:
        raise AssertionError("flush should not run after failed write")


class _BrokenStdinProcess:
    stdin = _BrokenStdin()
    stdout = None
    stderr = None

    def poll(self) -> int | None:
        return None


def test_process_runtime_write_stdin_returns_error_for_broken_pipe() -> None:
    runtime = ProcessRuntime()
    runtime._processes["broken"] = ManagedProcess(
        process_id="broken",
        command="closed stdin",
        cwd="/tmp",
        process=cast(Any, _BrokenStdinProcess()),
    )

    result = runtime.write_stdin("broken", "ping\n")

    assert result["status"] == "error"
    assert result["error"].startswith("stdin_write_failed:")
    assert "stdin closed" in result["error"]


def test_process_runtime_terminate_timeout_escalates_to_kill() -> None:
    runtime = ProcessRuntime()
    process = _TimeoutThenKillProcess()
    runtime._processes["stubborn"] = ManagedProcess(
        process_id="stubborn",
        command="ignore TERM",
        cwd="/tmp",
        process=cast(Any, process),
    )

    stopped = runtime.stop("stubborn", timeout=0.001)

    assert process.terminated is True
    assert process.killed is True
    assert stopped["process_status"] == "exited"
    assert stopped["returncode"] == -9


def test_process_runtime_cleanup_stops_and_removes_managed_processes() -> None:
    runtime = ProcessRuntime()

    process_id = runtime.start("cat")["process_id"]
    cleanup = runtime.cleanup(timeout=0.5)
    polled = runtime.poll(process_id)

    assert cleanup["status"] == "completed"
    assert cleanup["stopped"] == [process_id]
    assert cleanup["removed"] == [process_id]
    assert polled["status"] == "error"
    assert polled["error"] == "unknown_process_id"


def test_process_runtime_start_failure_returns_error(tmp_path: Path) -> None:
    runtime = ProcessRuntime()

    failed = runtime.start("pwd", cwd=str(tmp_path / "missing"))

    assert failed["status"] == "error"
    assert failed["error"].startswith("start_failed:")


def test_tool_manager_exposes_process_runtime_metadata() -> None:
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)

    start_metadata = manager.get_tool_runtime_metadata("process_start")
    poll_metadata = manager.get_tool_runtime_metadata("process_poll")

    assert start_metadata["long_running"] is True
    assert start_metadata["streams_output"] is True
    assert start_metadata["parallel_safe"] is False
    assert poll_metadata["mutates_state"] is False
    assert poll_metadata["streams_output"] is True


def test_tool_manager_executes_process_runtime_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_YOLO", "1")
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)

    started = manager.execute_tool(
        "process_start",
        {"command": "printf 'tool\\n'", "env": {"PENGUIN_TOOL_TEST": "1"}},
    )
    assert isinstance(started, dict)
    process_id = started["process_id"]
    polled = _poll_manager_until_output(manager, process_id, "tool")

    assert polled["process_id"] == process_id
    assert polled["env_keys"] == ["PENGUIN_TOOL_TEST"]
    assert "tool" in polled["output"]


def test_tool_manager_marks_core_inspection_tools_read_only() -> None:
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)

    for tool_name in (
        "read_file",
        "list_files",
        "find_file",
        "grep_search",
        "memory_search",
        "get_file_map",
        "read_image",
    ):
        metadata = manager.get_tool_runtime_metadata(tool_name)
        call = tool_call_with_schedule_metadata(
            ToolCall(
                id=tool_name,
                name=tool_name,
                arguments={"path": "README.md"},
                source="responses",
            ),
            metadata,
        )

        assert metadata["mutates_state"] is False
        assert metadata["requires_approval"] is False
        assert metadata["parallel_safe"] is True
        assert call.effect == "read"
        assert call.mutates_state is False
