"""A managed process is ended, signalled and released by one owner at a time.

Covers SM-24: the completion reason was written by two threads, a stop could
signal a process group whose leader Penguin had already reaped, cleanup held
the runtime lock across blocking stops and dropped retry receipts, and a poll
could commit its answer to a record that was being retired.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

from penguin.tools.process_runtime import ProcessRuntime

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")

# Replaces the shell and ignores SIGTERM, so only SIGKILL ends it.
STUBBORN = (
    f'exec "{sys.executable}" -c "import signal, time; '
    'signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(5)"'
)


@pytest.fixture
def runtime(tmp_path: Path):
    runtime = ProcessRuntime(log_dir=tmp_path)
    yield runtime
    runtime.cleanup(mode="kill", timeout=0.5)


def _wait_until(condition, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_a_stop_stays_cancelled_when_the_deadline_fires_during_it(
    runtime: ProcessRuntime,
) -> None:
    process_id = runtime.start(STUBBORN)["process_id"]
    time.sleep(0.3)  # let the child install its SIGTERM handler
    record = runtime._processes[process_id]
    stopping = threading.Thread(
        target=runtime.stop, args=(process_id,), kwargs={"timeout": 2.0}
    )
    stopping.start()
    assert _wait_until(lambda: record.completion_reason is not None)

    record.deadline = time.monotonic() - 1
    stopping.join(timeout=5)

    assert runtime.poll(process_id)["completion_reason"] == "cancelled"


def test_stop_never_signals_a_reaped_pid_that_was_reused(
    runtime: ProcessRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    process_id = runtime.start("true")["process_id"]
    runtime.poll(process_id, wait_ms=3000, wait_for_exit=True)
    record = runtime._processes[process_id]
    assert record.process.returncode is not None
    pid = record.process.pid
    real_kill = os.kill
    signalled: list[int] = []

    def kill(target: int, sig: int) -> None:
        if target == pid and sig == 0:
            return  # another program has this pid now
        real_kill(target, sig)

    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(os, "killpg", lambda target, _sig: signalled.append(target))

    runtime.stop(process_id, timeout=0.2)

    assert signalled == []


def test_cleanup_still_ends_children_that_outlived_their_shell(
    runtime: ProcessRuntime,
) -> None:
    process_id = runtime.start("sleep 30 & echo $!")["process_id"]
    result = runtime.poll(process_id, wait_ms=3000, wait_for_exit=True)
    child = int(result["output"].split()[-1])

    runtime.cleanup(timeout=0.5)

    def gone() -> bool:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return True
        return False

    assert _wait_until(gone)


def test_cleanup_does_not_block_other_calls_while_it_stops_processes(
    runtime: ProcessRuntime,
) -> None:
    runtime.start(STUBBORN)
    other = runtime.start("sleep 5")["process_id"]
    time.sleep(0.3)  # let the stubborn child install its SIGTERM handler
    cleaning = threading.Thread(target=runtime.cleanup, kwargs={"timeout": 2.0})
    cleaning.start()
    time.sleep(0.2)

    started = time.monotonic()
    runtime.status(other)
    elapsed = time.monotonic() - started
    cleaning.join(timeout=10)

    assert elapsed < 1.0


def test_cleanup_keeps_receipts_so_a_retried_start_does_not_rerun(
    runtime: ProcessRuntime, tmp_path: Path
) -> None:
    marker = tmp_path / "runs"
    command = f"echo run >> {marker}"
    runtime.start(command, process_id="call_1")
    runtime.poll("call_1", wait_ms=3000, wait_for_exit=True)

    runtime.cleanup(timeout=0.5)
    retried = runtime.start(command, process_id="call_1")

    assert retried["status"] == "error"
    assert retried["error"] == "process_result_expired"
    time.sleep(0.2)
    assert marker.read_text().count("run") == 1


def test_a_poll_racing_retirement_answers_like_its_retry(
    runtime: ProcessRuntime,
) -> None:
    process_id = runtime.start("echo done")["process_id"]
    runtime.poll(process_id, max_chars=0, wait_ms=3000, wait_for_exit=True)
    record = runtime._processes[process_id]
    answers: list[dict] = []

    with record.changed:
        polling = threading.Thread(
            target=lambda: answers.append(
                runtime.poll(process_id, request_id="req_1", since_sequence=None)
            )
        )
        polling.start()
        time.sleep(0.1)  # the poll has found the record and waits for its lock
        with runtime._lock:
            runtime._retire(record)
    polling.join(timeout=5)
    retry = runtime.poll(process_id, request_id="req_1", since_sequence=None)

    assert answers == [retry]
