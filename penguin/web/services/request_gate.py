"""Bounded session-scoped request serialization for chat transports."""

from __future__ import annotations

import asyncio
import math
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

__all__ = [
    "SessionRequestGateTimeout",
    "get_session_request_gate_timeout_seconds",
    "session_request_gate",
]


DEFAULT_SESSION_REQUEST_GATE_TIMEOUT_SECONDS = 10.0


class SessionRequestGateTimeout(TimeoutError):
    """Raised when another request owns a session longer than the wait budget."""

    def __init__(self, session_id: str, timeout_seconds: float) -> None:
        self.session_id = session_id
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"session {session_id!r} remained busy for {timeout_seconds:g} seconds"
        )


def get_session_request_gate_timeout_seconds() -> float:
    """Return the bounded wait budget for REST and WebSocket chat requests."""

    raw_value = os.getenv(
        "PENGUIN_SESSION_REQUEST_GATE_TIMEOUT_SECONDS",
        str(DEFAULT_SESSION_REQUEST_GATE_TIMEOUT_SECONDS),
    )
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_SESSION_REQUEST_GATE_TIMEOUT_SECONDS
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_SESSION_REQUEST_GATE_TIMEOUT_SECONDS
    return value


def _gate_state(owner: Any) -> tuple[dict[str, asyncio.Lock], dict[str, int]]:
    gates = getattr(owner, "_opencode_request_gates", None)
    if not isinstance(gates, dict):
        gates = {}
        setattr(owner, "_opencode_request_gates", gates)

    users = getattr(owner, "_opencode_request_gate_users", None)
    if not isinstance(users, dict):
        users = {}
        setattr(owner, "_opencode_request_gate_users", users)
    return gates, users


def _track_gate_task(
    owner: Any, gate_key: str
) -> tuple[asyncio.Task[Any] | None, bool]:
    """Make queued gate ownership visible to session abort."""

    task = asyncio.current_task()
    if task is None:
        return None, False
    tasks_by_session = getattr(owner, "_opencode_process_tasks", None)
    if not isinstance(tasks_by_session, dict):
        tasks_by_session = {}
        setattr(owner, "_opencode_process_tasks", tasks_by_session)
    tasks = tasks_by_session.get(gate_key)
    if not isinstance(tasks, set):
        tasks = set()
        tasks_by_session[gate_key] = tasks
    already_tracked = task in tasks
    tasks.add(task)
    return task, already_tracked


def _release_gate_task(
    owner: Any,
    gate_key: str,
    task: asyncio.Task[Any] | None,
    *,
    already_tracked: bool,
) -> None:
    if task is None or already_tracked:
        return
    tasks_by_session = getattr(owner, "_opencode_process_tasks", None)
    if not isinstance(tasks_by_session, dict):
        return
    tasks = tasks_by_session.get(gate_key)
    if not isinstance(tasks, set):
        return
    tasks.discard(task)
    if not tasks:
        tasks_by_session.pop(gate_key, None)


@asynccontextmanager
async def session_request_gate(
    owner: Any,
    session_id: str | None,
    *,
    timeout_seconds: float | None = None,
) -> AsyncIterator[float]:
    """Acquire one session gate with a deadline and release it on every path.

    The usage counter lets idle gates be pruned without creating a second lock
    while an existing waiter still holds a reference to the first one.
    """

    gate_key = session_id.strip() if isinstance(session_id, str) else ""
    gate_key = gate_key or "__default__"
    timeout = (
        get_session_request_gate_timeout_seconds()
        if timeout_seconds is None
        else float(timeout_seconds)
    )
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be finite and greater than zero")

    gates, users = _gate_state(owner)
    gate = gates.get(gate_key)
    if not isinstance(gate, asyncio.Lock):
        gate = asyncio.Lock()
        gates[gate_key] = gate
    users[gate_key] = int(users.get(gate_key, 0)) + 1
    request_task, already_tracked = _track_gate_task(owner, gate_key)

    acquired = False
    wait_started = time.perf_counter()
    try:
        try:
            await asyncio.wait_for(gate.acquire(), timeout=timeout)
            acquired = True
        except asyncio.TimeoutError as exc:
            raise SessionRequestGateTimeout(gate_key, timeout) from exc
        yield (time.perf_counter() - wait_started) * 1000
    finally:
        if acquired and gate.locked():
            gate.release()

        remaining = max(0, int(users.get(gate_key, 1)) - 1)
        if remaining:
            users[gate_key] = remaining
        else:
            users.pop(gate_key, None)
            if gates.get(gate_key) is gate and not gate.locked():
                gates.pop(gate_key, None)
        _release_gate_task(
            owner,
            gate_key,
            request_task,
            already_tracked=already_tracked,
        )
