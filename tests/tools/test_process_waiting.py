"""Local process and loop-policy contracts without a live provider."""

from __future__ import annotations

import shlex
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from penguin.engine import LoopState
from penguin.tools.process_runtime import MAX_BUFFER_CHARS, ProcessRuntime

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[ProcessRuntime]:
    instance = ProcessRuntime(log_dir=tmp_path)
    try:
        yield instance
    finally:
        instance.cleanup()


def test_capture_runs_without_polling_and_spills_to_log(
    runtime: ProcessRuntime,
) -> None:
    size = MAX_BUFFER_CHARS * 2
    command = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
        f"import sys; sys.stdout.write('O' * {size}); sys.stderr.write('E' * {size})"
    )
    process_id = runtime.start(command)["process_id"]
    record = runtime._processes[process_id]
    # This would deadlock if draining depended on polls or one pipe starving the other.
    assert record.process.wait(timeout=5) == 0
    record.reader.join(timeout=3)
    result = runtime.poll(process_id)
    assert result["process_status"] == "exited"
    assert result["history_lost"] is True
    assert result["truncated"] is True
    assert record.buffered_chars <= MAX_BUFFER_CHARS
    log = Path(result["log_path"]).read_text()
    assert log.count("O") == log.count("E") == size


def test_wait_deadline_does_not_kill_quiet_process(runtime: ProcessRuntime) -> None:
    process_id = runtime.start("read done")["process_id"]
    start = time.monotonic()
    result = runtime.poll(process_id, wait_ms=50)
    assert time.monotonic() - start >= 0.04
    assert result["process_status"] == "running"
    assert result["no_new_output"] is True
    runtime.write_stdin(process_id, "done\n")
    assert runtime.poll(process_id, wait_ms=1000)["process_status"] == "exited"


def test_consumers_and_request_retries_do_not_lose_output(
    runtime: ProcessRuntime,
) -> None:
    process_id = runtime.start("printf 'one\\n'; read done")["process_id"]
    first = runtime.poll(
        process_id, since_sequence=None, request_id="call-1", wait_ms=1000
    )
    assert "one" in first["output"]
    assert runtime.poll(process_id, since_sequence=None, request_id="call-1") == first
    assert runtime.poll(process_id, since_sequence=None)["output"] == ""
    assert (
        "one"
        in runtime.poll(process_id, since_sequence=None, consumer_id="ui")["output"]
    )
    assert "one" in runtime.poll(process_id, since_sequence=0)["output"]


def test_zero_size_read_does_not_advance_cursor(runtime: ProcessRuntime) -> None:
    process_id = runtime.start("printf 'one\\n'; read done")["process_id"]
    peek = runtime.poll(process_id, since_sequence=None, max_chars=0, wait_ms=1000)
    assert peek["next_sequence"] == 0
    assert "one" in runtime.poll(process_id, since_sequence=None)["output"]


def test_exit_does_not_wait_forever_for_descendant_pipe(
    runtime: ProcessRuntime,
) -> None:
    process_id = runtime.start("sleep 60 & printf 'done\\n'")["process_id"]
    record = runtime._processes[process_id]
    record.reader.join(timeout=3)
    result = runtime.poll(process_id)
    assert result["process_status"] == "exited"
    assert result["streams_closed"] is False
    assert "done" in result["output"]
    # cleanup also kills the surviving member of this process group.


