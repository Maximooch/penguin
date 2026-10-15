"""Persistent shell processes with continuous capture and bounded, replayable reads."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import selectors
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from codecs import getincrementaldecoder
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_POLL_WAIT_MS = 5_000
MAX_POLL_WAIT_MS = 60_000
MAX_BUFFER_CHARS = 256_000
MAX_LOG_CHARS = 32_000_000
POST_EXIT_DRAIN_SECONDS = 0.1


@dataclass(frozen=True)
class ProcessOutputEvent:
    """One decoded stdout/stderr chunk; sequence numbers begin at one."""

    sequence: int
    stream: str
    text: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ManagedProcess:
    """State guarded by ``changed``; one worker owns both output pipes."""

    process_id: str
    command: str
    cwd: str
    process: subprocess.Popen[str]
    env_overrides: dict[str, str] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    events: deque[ProcessOutputEvent] = field(default_factory=deque)
    next_sequence: int = 1
    changed: threading.Condition = field(default_factory=threading.Condition)
    reader: threading.Thread | None = None
    reader_done: bool = False
    streams_closed: bool = False
    reader_error: str | None = None
    buffered_chars: int = 0
    log_path: str | None = None
    log_chars: int = 0
    log_truncated: bool = False
    owns_group: bool = False
    stop_reader: threading.Event = field(default_factory=threading.Event)
    cursors: dict[str, int] = field(default_factory=dict)
    replies: OrderedDict[tuple[str, str], dict[str, Any]] = field(
        default_factory=OrderedDict
    )
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    completion_reason: str | None = None
    owner: tuple[str, str] = ("", "agent")
    deadline: float | None = None
    on_event: Callable[[str, dict[str, Any]], None] | None = None
    notify_on_complete: bool = False
    notified: bool = False
    last_output_event: float = 0.0
    completion_observed: bool = False

    def append_output(self, stream: str, text: str) -> None:
        """Append an event while holding ``changed``."""
        self.events.append(ProcessOutputEvent(self.next_sequence, stream, text))
        self.next_sequence += 1
        self.buffered_chars += len(text)

    def status(self) -> str:
        """Keep exit pending until the reader has collected trailing output."""
        if self.process.poll() is None:
            return "running"
        return (
            "draining" if self.reader is not None and not self.reader_done else "exited"
        )


class ProcessRuntime:
    """Own child processes, output logs, and independent consumer cursors.

    Low-level reads default to explicit replay from zero for compatibility.
    Tool callers pass ``since_sequence=None`` to advance their own cursor.
    Logs outlive process cleanup and are capped separately from memory.
    """

    def __init__(
        self,
        *,
        max_events_per_process: int = 10_000,
        log_dir: str | Path | None = None,
        max_processes: int = 128,
    ) -> None:
        self._processes: dict[str, ManagedProcess] = {}
        self._max_events_per_process = max(1, max_events_per_process)
        self._max_processes = max_processes
        self._lock = threading.RLock()
        self._retired_dir: Path | None = None
        self._log_dir = (
            Path(log_dir)
            if log_dir
            else Path(
                os.environ.get("PENGUIN_WORKSPACE", "~/penguin_workspace")
            ).expanduser()
            / "process-logs"
        )

    def start(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        process_id: str | None = None,
        owner: tuple[str, str] = ("", "agent"),
        timeout_seconds: float | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        notify_on_complete: bool = False,
    ) -> dict[str, Any]:
        """Start a shell command and its output reader; return a zero cursor."""
        if timeout_seconds is not None and (
            not math.isfinite(timeout_seconds) or timeout_seconds < 0
        ):
            return self._error(
                process_id or "", "timeout_seconds must be finite and nonnegative"
            )
        resolved_cwd = str(Path(cwd or os.getcwd()).expanduser().resolve())
        from penguin.system.tool_environment import build_tool_environment

        try:
            effective_env = build_tool_environment(env)
        except ValueError as exc:
            return self._error(process_id or "", str(exc))
        for key, value in (
            ("TERM", "dumb"),
            ("NO_COLOR", "1"),
            ("RICH_NO_MARKUP", "1"),
        ):
            effective_env.setdefault(key, value)
        resolved_id = process_id or f"proc_{uuid.uuid4().hex[:12]}"
        with self._lock:
            if resolved_id in self._processes:
                return self._error(resolved_id, "process_id_already_exists")
            retired = self.retired_result(resolved_id, owner=owner)
            if retired is not None:
                return retired
            if len(self._processes) >= self._max_processes:
                # Prefer consumed results, but unread completions cannot pin capacity.
                candidates = sorted(
                    self._processes.values(),
                    key=lambda old: (not old.completion_observed, old.started_at),
                )
                for old in candidates:
                    if old.status() != "exited":
                        continue
                    self._retire(old)
                    break
                if len(self._processes) >= self._max_processes:
                    counts = {state: 0 for state in ("running", "draining", "exited")}
                    for record in self._processes.values():
                        counts[record.status()] += 1
                    result = self._error(resolved_id, "process_limit_reached")
                    result.update(limit=self._max_processes, process_counts=counts)
                    result["result"] += (
                        f"; limit={self._max_processes}, counts={counts}. "
                        "Wait for active commands to finish or use process_stop on "
                        "an owned command you no longer need. Retrying a new command "
                        "without releasing capacity will not help."
                    )
                    logger.warning("Process capacity exhausted: %s", counts)
                    return result
            log_path = None
            try:
                self._log_dir.mkdir(parents=True, exist_ok=True)
                fd, log_path = tempfile.mkstemp(
                    prefix="process-", suffix=".log", dir=self._log_dir
                )
                os.close(fd)
                process = subprocess.Popen(
                    ["bash", "-c", command],
                    cwd=resolved_cwd,
                    env=effective_env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    start_new_session=os.name == "posix",
                )
            except OSError as exc:
                if log_path:
                    Path(log_path).unlink(missing_ok=True)
                return self._error(resolved_id, f"start_failed: {exc}")
            record = ManagedProcess(
                resolved_id,
                command,
                resolved_cwd,
                process,
                env_overrides={key: str(value) for key, value in (env or {}).items()},
                owns_group=os.name == "posix",
                log_path=log_path,
                owner=owner,
                on_event=on_event,
                notify_on_complete=notify_on_complete,
                deadline=(
                    time.monotonic() + timeout_seconds
                    if timeout_seconds is not None
                    else None
                ),
            )
            self._processes[resolved_id] = record
            record.reader = threading.Thread(
                target=self._capture,
                args=(record,),
                name=f"penguin-{resolved_id}",
                daemon=True,
            )
            record.reader.start()
            with record.changed:
                # Start delivers no output, even if the worker won the race.
                return self._snapshot(
                    record, output="", since_sequence=0, next_sequence=0
                )

    def _retired_path(self, process_id: str) -> Path | None:
        if self._retired_dir is None:
            return None
        # Hash caller-supplied IDs rather than treating them as filesystem paths.
        return self._retired_dir / (
            hashlib.sha256(process_id.encode()).hexdigest() + ".json"
        )

    def _retire(self, record: ManagedProcess) -> None:
        """Release an exited handle after saving its result and retry receipts."""
        with record.changed:
            if self._retired_dir is None:
                self._retired_dir = Path(
                    tempfile.mkdtemp(prefix="retired-", dir=self._log_dir)
                )
            path = self._retired_path(record.process_id)
            snapshot = self._snapshot(
                record,
                output="",
                since_sequence=0,
                next_sequence=record.next_sequence - 1,
            )
            receipt = {
                "owner": record.owner,
                "snapshot": snapshot,
                "replies": [
                    [list(key), value] for key, value in record.replies.items()
                ],
            }
            # Save before eviction: a failed write must not permit command replay.
            temporary = path.with_suffix(".tmp")
            try:
                temporary.write_text(json.dumps(receipt), encoding="utf-8")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
            with record.write_lock:
                if record.process.stdin is not None:
                    record.process.stdin.close()
            del self._processes[record.process_id]

    def retired_result(
        self,
        process_id: str,
        *,
        owner: tuple[str, str] | None = None,
        command: str | None = None,
        consumer_id: str = "agent",
        request_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Replay a retired receipt or report expiration with the retained log."""
        path = self._retired_path(process_id)
        if path is None or not path.exists():
            return None
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if owner is not None and tuple(receipt["owner"]) != owner:
            return self._error(process_id, "unknown_process_id")
        snapshot = receipt["snapshot"]
        if command is not None and command != snapshot["command"]:
            return self._error(process_id, "tool_call_id reused with different command")
        if request_id is not None:
            for key, reply in receipt["replies"]:
                if key == [consumer_id, request_id]:
                    return reply
        result = self._error(process_id, "process_result_expired")
        result.update(log_path=snapshot["log_path"], returncode=snapshot["returncode"])
        result["result"] += (
            f"; command exited with returncode={snapshot['returncode']}. "
            f"Read retained output at log_path={snapshot['log_path']}. "
            "The command was not restarted."
        )
        return result

    def poll(
        self,
        process_id: str,
        *,
        since_sequence: int | None = 0,
        max_chars: int = 12_000,
        wait_ms: int = 0,
        consumer_id: str = "agent",
        request_id: str | None = None,
        wait_for_exit: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Wait for new data/exit and return a reusable exclusive cursor.

        Explicit cursors never consume another reader's output. Automatic reads
        commit cursors atomically. Request IDs replay the last 128 responses,
        allowing a transport retry without skipping output. A zero-size read is a peek.
        """
        if not math.isfinite(wait_ms) or not 0 <= wait_ms <= MAX_POLL_WAIT_MS:
            return self._error(process_id, "wait_ms must be between 0 and 60000")
        if max_chars < 0 or (since_sequence is not None and since_sequence < 0):
            return self._error(
                process_id, "output limit and cursor must be nonnegative"
            )
        record = self._processes.get(process_id)
        if record is None:
            return self.retired_result(
                process_id, consumer_id=consumer_id, request_id=request_id
            ) or self._error(process_id, "unknown_process_id")
        started = time.monotonic()
        key = (consumer_id, request_id) if request_id else None
        with record.changed:
            deadline = started + wait_ms / 1000
            while True:
                # Recheck after every wait: another call may have consumed output
                # or completed this same request while the condition was released.
                if key is not None and key in record.replies:
                    return dict(record.replies[key])
                cursor = (
                    record.cursors.get(consumer_id, 0)
                    if since_sequence is None
                    else since_sequence
                )
                if cursor > record.next_sequence - 1:
                    return self._error(process_id, "cursor_ahead_of_output")
                if record.status() == "exited" or (
                    not wait_for_exit and record.next_sequence - 1 > cursor
                ):
                    break
                if cancel_event is not None and cancel_event.is_set():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                record.changed.wait(
                    min(remaining, 0.05) if cancel_event is not None else remaining
                )
            events = [event for event in record.events if event.sequence > cursor]
            output = "".join(f"[{event.stream}] {event.text}" for event in events)
            history_lost = bool(
                record.events and cursor < record.events[0].sequence - 1
            )
            truncated = history_lost or len(output) > max_chars
            output = output[-max_chars:] if max_chars else ""
            next_sequence = record.next_sequence - 1 if max_chars else cursor
            snapshot = self._snapshot(
                record,
                output=output,
                since_sequence=cursor,
                next_sequence=next_sequence,
            )
            snapshot.update(
                truncated=truncated,
                history_lost=history_lost,
                no_new_output=not events,
                waited_ms=round((time.monotonic() - started) * 1000),
            )
            if truncated:
                snapshot["result"] += (
                    "\nOutput truncated; inspect log_path for retained output."
                )
            if since_sequence is None and max_chars:
                record.cursors[consumer_id] = next_sequence
            if max_chars and snapshot["process_status"] == "exited":
                record.completion_observed = True
            if key is not None:
                record.replies[key] = dict(snapshot)
                while len(record.replies) > 128:
                    record.replies.popitem(last=False)
            record.changed.notify_all()
            return snapshot

    def write_stdin(
        self,
        process_id: str,
        text: str,
        *,
        timeout_ms: int = 1000,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Write bounded, cancellable input and report bytes accepted by the pipe."""
        if not math.isfinite(timeout_ms) or not 0 < timeout_ms <= 60_000:
            return self._error(process_id, "timeout_ms must be between 1 and 60000")
        record = self._processes.get(process_id)
        if record is None:
            return self._error(process_id, "unknown_process_id")
        payload = text.encode("utf-8")
        written = 0
        deadline = time.monotonic() + timeout_ms / 1000
        acquired = False
        error = None
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    error = "stdin_write_cancelled"
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    error = "stdin_write_timeout"
                    break
                if not acquired:
                    acquired = record.write_lock.acquire(timeout=min(remaining, 0.05))
                    if not acquired:
                        continue
                if record.process.poll() is not None:
                    error = "process_not_running"
                    break
                if record.process.stdin is None:
                    error = "stdin_unavailable"
                    break
                if written == len(payload):
                    break
                fd = record.process.stdin.fileno()
                os.set_blocking(fd, False)
                try:
                    # Small chunks bound work between cancellation checks. All
                    # stdin writes use the raw descriptor; no text buffer is used.
                    written += os.write(fd, payload[written : written + 4096])
                except BlockingIOError:
                    with selectors.DefaultSelector() as selector:
                        selector.register(fd, selectors.EVENT_WRITE)
                        selector.select(timeout=min(remaining, 0.05))
        except (OSError, ValueError) as exc:
            error = f"stdin_write_failed: {exc}"
        finally:
            if acquired:
                record.write_lock.release()
        with record.changed:
            result = self._snapshot(
                record, output="", since_sequence=0, next_sequence=0
            )
        result.update(
            bytes_written=written,
            bytes_total=len(payload),
            bytes_remaining=len(payload) - written,
        )
        if error is not None:
            result.update(status="error", error=error)
            result["result"] += (
                f"\n{error}: accepted {written}/{len(payload)} UTF-8 bytes. "
                "Do not resend the entire input: accepted bytes cannot be undone."
            )
        return result

    def _signal(self, record: ManagedProcess, mode: str) -> None:
        try:
            if record.owns_group:
                os.killpg(
                    record.process.pid,
                    {"interrupt": signal.SIGINT, "kill": signal.SIGKILL}.get(
                        mode, signal.SIGTERM
                    ),
                )
            elif record.process.poll() is None:
                if mode == "interrupt":
                    record.process.send_signal(signal.SIGINT)
                elif mode == "kill":
                    record.process.kill()
                else:
                    record.process.terminate()
        except ProcessLookupError:
            pass  # A concurrent exit has already accomplished cancellation.

    def stop(
        self, process_id: str, *, mode: str = "terminate", timeout: float = 2.0
    ) -> dict[str, Any]:
        """Signal the process group, escalate, and preserve its final output."""
        record = self._processes.get(process_id)
        if record is None:
            return self._error(process_id, "unknown_process_id")
        if (
            mode not in {"terminate", "interrupt", "kill"}
            or not math.isfinite(timeout)
            or timeout < 0
        ):
            return self._error(process_id, "invalid stop mode or timeout")
        if record.process.poll() is None and record.completion_reason is None:
            record.completion_reason = "cancelled"
        self._signal(record, mode)
        try:
            record.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._signal(record, "kill")
            record.process.wait(timeout=max(timeout, 0.1))
        # The shell may exit before descendants which ignored SIGTERM.
        self._signal(record, "kill")
        record.owns_group = False
        if record.reader is not None:
            record.reader.join(timeout=max(timeout, 0.2))
        return self.poll(process_id)

    def cleanup(
        self, *, mode: str = "terminate", timeout: float = 2.0
    ) -> dict[str, Any]:
        """Stop all owned groups and close pipes; retain logs on disk."""
        stopped: list[str] = []
        errors: dict[str, str] = {}
        with self._lock:
            removed = list(self._processes)
            for process_id, record in self._processes.items():
                was_running = record.process.poll() is None
                try:
                    self.stop(process_id, mode=mode, timeout=timeout)
                    if was_running:
                        stopped.append(process_id)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    errors[process_id] = str(exc)
                    logger.exception("Process cleanup failed: %s", process_id)
                finally:
                    record.stop_reader.set()
                    if record.reader is not None:
                        record.reader.join(timeout=1)
                    for stream in ("stdin", "stdout", "stderr"):
                        pipe = getattr(record.process, stream)
                        if pipe is not None:
                            pipe.close()
            self._processes.clear()
        return {
            "action": "process_cleanup",
            "status": "error" if errors else "completed",
            "result": (
                f"stopped={len(stopped)} removed={len(removed)} errors={len(errors)}"
            ),
            "stopped": stopped,
            "removed": removed,
            "errors": errors,
        }

    def _capture(self, record: ManagedProcess) -> None:
        """Drain both pipes fairly, including a bounded grace period after exit."""
        decoders = {
            stream: getincrementaldecoder("utf-8")("replace")
            for stream in ("stdout", "stderr")
        }
        exit_deadline = None
        try:
            with (
                selectors.DefaultSelector() as selector,
                open(record.log_path, "a", encoding="utf-8") as log,
            ):
                for stream in decoders:
                    pipe = getattr(record.process, stream)
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, stream)
                while not record.stop_reader.is_set():
                    if (
                        record.deadline is not None
                        and time.monotonic() >= record.deadline
                        and record.process.poll() is None
                    ):
                        record.completion_reason = "timeout"
                        self._signal(record, "kill")
                        record.deadline = None
                    if record.process.poll() is not None:
                        if exit_deadline is None:
                            exit_deadline = time.monotonic() + POST_EXIT_DRAIN_SECONDS
                        if not selector.get_map() or time.monotonic() >= exit_deadline:
                            break
                    for key, _ in selector.select(0.02):
                        try:
                            chunk = os.read(key.fd, 4096)
                        except BlockingIOError:
                            continue
                        text = decoders[key.data].decode(chunk, final=not chunk)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        if text:
                            with record.changed:
                                record.append_output(key.data, text)
                                while (
                                    len(record.events) > self._max_events_per_process
                                    or record.buffered_chars > MAX_BUFFER_CHARS
                                ):
                                    record.buffered_chars -= len(
                                        record.events.popleft().text
                                    )
                                available = max(0, MAX_LOG_CHARS - record.log_chars)
                                retained = text[:available]
                                log.write(retained)
                                log.flush()
                                record.log_chars += len(retained)
                                record.log_truncated |= len(retained) < len(text)
                                record.changed.notify_all()
                            if time.monotonic() - record.last_output_event >= 0.1:
                                record.last_output_event = time.monotonic()
                                self._emit(record, "output")
                record.streams_closed = not selector.get_map()
        except (OSError, ValueError) as exc:
            logger.exception("Process capture failed: %s", record.process_id)
            record.reader_error = str(exc)
            self._signal(record, "kill")
            record.process.wait()
        finally:
            for stream in ("stdout", "stderr"):
                pipe = getattr(record.process, stream)
                if pipe is not None:
                    pipe.close()
            with record.changed:
                record.reader_done = True
                record.changed.notify_all()
            self._emit(record, "output")
            self.enable_notifications(
                record.process_id, enabled=record.notify_on_complete
            )

    def enable_notifications(self, process_id: str, *, enabled: bool = True) -> None:
        """Arm one completion event, including completion racing with yield."""
        record = self._processes.get(process_id)
        if record is None:
            return
        with record.changed:
            record.notify_on_complete = enabled
            if not enabled or not record.reader_done or record.notified:
                return
            record.notified = True
        self._emit(record, "completed")

    def _emit(self, record: ManagedProcess, kind: str) -> None:
        if record.on_event is None:
            return
        with record.changed:
            payload = self._snapshot(
                record,
                output="",
                since_sequence=0,
                next_sequence=record.next_sequence - 1,
            )
            payload["output_tail"] = "".join(event.text for event in record.events)[
                -8192:
            ]
            payload["session_id"], payload["agent_id"] = record.owner
        try:
            record.on_event(kind, payload)
        except Exception:
            logger.exception("Process event callback failed: %s", record.process_id)

    def _snapshot(
        self,
        record: ManagedProcess,
        *,
        output: str,
        since_sequence: int,
        next_sequence: int,
    ) -> dict[str, Any]:
        status = record.status()
        returncode = record.process.poll()
        error = record.reader_error
        if record.completion_reason == "timeout":
            error = "timeout"
        elif (
            status == "exited"
            and returncode not in (0, None)
            and record.completion_reason != "cancelled"
        ):
            error = error or "command_failed"
        result = (
            f"process_id={record.process_id} status={status} "
            f"returncode={returncode} next_sequence={next_sequence} "
            f"reason={record.completion_reason or status}"
        )
        if output:
            result += f"\n{output}"
        else:
            result += (
                "\nNo new output."
                if status != "exited"
                else "\nProcess finished; no new output."
            )
        result += f"\nlog_path={record.log_path}"
        if record.log_truncated:
            result += "\nRetained log reached its size limit."
        if record.reader_error:
            result += f"\nOutput capture failed: {record.reader_error}"
        return {
            "action": "process",
            "status": "error" if error else "completed",
            "result": result,
            "process_id": record.process_id,
            "process_status": status,
            "returncode": returncode,
            "command": record.command,
            "cwd": record.cwd,
            "env_keys": sorted(record.env_overrides),
            "started_at": record.started_at,
            "since_sequence": since_sequence,
            "next_sequence": next_sequence,
            "output": output,
            "log_path": record.log_path,
            "log_truncated": record.log_truncated,
            "streams_closed": record.streams_closed,
            "reader_error": record.reader_error,
            "error": error,
            "completion_reason": record.completion_reason
            or ("exited" if status == "exited" else None),
        }

    def _error(self, process_id: str, error: str) -> dict[str, Any]:
        return {
            "action": "process",
            "status": "error",
            "result": error,
            "error": error,
            "process_id": process_id,
        }


__all__ = ["ManagedProcess", "ProcessOutputEvent", "ProcessRuntime"]
