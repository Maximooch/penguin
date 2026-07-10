"""Bounded request timing, liveness, and connection diagnostics.

This module deliberately accepts stage names and numeric durations only. Prompt
content, tool arguments, credentials, and full outputs have no place in the runtime
diagnostics contract.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Callable, Iterator

__all__ = [
    "ConnectionHistory",
    "RuntimeDiagnosticsRecorder",
    "current_runtime_diagnostics",
    "get_runtime_diagnostics_history",
    "mark_runtime_progress",
    "record_runtime_duration",
    "runtime_diagnostics_scope",
    "store_runtime_diagnostics",
]

_CURRENT_RUNTIME_DIAGNOSTICS: ContextVar[RuntimeDiagnosticsRecorder | None] = (
    ContextVar("penguin_runtime_diagnostics", default=None)
)
_PROGRESS_CHANNELS = ("provider", "tool", "ui", "runtime")
_SAFE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
_HISTORY_ATTR = "_runtime_diagnostics_history_v1"
_HISTORY_LOCK_ATTR = "_runtime_diagnostics_history_lock_v1"


@dataclass
class _StageMetric:
    """Mutable aggregate for one measured stage."""

    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    last_ms: float = 0.0

    def add(self, duration_ms: float) -> None:
        """Add one non-negative duration sample."""

        duration = max(0.0, float(duration_ms))
        self.count += 1
        self.total_ms += duration
        self.max_ms = max(self.max_ms, duration)
        self.last_ms = duration

    def to_dict(self) -> dict[str, int | float]:
        """Return a stable rounded diagnostics representation."""

        return {
            "count": self.count,
            "total_ms": _round_ms(self.total_ms),
            "max_ms": _round_ms(self.max_ms),
            "last_ms": _round_ms(self.last_ms),
        }


class RuntimeDiagnosticsRecorder:
    """Thread-safe bounded diagnostics for one request lifecycle."""

    def __init__(
        self,
        *,
        request_id: str,
        session_id: str | None,
        monotonic: Callable[[], float] = time.monotonic,
        max_events: int = 128,
    ) -> None:
        """Initialize an empty recorder using an injectable monotonic clock."""

        self.request_id = str(request_id or "unknown")[:128]
        self.session_id = str(session_id)[:128] if session_id else None
        self._monotonic = monotonic
        self._started_at = monotonic()
        self._finished_at: float | None = None
        self._terminal_status: str | None = None
        self._stages: dict[str, _StageMetric] = {}
        self._last_progress: dict[str, float] = {}
        self._events: deque[dict[str, str | float]] = deque(maxlen=max(1, max_events))
        self._lock = threading.RLock()

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        """Measure one synchronous or awaited block with the monotonic clock."""

        started_at = self._monotonic()
        try:
            yield
        finally:
            self.record_duration(
                stage,
                (self._monotonic() - started_at) * 1000,
            )

    def record_duration(self, stage: str, duration_ms: float) -> None:
        """Record one numeric duration under a normalized bounded stage name."""

        name = _normalize_name(stage)
        with self._lock:
            metric = self._stages.setdefault(name, _StageMetric())
            metric.add(duration_ms)
            self._events.append(
                {
                    "kind": "duration",
                    "name": name,
                    "monotonic_ms": _round_ms(self._monotonic() * 1000),
                }
            )

    def mark_progress(self, channel: str) -> None:
        """Record real progress for one provider/tool/UI/runtime channel."""

        normalized = _normalize_name(channel)
        if normalized not in _PROGRESS_CHANNELS:
            raise ValueError(
                f"Progress channel must be one of {_PROGRESS_CHANNELS}; "
                f"received {channel!r}"
            )
        now = self._monotonic()
        with self._lock:
            self._last_progress[normalized] = now
            self._events.append(
                {
                    "kind": "progress",
                    "name": normalized,
                    "monotonic_ms": _round_ms(now * 1000),
                }
            )

    def finish(self, status: str) -> None:
        """Record one idempotent terminal status and completion timestamp."""

        with self._lock:
            if self._finished_at is not None:
                return
            self._finished_at = self._monotonic()
            self._terminal_status = _normalize_name(status)

    def snapshot(self) -> dict[str, object]:
        """Return a content-free diagnostics snapshot for logs/API/debug export."""

        now = self._monotonic()
        with self._lock:
            end = self._finished_at or now
            progress_ages = {
                channel: (
                    _round_ms((now - self._last_progress[channel]) * 1000)
                    if channel in self._last_progress
                    else None
                )
                for channel in _PROGRESS_CHANNELS
            }
            stages = {
                name: metric.to_dict() for name, metric in sorted(self._stages.items())
            }
            tool_execution_ms = _stage_total(stages, "tool.execution")
            tool_batch_ms = _stage_total(stages, "tool.batch")
            return {
                "request_id": self.request_id,
                "session_id": self.session_id,
                "request_age_ms": _round_ms((end - self._started_at) * 1000),
                "terminal_status": self._terminal_status,
                "progress_age_ms": progress_ages,
                "stages": stages,
                "derived": {
                    "tool_execution_ms": tool_execution_ms,
                    "tool_batch_ms": tool_batch_ms,
                    "tool_orchestration_ms": _round_ms(
                        max(0.0, tool_batch_ms - tool_execution_ms)
                    ),
                },
                "events": list(self._events),
            }


class ConnectionHistory:
    """Bounded content-free connection lifecycle history."""

    def __init__(
        self,
        *,
        max_entries: int = 64,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize an empty bounded history."""

        self._entries: deque[dict[str, str | float | None]] = deque(
            maxlen=max(1, max_entries)
        )
        self._monotonic = monotonic
        self._lock = threading.RLock()

    def record(
        self,
        state: str,
        *,
        transport: str,
        reason_code: str | None = None,
    ) -> None:
        """Record a normalized lifecycle state without URLs or exception text."""

        entry: dict[str, str | float | None] = {
            "state": _normalize_name(state),
            "transport": _normalize_name(transport),
            "reason_code": _normalize_name(reason_code) if reason_code else None,
            "monotonic_ms": _round_ms(self._monotonic() * 1000),
        }
        with self._lock:
            self._entries.append(entry)

    def snapshot(self) -> list[dict[str, str | float | None]]:
        """Return a copy of the bounded connection history."""

        with self._lock:
            return [dict(entry) for entry in self._entries]