def test_stop_signals_owned_process_group(
    runtime: ProcessRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    process_id = runtime.start("sleep 60 & wait")["process_id"]
    calls: list[int] = []
    killpg = os.killpg

    def signal_group(pid: int, sig: int) -> None:
        calls.append(pid)
        killpg(pid, sig)

    monkeypatch.setattr(os, "killpg", signal_group)
    stopped = runtime.stop(process_id, timeout=0.2)
    assert stopped["process_status"] == "exited"
    assert calls and set(calls) == {runtime._processes[process_id].process.pid}


def test_process_wait_budget_resets_only_on_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    monkeypatch.setattr("penguin.tools.process_wait.time.monotonic", lambda: now[0])
    state = LoopState()
    result = {
        "action": "process",
        "status": "completed",
        "process_status": "running",
        "process_id": "proc",
        "next_sequence": 0,
    }
    for value in (0, 10, 60, 119):
        now[0] = value
        assert state.check_empty_tool_only("", [result]) == (False, None)
    result["next_sequence"] = 1
    now[0] = 120
    assert state.check_empty_tool_only("", [result]) == (False, None)
    now[0] = 240
    assert state.check_empty_tool_only("", [result]) == (
        True,
        "process_wait_budget_exhausted",
    )


def test_terminal_results_still_trigger_stale_guard() -> None:
    state = LoopState()
    result = {
        "action": "process",
        "status": "completed",
        "process_status": "exited",
        "process_id": "proc",
        "next_sequence": 0,
        "result": "finished",
    }
    assert state.check_empty_tool_only("", [result]) == (False, None)
    assert state.check_empty_tool_only("", [result]) == (False, None)
    assert state.check_empty_tool_only("", [result])[0] is True


def test_log_limit_is_visible_without_stopping_capture(
    runtime: ProcessRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("penguin.tools.process_runtime.MAX_LOG_CHARS", 4)
    pid = runtime.start("printf 'abcdefgh'; read done")["process_id"]
    result = runtime.poll(pid, wait_ms=1000)
    assert result["log_truncated"] is True
    assert "abcdefgh" in result["output"]
    assert Path(result["log_path"]).read_text() == "abcd"
    assert result["process_status"] == "running"


def test_capture_failure_terminates_child_and_surfaces_error(
    runtime: ProcessRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_open(*args, **kwargs):
        raise OSError("injected log failure")

    monkeypatch.setattr("penguin.tools.process_runtime.open", fail_open, raising=False)
    pid = runtime.start("read done")["process_id"]
    result = runtime.poll(pid, wait_ms=1000, wait_for_exit=True)
    assert result["status"] == "error"
    assert result["process_status"] == "exited"
    assert "injected log failure" in result["reader_error"]


@pytest.mark.parametrize("cursor,consumer", [(0, "agent"), (None, "inspector")])
def test_waiting_poll_does_not_block_other_readers(
    runtime: ProcessRuntime,
    monkeypatch: pytest.MonkeyPatch,
    cursor: int | None,
    consumer: str,
) -> None:
    pid = runtime.start("sleep 3")["process_id"]
    record = runtime._processes[pid]
    waiting = threading.Event()
    cancelled = threading.Event()
    original_wait = record.changed.wait

    def wait(timeout: float | None = None) -> bool:
        waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(record.changed, "wait", wait)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(
            runtime.poll, pid, since_sequence=None, wait_ms=1000, cancel_event=cancelled
        )
        try:
            assert waiting.wait(1)
            started = time.monotonic()
            result = runtime.poll(pid, since_sequence=cursor, consumer_id=consumer)
            assert time.monotonic() - started < 0.3
            assert result["process_status"] == "running"
        finally:
            cancelled.set()
        pending.result(timeout=2)


def test_stdin_backpressure_has_deadline_and_reports_partial_write(
    runtime: ProcessRuntime,
) -> None:
    pid = runtime.start("sleep 2")["process_id"]
    started = time.monotonic()
    result = runtime.write_stdin(pid, "x" * 262144)
    assert time.monotonic() - started < 1.5
    assert result["error"] == "stdin_write_timeout"
    assert 0 < result["bytes_written"] < result["bytes_total"]
    assert result["bytes_remaining"] == 262144 - result["bytes_written"]
    assert runtime._processes[pid].process.poll() is None


@pytest.mark.parametrize("same_request", [False, True])
def test_concurrent_consumer_reads_commit_cursor_and_retry_atomically(
    runtime: ProcessRuntime,
    monkeypatch: pytest.MonkeyPatch,
    same_request: bool,
) -> None:
    pid = runtime.start("sleep 3")["process_id"]
    record = runtime._processes[pid]
    both_waiting = threading.Event()
    waiting_threads = set()
    original_wait = record.changed.wait

    def wait(timeout: float | None = None) -> bool:
        waiting_threads.add(threading.get_ident())
        if len(waiting_threads) == 2:
            both_waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(record.changed, "wait", wait)
    with ThreadPoolExecutor() as pool:
        calls = [
            pool.submit(
                runtime.poll,
                pid,
                since_sequence=None,
                wait_ms=500,
                request_id="same" if same_request else str(i),
            )
            for i in range(2)
        ]
        assert both_waiting.wait(1)
        with record.changed:
            record.append_output("stdout", "only once\n")
            record.changed.notify_all()
        results = [call.result(timeout=2) for call in calls]
    if same_request:
        assert results[0] == results[1]
        assert "only once" in results[0]["output"]
    else:
        assert sum("only once" in result["output"] for result in results) == 1
    assert record.cursors["agent"] == 1


def test_queued_stdin_writer_obeys_deadline(runtime: ProcessRuntime) -> None:
    pid = runtime.start("sleep 3")["process_id"]
    with runtime._processes[pid].write_lock:
        started = time.monotonic()
        result = runtime.write_stdin(pid, "hello", timeout_ms=50)
    assert time.monotonic() - started < 0.5
    assert result["error"] == "stdin_write_timeout"
    assert result["bytes_written"] == 0


def test_stdin_cancellation_reports_partial_utf8_bytes(
    runtime: ProcessRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    pid = runtime.start("sleep 3")["process_id"]
    cancelled = threading.Event()
    original_write = os.write

    def write(fd: int, data: bytes) -> int:
        count = original_write(fd, data[:3])
        cancelled.set()
        return count

    monkeypatch.setattr(os, "write", write)
    result = runtime.write_stdin(pid, "é" * 100, cancel_event=cancelled)
    assert result["error"] == "stdin_write_cancelled"
    assert result["bytes_written"] == 3
    assert result["bytes_total"] == 200
    assert result["bytes_remaining"] == 197
    assert runtime._processes[pid].process.poll() is None
