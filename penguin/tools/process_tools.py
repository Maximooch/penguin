"""Session-scoped shell tool service and background completion delivery."""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import logging
import math
import os
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from penguin.tools.process_runtime import ProcessRuntime

logger = logging.getLogger(__name__)
MIN_PROCESS_WAIT_MS = 5000
PROCESS_TOOL_NAMES = frozenset(
    {
        "execute_command",
        "process_start",
        "process_poll",
        "process_write_stdin",
        "process_stop",
    }
)


def process_owner(context: dict[str, Any]) -> tuple[str, str]:
    """Resolve ownership from trusted execution context, never tool arguments."""
    return (
        str(context.get("session_id") or context.get("conversation_id") or ""),
        str(context.get("agent_id") or "agent"),
    )


class ProcessTools:
    """Adapt shell tools onto a single runtime without sharing session cursors."""

    def __init__(self, runtime: ProcessRuntime) -> None:
        self.runtime = runtime
        atexit.register(self.cleanup)
        self._lock = threading.RLock()
        self._observed: set[str] = set()
        self._output_inflight: set[str] = set()
        self._pending: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
        self._listeners: dict[
            tuple[str, str],
            tuple[asyncio.AbstractEventLoop, Callable[..., Awaitable[None]]],
        ] = {}

    def bind(
        self, owner: tuple[str, str], emit: Callable[..., Awaitable[None]]
    ) -> None:
        """Bind an event sink on its owning loop; payloads carry explicit scope."""
        with self._lock:
            self._listeners[owner] = (asyncio.get_running_loop(), emit)

    def pending(self, owner: tuple[str, str]) -> list[dict[str, Any]]:
        """Peek at completion notices until the conversation persists them."""
        with self._lock:
            return list(self._pending.get(owner, {}).values())

    def acknowledge(self, owner: tuple[str, str], process_id: str) -> None:
        """Remove an observed completion notice without consuming process output."""
        with self._lock:
            self._observed.add(process_id)
            notices = self._pending.get(owner, {})
            notices.pop(process_id, None)
            if not notices:
                self._pending.pop(owner, None)

    def _on_event(self, kind: str, payload: dict[str, Any]) -> None:
        owner = (payload["session_id"], payload["agent_id"])
        with self._lock:
            if kind == "completed" and payload["process_id"] not in self._observed:
                self._pending.setdefault(owner, {})[payload["process_id"]] = payload
            listener = self._listeners.get(owner)
        if listener is None or listener[0].is_closed():
            return
        loop, emit = listener
        process_id = payload["process_id"]
        if kind == "output":
            with self._lock:
                if process_id in self._output_inflight:
                    return
                self._output_inflight.add(process_id)

        async def deliver() -> None:
            try:
                await emit(kind, payload)
            except Exception:
                logger.exception("Unable to deliver process event for %s", owner)
            finally:
                if kind == "output":
                    with self._lock:
                        self._output_inflight.discard(process_id)

        delivery = deliver()
        try:
            future = asyncio.run_coroutine_threadsafe(delivery, loop)
            # Observe cancellation/errors without blocking the pipe reader.
            future.add_done_callback(
                lambda done: None if done.cancelled() else done.exception()
            )
        except RuntimeError:
            delivery.close()
            with self._lock:
                self._output_inflight.discard(process_id)
            logger.debug("Owning loop closed before process event delivery")

    def execute(
        self, name: str, arguments: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a validated process operation within its owning session."""
        owner = process_owner(context)
        if name in {"execute_command", "process_start"}:
            return self._start(name, arguments, context, owner)
        process_id = str(arguments["process_id"])
        record = self.runtime._processes.get(process_id)
        if record is None or record.owner != owner:
            return self.runtime._error(process_id, "unknown_process_id")
        if name == "process_write_stdin":
            return self.runtime.write_stdin(process_id, arguments.get("text", ""))
        if name == "process_stop":
            return self.runtime.stop(
                process_id,
                mode=arguments.get("mode", "terminate"),
                timeout=float(arguments.get("timeout", 2)),
            )
        wait_ms = arguments.get("wait_ms", 5000)
        if arguments.get("since_sequence") is None and 0 <= wait_ms <= 60000:
            wait_ms = max(MIN_PROCESS_WAIT_MS, wait_ms)
        result = self.runtime.poll(
            process_id,
            since_sequence=arguments.get("since_sequence"),
            wait_ms=wait_ms,
            max_chars=arguments.get("max_chars", 12000),
            consumer_id=owner[1],
            request_id=context.get("tool_call_id"),
            cancel_event=context.get("process_cancel_event"),
        )
        if result.get("process_status") == "exited":
            self.acknowledge(owner, process_id)
        return result

    def _start(
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
        owner: tuple[str, str],
    ) -> dict[str, Any]:
        timeout = arguments.get("timeout_seconds")
        if timeout is None and os.environ.get("PENGUIN_TOOL_TIMEOUT") is not None:
            timeout = float(os.environ["PENGUIN_TOOL_TIMEOUT"])
        if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
            return self.runtime._error(
                "", "timeout_seconds must be finite and nonnegative"
            )
        yield_ms = arguments.get("yield_time_ms", 1000)
        if not math.isfinite(yield_ms) or not 0 <= yield_ms <= 60000:
            return self.runtime._error("", "yield_time_ms must be between 0 and 60000")
        if arguments.get("max_chars", 12000) < 0:
            return self.runtime._error("", "max_chars must be nonnegative")
        cancellation = context.get("process_cancel_event")
        if cancellation is not None and cancellation.is_set():
            return {
                "action": name,
                "status": "cancelled",
                "result": "Cancelled before start",
            }
        request_id = context.get("tool_call_id")
        process_id = None
        if request_id:
            identity = json.dumps([owner, request_id])
            process_id = "proc_" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        with self._lock:
            self._observed.intersection_update(self.runtime._processes)
            existing = self.runtime._processes.get(process_id) if process_id else None
            if existing is None:
                started = self.runtime.start(
                    arguments["command"],
                    cwd=arguments.get("cwd") or context.get("directory"),
                    env=arguments.get("env"),
                    process_id=process_id,
                    owner=owner,
                    timeout_seconds=timeout,
                    on_event=self._on_event,
                )
                if started["status"] == "error":
                    return started
                process_id = started["process_id"]
            elif existing.command != arguments["command"]:
                return self.runtime._error(
                    process_id, "tool_call_id reused with different command"
                )
            else:
                started = self.runtime._snapshot(
                    existing, output="", since_sequence=0, next_sequence=0
                )
        if name == "process_start":
            self.runtime.enable_notifications(process_id)
            return started
        result = self.runtime.poll(
            process_id,
            since_sequence=None,
            consumer_id=owner[1],
            request_id=request_id,
            wait_ms=yield_ms,
            wait_for_exit=True,
            max_chars=arguments.get("max_chars", 12000),
            cancel_event=context.get("process_cancel_event"),
        )
        cancellation = context.get("process_cancel_event")
        if cancellation is not None and cancellation.is_set():
            result = self.runtime.stop(process_id)
            result["status"] = "cancelled"
        elif result.get("process_status") != "exited":
            self.runtime.enable_notifications(process_id)
        else:
            self.acknowledge(owner, process_id)
        result.update(
            action="execute_command", tool="execute_command", timeout_seconds=timeout
        )
        if result.get("process_status") == "exited" and result.get(
            "returncode"
        ) not in (0, None):
            result["status"] = (
                "error" if result["status"] != "cancelled" else "cancelled"
            )
            result["error"] = result.get("error") or "command_failed"
        return result

    def cleanup(self) -> dict[str, Any]:
        """Stop workers before clearing event sinks and pending notices."""
        result = self.runtime.cleanup()
        with self._lock:
            self._pending.clear()
            self._observed.clear()
            self._listeners.clear()
            self._output_inflight.clear()
        return result


__all__ = ["PROCESS_TOOL_NAMES", "ProcessTools", "process_owner"]
