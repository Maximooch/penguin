"""Durable terminal snapshots and recoverable chat-continuation leases."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from penguin.core_runtime.session_lookup import find_session_store
from penguin.system.execution_context import normalize_directory

__all__ = [
    "CHAT_TERMINAL_STATE_KEY",
    "ChatContinuationConflict",
    "ChatTerminalStatePersistenceError",
    "activate_chat_continuation",
    "build_completed_tool_boundary",
    "canonical_chat_request_context",
    "consume_chat_continuation",
    "get_chat_terminal_state",
    "hydrate_chat_terminal_payload",
    "invalidate_chat_terminal_state",
    "lease_chat_continuation",
    "record_chat_terminal_state",
    "release_chat_continuation",
]


logger = logging.getLogger(__name__)

CHAT_TERMINAL_STATE_KEY = "chat_terminal_state"
_PROCESS_BOOT_ID = str(uuid.uuid4())
_LEASE_SECONDS = 120
_CONTEXT_KEYS = (
    "directory",
    "model",
    "agent_id",
    "agent_mode",
    "variant",
    "service_tier",
)


class ChatContinuationConflict(RuntimeError):
    """Raised when a continuation does not match the latest durable marker."""


class ChatTerminalStatePersistenceError(RuntimeError):
    """Raised when safe continuation invalidation cannot be made durable."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lease_owner_id() -> str:
    """Identify this concrete worker, including post-import forked workers."""

    return f"{os.getpid()}:{_PROCESS_BOOT_ID}"


def _utc_now() -> str:
    return _now().isoformat()


def _metadata(session: Any) -> dict[str, Any]:
    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        session.metadata = metadata
    return metadata


def _current_marker(session: Any) -> dict[str, Any] | None:
    marker = _metadata(session).get(CHAT_TERMINAL_STATE_KEY)
    return marker if isinstance(marker, dict) else None


async def _save_marker(manager: Any, session: Any) -> None:
    marker = getattr(manager, "mark_session_modified", None)
    if callable(marker):
        marker(session.id)
    saver = getattr(manager, "save_session", None)
    if not callable(saver):
        raise RuntimeError("session manager cannot persist terminal state")
    saved = await asyncio.to_thread(saver, session)
    if saved is False:
        raise OSError("session manager reported a failed terminal-state save")


