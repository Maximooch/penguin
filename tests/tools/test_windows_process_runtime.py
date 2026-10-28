"""Real native Windows pipes and process-lifecycle regression contracts."""

from __future__ import annotations

import asyncio
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from penguin.tools.process_runtime import ProcessRuntime
from penguin.tools.process_tools import ProcessTools

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native Windows pipe contract")


@pytest.fixture
def runtime(tmp_path):
    instance = ProcessRuntime(log_dir=tmp_path / "logs")
    yield instance
    instance.cleanup()
    assert not instance._processes


@pytest.fixture
def command(tmp_path):
    sequence = 0

    def build(source: str) -> str:
        nonlocal sequence
        sequence += 1
        script = tmp_path / f"script with spaces {sequence}.py"
        script.write_text(source, encoding="utf-8")
        return subprocess.list2cmdline(
            [sys.executable, "-u", "-X", "utf8", str(script)]
        )

    return build


def finish(runtime, process_id):
    result = runtime.poll(
        process_id, wait_ms=10000, wait_for_exit=True, max_chars=500000
    )
    assert result["process_status"] == "exited", result
    assert result["reader_error"] is None, result
    assert result["returncode"] is not None
    runtime._processes[process_id].reader.join(1)
    assert not runtime._processes[process_id].reader.is_alive()
    return result


def test_delayed_output_survives_return_and_is_not_consumed(runtime):
    events = []
    complete = threading.Event()

    def receive(kind, payload):
        events.append((kind, payload))
        if kind == "completed":
            complete.set()

    pid = runtime.start(
        subprocess.list2cmdline(
            [
                sys.executable,
                "-c",
                "import time; print('first', flush=True); "
                "time.sleep(.2); print('last', flush=True)",
            ]
        ),
        notify_on_complete=True,
        on_event=receive,
    )["process_id"]
    assert complete.wait(5), events
    assert runtime._processes[pid].cursors == {}
    result = finish(runtime, pid)
    assert "first" in result["output"] and "last" in result["output"]
    assert result["returncode"] == 0
    completed = [p for kind, p in events if kind == "completed"]
    assert len(completed) == 1
    assert completed[0]["returncode"] == 0
    assert completed[0]["completion_reason"] == "exited"
    assert "last" in completed[0]["output_tail"]
    assert runtime.poll(pid)["output"] == result["output"]


def test_cmd_launch_and_both_streams(runtime):
    pid = runtime.start("echo native-out & echo native-err 1>&2")["process_id"]
    result = finish(runtime, pid)
    assert result["returncode"] == 0
    assert "native-out" in result["output"] and "native-err" in result["output"]


def test_large_concurrent_unicode_streams_do_not_deadlock(runtime, command):
    source = """
import os, threading
def write(fd, value):
    data = (value * 80000).encode('utf-8')
    while data:
        data = data[os.write(fd, data):]
threads = [threading.Thread(target=write, args=(1, '\\u96ea')),
           threading.Thread(target=write, args=(2, '\\u00e9'))]
for thread in threads: thread.start()
for thread in threads: thread.join()
"""
    pid = runtime.start(command(source))["process_id"]
    result = finish(runtime, pid)
    assert result["returncode"] == 0
    assert result["output"].count("\u96ea") == 80000
    assert result["output"].count("\u00e9") == 80000
    assert "\ufffd" not in result["output"]
    log = Path(result["log_path"]).read_text(encoding="utf-8")
    assert log.count("\u96ea") == 80000
    assert log.count("\u00e9") == 80000


def test_nonzero_exit_retains_output_and_error(runtime, command):
    pid = runtime.start(
        command("import sys; print('failure detail', file=sys.stderr); sys.exit(7)")
    )["process_id"]
    result = finish(runtime, pid)
    assert result["returncode"] == 7
    assert result["error"] == "command_failed"
    assert "failure detail" in result["output"]


def test_utf8_python_text_output(runtime, command):
    pid = runtime.start(
        command("import sys; print('\u96ea'); print('\u00e9',file=sys.stderr)")
    )["process_id"]
    result = finish(runtime, pid)
    assert result["returncode"] == 0
    assert "\u96ea" in result["output"]
    assert "\u00e9" in result["output"]


