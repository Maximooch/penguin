"""OpenCode event normalization helpers for Penguin SSE streams."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

GLOBAL_STATUS_EVENTS = {
    "vcs.branch.updated",
    "lsp.updated",
    "lsp.client.diagnostics",
}
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def normalize_directory(directory: Optional[str]) -> Optional[str]:
    """Return a resolved directory string when one can be trusted."""
    if not isinstance(directory, str) or not directory.strip():
        return None
    try:
        return str(Path(directory).expanduser().resolve())
    except Exception:
        return None


def directory_matches(left: Optional[str], right: Optional[str]) -> bool:
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


def extract_event_session(properties: dict[str, Any]) -> Optional[str]:
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


def extract_event_directory(properties: dict[str, Any]) -> Optional[str]:
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


def _extract_event_agent(properties: dict[str, Any]) -> Optional[str]:
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


def _extract_source_id(properties: dict[str, Any]) -> Optional[str]:
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
    default_agent_id: Optional[str] = None,
    default_directory: Optional[str] = None,
    default_session_id: Optional[str] = None,
    now_ms: Optional[int] = None,
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

    directory = normalize_directory(extract_event_directory(properties)) or normalize_directory(
        default_directory
    )
    if directory:
        properties["directory"] = directory

    agent_id = _extract_event_agent(properties) or default_agent_id
    if agent_id and not isinstance(properties.get("agentID"), str):
        properties["agentID"] = agent_id

    source_id = _extract_source_id(properties)
    event_id = data.get("id")
    if not isinstance(event_id, str) or not event_id:
        id_suffix = source_id or str(order)
        event_id = f"{event_type}:{session_id or '-'}:{id_suffix}"

    return {
        "id": event_id,
        "order": order,
        "time": now_ms if now_ms is not None else int(time.time() * 1000),
        "type": event_type,
        "properties": properties,
    }


def sse_event_frame(event: dict[str, Any]) -> str:
    """Serialize a normalized OpenCode event as one SSE frame."""
    event_id = event.get("id")
    prefix = f"id: {event_id}\n" if isinstance(event_id, str) and event_id else ""
    return f"{prefix}data: {json.dumps(event)}\n\n"


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
        {
            "type": event_type,
            "properties": properties,
        },
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
