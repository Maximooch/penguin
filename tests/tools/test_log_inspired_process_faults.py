from __future__ import annotations

import builtins
import errno
import shlex
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from penguin.tools.process_runtime import MAX_BUFFER_CHARS, ProcessRuntime


class _FaultingLog:
    """Delegate to a real log file while failing one selected operation."""

    def __init__(self, wrapped: Any, operation: str, failure: OSError) -> None:
        self._wrapped = wrapped
        self._operation = operation
        self._failure = failure

    def __enter__(self) -> _FaultingLog:
        self._wrapped.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._wrapped.__exit__(*args)

    def write(self, text: str) -> int:
        if self._operation == "write":
            raise self._failure
        return self._wrapped.write(text)

    def flush(self) -> None:
        if self._operation == "flush":
            raise self._failure
        self._wrapped.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


def _python_command(source: str) -> str:
    return " ".join((shlex.quote(sys.executable), "-c", shlex.quote(source)))


def _wait_for_reader(runtime: ProcessRuntime, process_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 3
    snapshot: dict[str, Any] = {}
    while time.monotonic() < deadline:
        snapshot = runtime.poll(process_id)
        record = runtime._processes[process_id]
        if record.reader_done and record.process.poll() is not None:
            return snapshot
        time.sleep(0.01)
    pytest.fail(f"reader/process did not finish: {snapshot}")


def _assert_reaped(runtime: ProcessRuntime, process_id: str) -> None:
    record = runtime._processes[process_id]
    assert record.process.poll() is not None
    assert record.reader_done is True
    assert record.reader is not None
    record.reader.join(timeout=0.2)
    assert not record.reader.is_alive()


@pytest.mark.parametrize(
    ("operation", "error_number", "message"),
    [
        pytest.param("open", errno.EACCES, "permission denied", id="open-permission"),
        pytest.param("write", errno.ENOSPC, "disk full on write", id="write-enospc"),
        pytest.param("flush", errno.ENOSPC, "disk full on flush", id="flush-enospc"),
    ],
)
def test_capture_log_fault_is_surfaced_reaps_child_and_runtime_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    error_number: int,
    message: str,
) -> None:
    """Log I/O faults must fail explicitly without poisoning later processes."""
    runtime = ProcessRuntime(log_dir=tmp_path, max_events_per_process=8)
    real_open = builtins.open
    fault_enabled = True

    def faulting_open(
        file: str | bytes | int | Path,
        mode: str = "r",
        *args: object,
        **kwargs: object,
    ) -> Any:
        if fault_enabled and mode == "a" and Path(file).parent == tmp_path:
            failure = OSError(error_number, message)
            if operation == "open":
                raise failure
            wrapped = real_open(file, mode, *args, **kwargs)
            return _FaultingLog(wrapped, operation, failure)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", faulting_open)
    process_ids: list[str] = []
    try:
        command = _python_command(
            "import sys, time; "
            "sys.stdout.write('payload-' + 'x' * 300000); "
            "sys.stdout.flush(); time.sleep(10)"
        )
        process_id = runtime.start(command)["process_id"]
        process_ids.append(process_id)
        failed = _wait_for_reader(runtime, process_id)

        assert failed["status"] == "error"
        assert failed["reader_error"] is not None
        assert message in failed["reader_error"].lower()
        assert failed["error"] == failed["reader_error"]
        assert failed["returncode"] not in (0, None)
        assert failed["process_status"] == "exited"
        assert runtime._processes[process_id].buffered_chars <= MAX_BUFFER_CHARS
        _assert_reaped(runtime, process_id)

        fault_enabled = False
        fresh_id = runtime.start("printf 'fresh-process-ok\\n'")["process_id"]
        process_ids.append(fresh_id)
        recovered = _wait_for_reader(runtime, fresh_id)

        assert recovered["status"] == "completed"
        assert recovered["returncode"] == 0
        assert "fresh-process-ok" in recovered["output"]
        assert recovered["reader_error"] is None
        _assert_reaped(runtime, fresh_id)
    finally:
        fault_enabled = False
        runtime.cleanup(timeout=0.5)


def test_callback_exceptions_do_not_fake_failure_or_leak_child(tmp_path: Path) -> None:
    """Observer failures must be isolated from process completion and cleanup."""
    callback_kinds: list[str] = []

    def broken_callback(kind: str, payload: dict[str, Any]) -> None:
        callback_kinds.append(kind)
        assert payload["process_id"]
        raise RuntimeError("synthetic callback failure")

    runtime = ProcessRuntime(log_dir=tmp_path)
    process_id = ""
    try:
        started = runtime.start(
            "printf 'callback-safe\\n'",
            on_event=broken_callback,
            notify_on_complete=True,
        )
        process_id = started["process_id"]
        completed = _wait_for_reader(runtime, process_id)

        assert completed["status"] == "completed"
        assert completed["returncode"] == 0
        assert completed["error"] is None
        assert completed["reader_error"] is None
        assert "callback-safe" in completed["output"]
        assert "output" in callback_kinds
        assert "completed" in callback_kinds
        _assert_reaped(runtime, process_id)
    finally:
        runtime.cleanup(timeout=0.5)