def test_quiet_capture_blocks_between_bounded_readiness_scans(
    runtime, command, monkeypatch
):
    from penguin.tools import windows_pipes

    original = windows_pipes._kernel.PeekNamedPipe
    scans = []

    def count(*args):
        scans.append(time.monotonic())
        return original(*args)

    monkeypatch.setattr(windows_pipes._kernel, "PeekNamedPipe", count)
    started = time.monotonic()
    pid = runtime.start(command("import time; time.sleep(.4)"))["process_id"]
    result = finish(runtime, pid)
    elapsed = time.monotonic() - started
    assert result["returncode"] == 0
    # Two pipes, one readiness scan per 20ms plus startup/EOF boundary scans.
    assert len(scans) <= 2 * math.ceil(elapsed / 0.02) + 12, (len(scans), elapsed)


@pytest.mark.parametrize("timeout", [0.02, 0.06])
def test_quiet_selector_does_not_rescan_due_to_coarse_clock(monkeypatch, timeout):
    from penguin.tools import windows_pipes

    elapsed = [0.0]
    waits, scans = [], []

    class ClockedStopEvent:
        def is_set(self):
            return False

        def wait(self, seconds):
            waits.append(seconds)
            elapsed[0] += seconds
            return False

    monkeypatch.setattr(
        windows_pipes,
        "time",
        SimpleNamespace(
            monotonic=lambda: math.floor(elapsed[0] / 0.015625) * 0.015625,
            perf_counter=lambda: elapsed[0],
        ),
    )
    real_peek = windows_pipes._kernel.PeekNamedPipe

    def peek(*args):
        scans.append(elapsed[0])
        return real_peek(*args)

    monkeypatch.setattr(windows_pipes._kernel, "PeekNamedPipe", peek)
    read_fd, write_fd = os.pipe()
    try:
        selector = windows_pipes.PipeSelector(ClockedStopEvent())
        selector.register(SimpleNamespace(fileno=lambda: read_fd), 1, "stdout")
        assert selector.select(timeout) == []
        assert elapsed[0] == pytest.approx(timeout)
        assert waits == pytest.approx([0.02] * math.ceil(timeout / 0.02))
        assert len(scans) == math.ceil(timeout / 0.02)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_closed_stream_selector_blocks_and_cancellation_wakes_it():
    from penguin.tools.windows_pipes import PipeSelector

    stop = threading.Event()
    selector = PipeSelector(stop)
    started = time.monotonic()
    assert selector.select(0.05) == []
    assert time.monotonic() - started >= 0.04
    waiter = threading.Thread(target=selector.select, args=(30,))
    waiter.start()
    stop.set()
    waiter.join(0.5)
    assert not waiter.is_alive()


def test_stdin_is_utf8_and_backpressure_is_bounded(runtime, command):
    pid = runtime.start(
        command("import sys; print(sys.stdin.buffer.readline().hex())")
    )["process_id"]
    written = runtime.write_stdin(pid, "\u96ea\n")
    assert written["bytes_written"] == 4
    assert "e99baa0a" in finish(runtime, pid)["output"]
    pid = runtime.start(command("import time; time.sleep(30)"))["process_id"]
    started = time.monotonic()
    result = runtime.write_stdin(pid, "x" * 1000000, timeout_ms=100)
    assert time.monotonic() - started < 2
    assert result["error"] == "stdin_write_timeout"
    assert 0 < result["bytes_written"] < result["bytes_total"]
    cancelled = threading.Event()
    cancelled.set()
    assert (
        runtime.write_stdin(pid, "ignored", cancel_event=cancelled)["error"]
        == "stdin_write_cancelled"
    )
    assert runtime.status(pid)["process_status"] == "running"


@pytest.mark.parametrize("mode", ["terminate", "kill", "interrupt"])
def test_stop_modes_terminate_process_and_reader(runtime, command, mode):
    pid = runtime.start(command("import time; print('started'); time.sleep(30)"))[
        "process_id"
    ]
    assert "started" in runtime.poll(pid, wait_ms=2000)["output"]
    stopped = runtime.stop(pid, mode=mode, timeout=1)
    assert stopped["process_status"] == "exited"
    assert stopped["returncode"] is not None
    assert stopped["completion_reason"] == "cancelled"
    assert not runtime._processes[pid].reader.is_alive()


def test_interrupt_without_console_falls_back_to_tree_stop(
    runtime, command, monkeypatch
):
    pid = runtime.start(command("import time; time.sleep(30)"))["process_id"]

    def no_console(_signal):
        raise OSError("No console attached")

    monkeypatch.setattr(runtime._processes[pid].process, "send_signal", no_console)
    assert runtime.stop(pid, mode="interrupt")["process_status"] == "exited"


