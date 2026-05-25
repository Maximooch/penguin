from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from penguin.tools.process_runtime import ProcessRuntime
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
