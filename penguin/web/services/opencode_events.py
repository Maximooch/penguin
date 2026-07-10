"""OpenCode event normalization helpers for Penguin SSE streams."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from penguin.system.runtime_diagnostics import (
    mark_runtime_progress,
    record_runtime_duration,
)
from penguin.system.runtime_events import (
    opencode_payload_from_runtime_event,
    runtime_event_from_opencode,
    wrap_opencode_event,
)

if TYPE_CHECKING:
    import logging

GLOBAL_STATUS_EVENTS = {
    "vcs.branch.updated",
    "lsp.updated",
    "lsp.client.diagnostics",
}
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def normalize_directory(directory: str | None) -> str | None:
    """Return a resolved directory string when one can be trusted."""
    if not isinstance(directory, str) or not directory.strip():
        return None
    try:
        return str(Path(directory).expanduser().resolve())
    except Exception:
        return None


def directory_matches(left: str | None, right: str | None) -> bool:
    """Return whether two directory strings point at the same filesystem path."""
    left_norm = normalize_directory(left)
    right_norm = normalize_directory(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    try:
        return Path(left_norm).samefile(right_norm)
    except Exception:
        return False


def extract_event_session(properties: dict[str, Any]) -> str | None:
    """Extract the best session id from a projected OpenCode event payload."""
    for key in ("sessionID", "conversation_id", "session_id"):
        value = properties.get(key)
        if isinstance(value, str) and value:
            return value

    for parent_key in ("part", "info"):
        nested = properties.get(parent_key)
        if not isinstance(nested, dict):
            continue
        for key in ("sessionID", "conversation_id", "session_id"):
            value = nested.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def extract_event_directory(properties: dict[str, Any]) -> str | None:
    """Extract the best workspace directory from a projected event payload."""
    direct = properties.get("directory")
    if isinstance(direct, str) and direct:
        return direct

    for parent_key in ("info", "path", "part"):
        nested = properties.get(parent_key)
        if not isinstance(nested, dict):
            continue
        value = nested.get("directory")
        if isinstance(value, str) and value:
            return value
        path = nested.get("path")
        if isinstance(path, dict):
            cwd = path.get("cwd")
            if isinstance(cwd, str) and cwd:
                return cwd
        cwd = nested.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
    return None


def _extract_event_agent(properties: dict[str, Any]) -> str | None:
    for key in ("agentID", "agent_id"):
        value = properties.get(key)
        if isinstance(value, str) and value:
            return value
    part = properties.get("part")
    if isinstance(part, dict):
        for key in ("agentID", "agent_id"):
            value = part.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _extract_source_id(properties: dict[str, Any]) -> str | None:
    for key in ("id", "requestID", "messageID", "partID"):
        value = properties.get(key)
        if isinstance(value, str) and value:
            return value
    for parent_key in ("part", "info"):
        nested = properties.get(parent_key)
        if not isinstance(nested, dict):
            continue
        for key in ("id", "messageID", "partID"):
            value = nested.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def normalize_opencode_event(
    data: dict[str, Any],
    *,
    order: int,
    default_agent_id: str | None = None,
    default_directory: str | None = None,
    default_session_id: str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any] | None:
    """Return a stable TUI-facing event payload or None for malformed data."""
    event_type = data.get("type")
    if not isinstance(event_type, str) or not event_type:
        return None

    raw_properties = data.get("properties")
    properties = dict(raw_properties) if isinstance(raw_properties, dict) else {}

    session_id = extract_event_session(properties) or default_session_id
    if session_id and not isinstance(properties.get("sessionID"), str):
        properties["sessionID"] = session_id

    directory = normalize_directory(
        extract_event_directory(properties)
    ) or normalize_directory(default_directory)
    if directory:
        properties["directory"] = directory

    agent_id = _extract_event_agent(properties) or default_agent_id
    if agent_id and not isinstance(properties.get("agentID"), str):
        properties["agentID"] = agent_id

    runtime_event = runtime_event_from_opencode(
        {
            "id": data.get("id"),
            "runtime_event": data.get("runtime_event"),
            "type": event_type,
            "properties": properties,
        },
        default_agent_id=default_agent_id,
        default_directory=default_directory,
        default_session_id=default_session_id,
        now_ms=now_ms,
        sequence=order,
    )
    if runtime_event is None:
        return None
    return opencode_payload_from_runtime_event(runtime_event)


def sse_event_frame(event: dict[str, Any]) -> str:
    """Serialize a normalized OpenCode event as one SSE frame."""
    event_id = event.get("id")
    prefix = f"id: {event_id}\n" if isinstance(event_id, str) and event_id else ""
    return f"{prefix}data: {json.dumps(event)}\n\n"


def record_opencode_event(core: Any, data: dict[str, Any]) -> dict[str, Any] | None:
    """Persist an OpenCode event's RuntimeEvent envelope and return it."""
    projection_started = time.perf_counter()
    runtime_event = runtime_event_from_opencode(data)
    record_runtime_duration(
        "event.projection",
        (time.perf_counter() - projection_started) * 1000,
    )
    if runtime_event is None:
        return None

    from penguin.system.runtime_event_ledger import get_runtime_event_ledger

    ledger_started = time.perf_counter()
    get_runtime_event_ledger(core).append(runtime_event)
    record_runtime_duration(
        "ledger.append",
        (time.perf_counter() - ledger_started) * 1000,
    )

    # Mutate the shared EventBus payload so downstream live subscribers use the
    # same event identity and ordering that was persisted at emission time.
    data["runtime_event"] = runtime_event
    projected = opencode_payload_from_runtime_event(runtime_event)
    data["id"] = projected.get("id")
    projected_type = projected.get("type")
    if isinstance(projected_type, str) and projected_type:
        data["type"] = projected_type
    data["time"] = projected.get("time")
    data["order"] = projected.get("order")
    projected_properties = projected.get("properties")
    if isinstance(projected_properties, dict):
        data["properties"] = projected_properties
    mark_runtime_progress("ui")
    return runtime_event


async def emit_opencode_event(
    core: Any,
    event_type: str,
    properties: dict[str, Any],
) -> None:
    """Emit an OpenCode-compatible event through the runtime EventBus."""
    event_bus = getattr(core, "event_bus", None)
    emit = getattr(event_bus, "emit", None)
    if not callable(emit):
        return
    await emit(
        "opencode_event",
        wrap_opencode_event(event_type, properties),
    )


def schedule_opencode_event(
    core_getter: Callable[[], Any],
    event_type: str,
    properties: dict[str, Any],
    *,
    logger: logging.Logger | None = None,
) -> None:
    """Schedule OpenCode event emission from sync or async route contexts."""

    async def _runner() -> None:
        try:
            await emit_opencode_event(core_getter(), event_type, properties)
        except Exception:
            if logger:
                logger.debug(
                    "Failed to emit opencode event %s",
                    event_type,
                    exc_info=True,
                )

    def _track_task(task: asyncio.Task[None]) -> None:
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)

    try:
        loop = asyncio.get_running_loop()
        _track_task(loop.create_task(_runner()))
        return
    except RuntimeError:
        pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            _track_task(loop.create_task(_runner()))
        else:
            loop.run_until_complete(_runner())
    except RuntimeError:
        try:
            asyncio.run(_runner())
        except Exception:
            if logger:
                logger.debug(
                    "Failed to schedule opencode event %s",
                    event_type,
                    exc_info=True,
                )
    except Exception:
        if logger:
            logger.debug(
                "Failed to schedule opencode event %s",
                event_type,
                exc_info=True,
            )