def test_hosted_cleanup_filters_helper_environment(runtime, command, monkeypatch):
    """The actual Windows helper works with the restricted environment."""
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    monkeypatch.setenv("SYNTHETIC_CLEANUP_SECRET", "synthetic-secret")
    real_run = subprocess.run
    environments = []

    def capture_run(*args, **kwargs):
        environments.append(kwargs.get("env"))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", capture_run)
    pid = runtime.start(command("import time; print('started'); time.sleep(30)"))[
        "process_id"
    ]
    assert "started" in runtime.poll(pid, wait_ms=2000)["output"]
    assert runtime.stop(pid)["process_status"] == "exited"
    assert environments
    assert all(isinstance(environment, dict) for environment in environments)
    assert all("SYNTHETIC_CLEANUP_SECRET" not in env for env in environments)


def test_timeout_stops_child_tree(runtime, command, tmp_path):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    marker = tmp_path / "leaked-child.txt"
    child = (
        "import time; from pathlib import Path; time.sleep(30); "
        f"Path({str(marker)!r}).write_text('leak')"
    )
    source = (
        "import subprocess,sys,time; "
        f"child=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "print(child.pid); time.sleep(30)"
    )
    pid = runtime.start(command(source), timeout_seconds=3)["process_id"]
    output = runtime.poll(pid, wait_ms=2000)["output"]
    child_pid = int(output.split()[-1])
    handle = kernel.OpenProcess(0x00100000, False, child_pid)  # SYNCHRONIZE
    assert handle, ctypes.WinError(ctypes.get_last_error())
    try:
        result = finish(runtime, pid)
        assert result["completion_reason"] == "timeout"
        assert result["error"] == "timeout"
        assert kernel.WaitForSingleObject(handle, 2000) == 0  # signalled: exited
    finally:
        kernel.CloseHandle(handle)
    assert not marker.exists()


def test_capture_fault_is_reported_and_process_is_reaped(runtime, command, monkeypatch):
    from penguin.tools.windows_pipes import PipeSelector

    def broken_pipe(self, timeout):
        raise OSError("injected capture failure")

    monkeypatch.setattr(PipeSelector, "select", broken_pipe)
    pid = runtime.start(command("import time; time.sleep(30)"))["process_id"]
    result = runtime.poll(pid, wait_ms=5000, wait_for_exit=True)
    assert result["process_status"] == "exited"
    assert "injected capture failure" in result["reader_error"]
    assert result["returncode"] is not None


def test_public_process_service_emits_after_start_returns(runtime, command):
    service = ProcessTools(runtime)
    owner = {"session_id": "session", "agent_id": "parent"}
    try:
        started = service.execute(
            "process_start",
            {
                "command": command(
                    "import time; print('first'); time.sleep(.2); print('last')"
                )
            },
            owner,
        )
        pid = started["process_id"]
        result = finish(runtime, pid)
        assert result["returncode"] == 0
        assert runtime._processes[pid].cursors == {}
        notices = service.pending(("session", "parent"))
        assert len(notices) == 1
        assert notices[0]["returncode"] == 0
        assert "last" in notices[0]["output_tail"]
        assert (
            service.execute("process_status", {"process_id": pid}, owner)["output"]
            == ""
        )
        assert "first" in runtime.poll(pid)["output"]
    finally:
        service.cleanup()


@pytest.mark.asyncio
async def test_bound_process_events_arrive_after_start_returns(runtime, command):
    service = ProcessTools(runtime)
    completed = asyncio.Event()
    events = []

    async def receive(kind, payload):
        events.append((kind, payload))
        if kind == "completed":
            completed.set()

    owner = {"session_id": "session", "agent_id": "parent"}
    service.bind(("session", "parent"), receive)
    try:
        started = await asyncio.to_thread(
            service.execute,
            "process_start",
            {
                "command": command(
                    "import time; print('first'); time.sleep(.2); print('last')"
                )
            },
            owner,
        )
        await asyncio.wait_for(completed.wait(), 5)
        pid = started["process_id"]
        assert runtime._processes[pid].cursors == {}
        assert any(kind == "output" for kind, _ in events)
        result = next(payload for kind, payload in events if kind == "completed")
        assert result["session_id"] == "session"
        assert result["agent_id"] == "parent"
        assert result["returncode"] == 0
        assert "last" in result["output_tail"]
        assert "first" in runtime.poll(pid)["output"]
    finally:
        service.cleanup()
