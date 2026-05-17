"""Persistent terminal/process runtime for Penguin tools."""

from __future__ import annotations

import logging
import os
import select
import signal
import subprocess
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Deque, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessOutputEvent:
    """One stdout/stderr chunk captured from a managed process."""

    sequence: int
    stream: str
    text: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ManagedProcess:
    """State for one process owned by the terminal runtime."""

    process_id: str
    command: str
    cwd: str
    process: subprocess.Popen[str]
    env_overrides: dict[str, str] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    events: Deque[ProcessOutputEvent] = field(default_factory=deque)
    next_sequence: int = 1

    def append_output(self, stream: str, text: str) -> None:
        """Append output drained from stdout/stderr."""

        self.events.append(
            ProcessOutputEvent(
                sequence=self.next_sequence,
                stream=stream,
                text=text,
            )
        )
        self.next_sequence += 1

    def status(self) -> str:
        """Return the current process lifecycle status."""

        return "running" if self.process.poll() is None else "exited"


class ProcessRuntime:
    """Manage persistent shell processes with bounded output reads."""

    def __init__(self, *, max_events_per_process: int = 10_000) -> None:
        self._processes: dict[str, ManagedProcess] = {}
        self._max_events_per_process = max_events_per_process

    def start(
        self,
        command: str,
        *,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        process_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Start a persistent shell process.

        Args:
            command: Shell command to run.
            cwd: Optional working directory. Defaults to the current directory.
            env: Optional environment overrides.
            process_id: Optional caller-provided stable id.

        Returns:
            Structured process metadata suitable for a tool result.
        """

        resolved_cwd = str(Path(cwd or os.getcwd()).expanduser().resolve())
        effective_env = os.environ.copy()
        effective_env.update(env or {})
        effective_env.setdefault("TERM", "dumb")
        effective_env.setdefault("NO_COLOR", "1")
        effective_env.setdefault("RICH_NO_MARKUP", "1")
        resolved_id = process_id or f"proc_{uuid.uuid4().hex[:12]}"
        existing = self._processes.get(resolved_id)
        if existing is not None and existing.process.poll() is None:
            return self._error(resolved_id, "process_id_already_exists")
        try:
            process = subprocess.Popen(
                ["bash", "-lc", command],
                cwd=resolved_cwd,
                env=effective_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            return self._error(resolved_id, f"start_failed: {exc}")
        record = ManagedProcess(
            process_id=resolved_id,
            command=command,
            cwd=resolved_cwd,
            process=process,
            env_overrides={key: str(value) for key, value in (env or {}).items()},
        )
        self._set_nonblocking(process.stdout)
        self._set_nonblocking(process.stderr)
        self._processes[resolved_id] = record
        return self._snapshot(record, output="", since_sequence=0)

    def poll(
        self,
        process_id: str,
        *,
        since_sequence: int = 0,
        max_chars: int = 12_000,
    ) -> dict[str, Any]:
        """Return bounded process output and current lifecycle state."""

        record = self._processes.get(process_id)
        if record is None:
            return self._error(process_id, "unknown_process_id")
        self._drain_pipes(record)
        output, next_sequence, truncated = self._collect_output(
            record,
            since_sequence=since_sequence,
            max_chars=max_chars,
        )
        snapshot = self._snapshot(
            record,
            output=output,
            since_sequence=since_sequence,
            next_sequence=next_sequence,
        )
        snapshot["truncated"] = truncated
        return snapshot

    def write_stdin(self, process_id: str, text: str) -> dict[str, Any]:
        """Write text to a running process stdin."""

        record = self._processes.get(process_id)
        if record is None:
            return self._error(process_id, "unknown_process_id")
        if record.process.poll() is not None:
            return self._error(process_id, "process_not_running")
        if record.process.stdin is None:
            return self._error(process_id, "stdin_unavailable")
        record.process.stdin.write(text)
        record.process.stdin.flush()
        return self._snapshot(record, output="", since_sequence=0)

    def stop(
        self,
        process_id: str,
        *,
        mode: str = "terminate",
        timeout: float = 2.0,
    ) -> dict[str, Any]:
        """Interrupt, terminate, or kill a managed process."""

        record = self._processes.get(process_id)
        if record is None:
            return self._error(process_id, "unknown_process_id")
        if record.process.poll() is None:
            if mode == "interrupt":
                record.process.send_signal(signal.SIGINT)
            elif mode == "kill":
                record.process.kill()
            else:
                record.process.terminate()
            try:
                record.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record.process.kill()
                record.process.wait(timeout=timeout)
        self._drain_pipes(record)
        return self.poll(process_id)

    def _set_nonblocking(self, pipe: Any) -> None:
        if pipe is None:
            return
        try:
            import fcntl

            flags = fcntl.fcntl(pipe.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(pipe.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)
        except Exception as exc:
            logger.debug("Unable to set process pipe nonblocking: %s", exc)

    def _drain_pipes(self, record: ManagedProcess) -> None:
        for stream in ("stdout", "stderr"):
            pipe = getattr(record.process, stream)
            if pipe is None:
                continue
            fd = pipe.fileno()
            while True:
                try:
                    ready, _, _ = select.select([fd], [], [], 0)
                    if not ready:
                        break
                    chunk = os.read(fd, 4096)
                except BlockingIOError:
                    break
                except (OSError, ValueError):
                    break
                if not chunk:
                    break
                record.append_output(
                    stream,
                    chunk.decode(errors="replace"),
                )
                while len(record.events) > self._max_events_per_process:
                    record.events.popleft()

    def _collect_output(
        self,
        record: ManagedProcess,
        *,
        since_sequence: int,
        max_chars: int,
    ) -> tuple[str, int, bool]:
        events = [event for event in record.events if event.sequence > since_sequence]
        next_sequence = record.next_sequence
        lines = [f"[{event.stream}] {event.text}" for event in events]
        output = "".join(lines)
        max_chars = max(0, int(max_chars))
        if max_chars == 0:
            return "", next_sequence, bool(output)
        truncated = max_chars > 0 and len(output) > max_chars
        if truncated:
            output = output[-max_chars:]
        return output, next_sequence, truncated

    def _snapshot(
        self,
        record: ManagedProcess,
        *,
        output: str,
        since_sequence: int,
        next_sequence: Optional[int] = None,
    ) -> dict[str, Any]:
        returncode = record.process.poll()
        status = "running" if returncode is None else "exited"
        next_value = next_sequence if next_sequence is not None else record.next_sequence
        result = (
            f"process_id={record.process_id} status={status} "
            f"returncode={returncode}"
        )
        if output:
            result = f"{result}\n{output}"
        return {
            "action": "process",
            "status": "completed",
            "result": result,
            "process_id": record.process_id,
            "process_status": status,
            "returncode": returncode,
            "command": record.command,
            "cwd": record.cwd,
            "env_keys": sorted(record.env_overrides),
            "started_at": record.started_at,
            "since_sequence": since_sequence,
            "next_sequence": next_value,
            "output": output,
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