def _clean_text(value: Any, *, lowercase: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned.lower() if lowercase else cleaned


def _json_safe(value: Any) -> Any:
    """Return a session-serializable snapshot without retaining live objects."""

    return json.loads(json.dumps(value, default=str))


def canonical_chat_request_context(context: Any) -> dict[str, str | None]:
    """Canonicalize the execution identity that a continuation must preserve."""

    raw = context if isinstance(context, dict) else {}
    raw_directory = _clean_text(raw.get("directory"))
    directory = normalize_directory(raw_directory) if raw_directory else None
    if raw_directory and directory is None:
        try:
            directory = str(Path(raw_directory).expanduser().resolve())
        except (OSError, RuntimeError):
            directory = raw_directory
    return {
        "directory": directory,
        "model": _clean_text(raw.get("model")),
        "agent_id": _clean_text(raw.get("agent_id")),
        "agent_mode": _clean_text(raw.get("agent_mode"), lowercase=True),
        "variant": _clean_text(raw.get("variant"), lowercase=True),
        "service_tier": _clean_text(raw.get("service_tier"), lowercase=True),
    }


def build_completed_tool_boundary(action_results: Any) -> dict[str, Any]:
    """Return a stable fingerprint for tool effects already completed by a turn."""

    completed = []
    if isinstance(action_results, list):
        completed = [
            item
            for item in action_results
            if isinstance(item, dict)
            and str(item.get("status", "completed")).strip().lower() == "completed"
        ]
    encoded = json.dumps(
        completed,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return {
        "completed_action_count": len(completed),
        "fingerprint": hashlib.sha256(encoded).hexdigest(),
    }


def _normalize_tool_boundary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    count = value.get("completed_action_count")
    fingerprint = value.get("fingerprint")
    if (
        not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        or not isinstance(fingerprint, str)
        or not fingerprint.strip()
    ):
        return None
    return {
        "completed_action_count": count,
        "fingerprint": fingerprint.strip(),
    }


def _lease_is_recoverable(marker: dict[str, Any]) -> bool:
    if marker.get("continuation_state") != "leased":
        return False

    # A different worker is not evidence that a lease is stale.  In a
    # multi-worker server, recovering that lease immediately would allow the
    # second worker to execute the same one-shot continuation while the first
    # worker is still running it.  The durable expiry is the only portable
    # liveness boundary available to this file-backed marker.
    raw_expiry = marker.get("lease_expires_at")
    if not isinstance(raw_expiry, str):
        return False
    try:
        expiry = datetime.fromisoformat(raw_expiry)
    except ValueError:
        return False
    if expiry.tzinfo is None:
        return False
    return expiry <= _now()


def _make_available(marker: dict[str, Any]) -> None:
    marker["continuation_state"] = "available"
    for key in (
        "lease_id",
        "lease_owner",
        "lease_action",
        "lease_started_at",
        "lease_expires_at",
    ):
        marker.pop(key, None)


async def _recover_stale_lease(
    manager: Any,
    session: Any,
    marker: dict[str, Any],
) -> None:
    if not _lease_is_recoverable(marker):
        return
    old_marker = deepcopy(marker)
    _make_available(marker)
    marker["lease_recovered_at"] = _utc_now()
    try:
        await _save_marker(manager, session)
    except asyncio.CancelledError:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        raise
    except Exception as exc:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        raise ChatTerminalStatePersistenceError(
            "stale continuation lease could not be recovered durably"
        ) from exc


async def record_chat_terminal_state(
    owner: Any,
    session_id: str | None,
    *,
    request_id: str,
    status: str,
    completed: bool,
    recoverable: bool,
    continuation_actions: list[str],
    terminal_payload: dict[str, Any] | None = None,
    request_context: dict[str, Any] | None = None,
    action_results: list[Any] | None = None,
) -> dict[str, Any] | None:
    """Persist the latest terminal generation and its hydratable response."""

    if not isinstance(session_id, str) or not session_id.strip():
        return None
    session, manager = find_session_store(owner, session_id.strip())
    if session is None or manager is None:
        return None

    metadata = _metadata(session)
    previous = _current_marker(session)
    previous_generation = (
        previous.get("generation", 0) if isinstance(previous, dict) else 0
    )
    if not isinstance(previous_generation, int) or isinstance(
        previous_generation, bool
    ):
        previous_generation = 0

    allowed_actions = [
        action for action in continuation_actions if action in {"retry", "resume"}
    ]
    terminal = (
        _json_safe(terminal_payload)
        if isinstance(terminal_payload, dict)
        else {
            "response": "",
            "partial_response": "",
            "action_results": list(action_results or []),
            "action_count": len(action_results or []),
            "status": str(status or "failed"),
            "terminal_reason": str(status or "failed"),
            "state": "completed" if completed else "failed",
            "completed": bool(completed),
            "recoverable": bool(recoverable),
            "aborted": False,
            "cancelled": False,
            "iterations": None,
            "error": None,
            "continuation": None,
            "actions": [],
        }
    )
    boundary = build_completed_tool_boundary(
        action_results if action_results is not None else terminal.get("action_results")
    )
    terminal_marker: dict[str, Any] = {
        "generation": previous_generation + 1,
        "request_id": str(request_id or ""),
        "status": str(status or "failed"),
        "completed": bool(completed),
        "recoverable": bool(recoverable),
        "continuation_actions": allowed_actions,
        "continuation_state": (
            "available" if recoverable and allowed_actions else "closed"
        ),
        "request_context": canonical_chat_request_context(request_context),
        "tool_boundary": boundary,
        "terminal": terminal,
        "updated_at": _utc_now(),
    }
    old_value = deepcopy(previous) if previous is not None else None
    metadata[CHAT_TERMINAL_STATE_KEY] = terminal_marker
    try:
        await _save_marker(manager, session)
    except asyncio.CancelledError:
        if old_value is None:
            metadata.pop(CHAT_TERMINAL_STATE_KEY, None)
        else:
            metadata[CHAT_TERMINAL_STATE_KEY] = old_value
        raise
    except Exception:
        if old_value is None:
            metadata.pop(CHAT_TERMINAL_STATE_KEY, None)
        else:
            metadata[CHAT_TERMINAL_STATE_KEY] = old_value
        logger.warning(
            "Failed to persist chat terminal state for %s",
            session_id,
            exc_info=True,
        )
        return None
    return deepcopy(terminal_marker)


def _validate_marker_identity(
    marker: dict[str, Any],
    *,
    action: str,
    previous_status: str,
    request_id: str,
    generation: int,
) -> None:
    if marker.get("generation") != generation:
        raise ChatContinuationConflict("terminal continuation generation is stale")
    if marker.get("request_id") != request_id:
        raise ChatContinuationConflict("terminal continuation request id is stale")
    if marker.get("status") != previous_status:
        raise ChatContinuationConflict("terminal continuation status does not match")
    allowed = marker.get("continuation_actions")
    if not isinstance(allowed, list) or action not in allowed:
        raise ChatContinuationConflict("terminal continuation action is not allowed")


async def lease_chat_continuation(
    owner: Any,
    session_id: str,
    *,
    action: str,
    previous_status: str,
    request_id: str,
    generation: int,
    request_context: dict[str, Any] | None,
    tool_boundary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate and durably reserve one continuation before execution starts."""

    session, manager = find_session_store(owner, session_id)
    if session is None or manager is None:
        raise ChatContinuationConflict("session terminal state is unavailable")
    marker = _current_marker(session)
    if marker is None:
        raise ChatContinuationConflict("session has no terminal state to continue")
    await _recover_stale_lease(manager, session, marker)
    marker = _current_marker(session)
    if marker is None:
        raise ChatContinuationConflict("session terminal state is unavailable")
    _validate_marker_identity(
        marker,
        action=action,
        previous_status=previous_status,
        request_id=request_id,
        generation=generation,
    )
    state = marker.get("continuation_state")
    if state == "leased":
        raise ChatContinuationConflict("terminal continuation is already in progress")
    if state != "available":
        raise ChatContinuationConflict("terminal continuation is no longer available")

    expected_context = canonical_chat_request_context(marker.get("request_context"))
    actual_context = canonical_chat_request_context(request_context)
    if actual_context != expected_context:
        raise ChatContinuationConflict("terminal continuation context does not match")
    expected_boundary = _normalize_tool_boundary(marker.get("tool_boundary"))
    actual_boundary = _normalize_tool_boundary(tool_boundary)
    if actual_boundary != expected_boundary:
        raise ChatContinuationConflict(
            "terminal continuation completed-tool boundary does not match"
        )

    old_marker = deepcopy(marker)
    lease_id = str(uuid.uuid4())
    marker.update(
        {
            "continuation_state": "leased",
            "lease_id": lease_id,
            "lease_owner": _lease_owner_id(),
            "lease_action": action,
            "lease_started_at": _utc_now(),
            "lease_expires_at": (
                _now() + timedelta(seconds=_LEASE_SECONDS)
            ).isoformat(),
        }
    )
    try:
        await _save_marker(manager, session)
    except asyncio.CancelledError:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        raise
    except Exception as exc:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        raise ChatContinuationConflict(
            "terminal continuation lease could not be persisted"
        ) from exc
    return deepcopy(marker)


async def activate_chat_continuation(
    owner: Any,
    session_id: str,
    *,
    lease_id: str,
) -> dict[str, Any]:
    """Durably close a leased continuation before resumed work can run.

    Once this transition succeeds, a later failure to save the successor
    terminal snapshot must not make the prior continuation available again.
    This is deliberately conservative: an interrupted process after activation
    requires a fresh user request rather than risking replaying completed tools.
    """

    session, manager = find_session_store(owner, session_id)
    if session is None or manager is None:
        raise ChatContinuationConflict("session terminal state is unavailable")
    marker = _current_marker(session)
    if (
        marker is None
        or marker.get("continuation_state") != "leased"
        or marker.get("lease_id") != lease_id
    ):
        raise ChatContinuationConflict("terminal continuation lease is unavailable")

    old_marker = deepcopy(marker)
    marker["continuation_state"] = "executing"
    marker["lease_execution_started_at"] = _utc_now()
    marker.pop("lease_expires_at", None)
    try:
        await _save_marker(manager, session)
    except asyncio.CancelledError:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        raise
    except Exception as exc:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        raise ChatTerminalStatePersistenceError(
            "terminal continuation execution could not be recorded durably"
        ) from exc
    return deepcopy(marker)


async def release_chat_continuation(
    owner: Any,
    session_id: str,
    *,
    lease_id: str,
) -> bool:
    """Return an unfinished lease to the available state."""

    session, manager = find_session_store(owner, session_id)
    if session is None or manager is None:
        return False
    marker = _current_marker(session)
    if (
        marker is None
        or marker.get("continuation_state") != "leased"
        or marker.get("lease_id") != lease_id
    ):
        return False
    old_marker = deepcopy(marker)
    _make_available(marker)
    marker["lease_released_at"] = _utc_now()
    try:
        await _save_marker(manager, session)
    except asyncio.CancelledError:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        raise
    except Exception as exc:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        raise ChatTerminalStatePersistenceError(
            "terminal continuation lease could not be released durably"
        ) from exc
    return True


async def consume_chat_continuation(
    owner: Any,
    session_id: str,
    *,
    action: str,
    previous_status: str,
    request_id: str,
    generation: int,
) -> dict[str, Any]:
    """Compatibility wrapper returning a recoverable continuation lease."""

    session, _manager = find_session_store(owner, session_id)
    marker = _current_marker(session) if session is not None else None
    return await lease_chat_continuation(
        owner,
        session_id,
        action=action,
        previous_status=previous_status,
        request_id=request_id,
        generation=generation,
        request_context=(marker or {}).get("request_context"),
        tool_boundary=(marker or {}).get("tool_boundary"),
    )


async def invalidate_chat_terminal_state(
    owner: Any,
    session_id: str | None,
    *,
    superseded_by_request_id: str,
) -> bool:
    """Durably invalidate an old continuation before a new turn has side effects."""

    if not isinstance(session_id, str) or not session_id.strip():
        return False
    session, manager = find_session_store(owner, session_id.strip())
    if session is None or manager is None:
        return False
    marker = _current_marker(session)
    if marker is None or marker.get("continuation_state") in {"closed", "invalidated"}:
        return False

    old_marker = deepcopy(marker)
    marker["continuation_state"] = "invalidated"
    marker["superseded_by_request_id"] = str(superseded_by_request_id or "")
    marker["invalidated_at"] = _utc_now()
    for key in (
        "lease_id",
        "lease_owner",
        "lease_action",
        "lease_started_at",
        "lease_expires_at",
        "lease_execution_started_at",
    ):
        marker.pop(key, None)
    try:
        await _save_marker(manager, session)
    except asyncio.CancelledError:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        raise
    except Exception as exc:
        _metadata(session)[CHAT_TERMINAL_STATE_KEY] = old_marker
        logger.warning(
            "Failed to invalidate chat terminal state for %s",
            session_id,
            exc_info=True,
        )
        raise ChatTerminalStatePersistenceError(
            "previous terminal state could not be invalidated durably"
        ) from exc
    return True


async def get_chat_terminal_state(
    owner: Any,
    session_id: str,
) -> dict[str, Any] | None:
    """Load the latest marker, recovering a lease left by an old process."""

    session, manager = find_session_store(owner, session_id)
    if session is None or manager is None:
        return None
    marker = _current_marker(session)
    if marker is None:
        return None
    await _recover_stale_lease(manager, session, marker)
    current = _current_marker(session)
    return deepcopy(current) if current is not None else None


def hydrate_chat_terminal_payload(
    marker: dict[str, Any],
    *,
    session_id: str,
) -> dict[str, Any]:
    """Rebuild the terminal response, including an available continuation body."""

    from penguin.web.services.chat_terminal import attach_chat_continuation

    terminal = marker.get("terminal")
    payload = deepcopy(terminal) if isinstance(terminal, dict) else {}
    return attach_chat_continuation(
        payload,
        session_id=session_id,
        request_id=str(marker.get("request_id") or ""),
        generation=marker.get("generation"),
        request_context=marker.get("request_context"),
        tool_boundary=marker.get("tool_boundary"),
        allow_continuation=marker.get("continuation_state") == "available",
    )