@contextmanager
def runtime_diagnostics_scope(
    recorder: RuntimeDiagnosticsRecorder,
) -> Iterator[RuntimeDiagnosticsRecorder]:
    """Install ``recorder`` in the current async/contextvars scope."""

    token: Token[RuntimeDiagnosticsRecorder | None] = _CURRENT_RUNTIME_DIAGNOSTICS.set(
        recorder
    )
    try:
        yield recorder
    finally:
        _CURRENT_RUNTIME_DIAGNOSTICS.reset(token)


def current_runtime_diagnostics() -> RuntimeDiagnosticsRecorder | None:
    """Return the recorder active in the current context, if any."""

    return _CURRENT_RUNTIME_DIAGNOSTICS.get()


def record_runtime_duration(stage: str, duration_ms: float) -> None:
    """Record a duration when a request diagnostics scope is active."""

    recorder = current_runtime_diagnostics()
    if recorder is not None:
        recorder.record_duration(stage, duration_ms)


def mark_runtime_progress(channel: str) -> None:
    """Mark progress when a request diagnostics scope is active."""

    recorder = current_runtime_diagnostics()
    if recorder is not None:
        recorder.mark_progress(channel)


def store_runtime_diagnostics(
    owner: Any,
    recorder: RuntimeDiagnosticsRecorder,
    *,
    max_entries: int = 100,
) -> dict[str, object]:
    """Store a bounded snapshot on a runtime owner for debug export."""

    lock = getattr(owner, _HISTORY_LOCK_ATTR, None)
    if lock is None:
        lock = threading.RLock()
        setattr(owner, _HISTORY_LOCK_ATTR, lock)
    with lock:
        history = getattr(owner, _HISTORY_ATTR, None)
        if not isinstance(history, deque) or history.maxlen != max(1, max_entries):
            history = deque(history or (), maxlen=max(1, max_entries))
            setattr(owner, _HISTORY_ATTR, history)
        snapshot = recorder.snapshot()
        history.append(snapshot)
        return snapshot


def get_runtime_diagnostics_history(owner: Any) -> list[dict[str, object]]:
    """Return a copy of bounded request diagnostics stored on ``owner``."""

    history = getattr(owner, _HISTORY_ATTR, None)
    if not isinstance(history, deque):
        return []
    return [dict(entry) for entry in history]


def _normalize_name(value: object) -> str:
    """Return a bounded low-cardinality diagnostics label."""

    normalized = _SAFE_NAME_PATTERN.sub("_", str(value or "unknown")).strip("_")
    return (normalized or "unknown")[:64]


def _round_ms(value: float) -> float:
    """Round milliseconds for stable tests and compact diagnostics."""

    return round(float(value), 3)


def _stage_total(stages: dict[str, object], name: str) -> float:
    """Read one aggregate stage total from a snapshot map."""

    value = stages.get(name)
    if isinstance(value, dict):
        total = value.get("total_ms", 0.0)
        if isinstance(total, (int, float)):
            return float(total)
    return 0.0
