"""Route-facing orchestration for persisted session goals."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from penguin.core_runtime import opencode_transcript
from penguin.core_runtime.session_goal_store import (
    clear_session_goal,
    get_session_goal_lock,
    load_session_goal_record,
    set_session_goal,
)
from penguin.core_runtime.session_goals import (
    GOAL_METADATA_KEY,
    GoalConflictError,
    GoalPersistenceError,
    GoalValidationError,
)
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.web.services.session_events import emit_session_goal_updated_events

if TYPE_CHECKING:
    from penguin.web.schemas.session_goal import (
        SessionGoalRunRequest,
        SessionGoalUpdateRequest,
    )

__all__ = [
    "clear_goal",
    "get_goal",
    "run_goal",
    "update_goal",
]

logger = logging.getLogger(__name__)
_TRANSCRIPT_KEY = "_opencode_transcript_v1"
_CREATE_REQUEST_KEY = "_penguin_goal_create_request_v1"
_GOAL_CONTROL_WORDS = {"status", "pause", "resume", "run", "clear"}
_TITLE_SOURCE_KEY = "_penguin_title_source_v1"
_DISPLAY_EMIT_TIMEOUT_SECONDS = 10.0
_GOAL_EVENT_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class _TranscriptMutation:
    """Exact transcript entry owned by one staged goal command."""

    message_id: str
    transcript_was_present: bool
    entry_was_present: bool
    entry_before: Any
    entry_after: Any
    order_had_message: bool


def _metadata(record: Any) -> dict[str, Any]:
    value = getattr(record.session, "metadata", None)
    return value if isinstance(value, dict) else {}


def _display_command(payload: SessionGoalUpdateRequest) -> str | None:
    command = payload.display_command
    if command is None:
        if payload.client_message_id is not None or payload.client_part_id is not None:
            raise GoalValidationError("client message IDs require display_command")
        return None
    if payload.client_message_id is None:
        raise GoalValidationError("display_command requires client_message_id")
    for field, value in (
        ("client_message_id", payload.client_message_id),
        ("client_part_id", payload.client_part_id),
    ):
        if (
            value is not None
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]*", value) is None
        ):
            raise GoalValidationError(f"{field} contains unsupported characters")
    normalized = command.strip()
    tokens = [
        part[1:-1] if part.startswith('"') and part.endswith('"') else part
        for part in re.findall(r'(?:[^\s"]+|"[^"]*")+', normalized)
    ]
    if len(tokens) < 2 or tokens[0] not in {"/goal", "/247"}:
        raise GoalValidationError("display_command must be a /goal or /247 command")
    args = tokens[1:]
    if args[0] in _GOAL_CONTROL_WORDS:
        raise GoalValidationError("display_command must create a goal")
    display_replace = "--replace" in args
    display_objective = " ".join(arg for arg in args if arg != "--replace").strip()
    expected_objective = payload.objective.strip() if payload.objective else ""
    if display_objective != expected_objective:
        raise GoalValidationError("display_command objective does not match objective")
    if display_replace != bool(payload.replace):
        raise GoalValidationError("display_command replace flag does not match replace")
    return normalized


def _create_request_metadata(
    payload: SessionGoalUpdateRequest,
    command: str | None,
) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
    metadata = deepcopy(payload.metadata) if payload.metadata is not None else {}
    if payload.objective is None or payload.client_message_id is None:
        return (metadata or None), None, None
    canonical = {
        "objective": payload.objective.strip(),
        "replace": bool(payload.replace),
        "token_budget": payload.token_budget,
        "metadata": metadata,
        "display_command": command,
    }
    try:
        encoded = json.dumps(
            canonical,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise GoalValidationError("metadata must be JSON-serializable") from exc
    fingerprint = hashlib.sha256(encoded).hexdigest()
    return (
        metadata or None,
        fingerprint,
        {
            "fingerprint": fingerprint,
            "client_message_id": payload.client_message_id,
            "client_part_id": payload.client_part_id,
        },
    )


def _transcript_message_text(record: Any, message_id: str) -> tuple[str, str] | None:
    transcript = _metadata(record).get(_TRANSCRIPT_KEY)
    messages = transcript.get("messages") if isinstance(transcript, dict) else None
    entry = messages.get(message_id) if isinstance(messages, dict) else None
    if not isinstance(entry, dict):
        return None
    info = entry.get("info")
    role = info.get("role") if isinstance(info, dict) else ""
    parts = entry.get("parts")
    order = entry.get("part_order")
    texts: list[str] = []
    if isinstance(parts, dict) and isinstance(order, list):
        for part_id in order:
            part = parts.get(part_id)
            text = part.get("text") if isinstance(part, dict) else None
            if isinstance(text, str) and text:
                texts.append(text)
    return str(role), "".join(texts)


def _save_record_checked(record: Any, session_id: str, *, reason: str) -> None:
    try:
        record.manager.mark_session_modified(session_id)
        saved = record.manager.save_session(record.session)
    except Exception as exc:
        raise GoalPersistenceError(
            f"Failed to persist {reason} for {session_id}: {exc}"
        ) from exc
    if saved is False:
        raise GoalPersistenceError(f"Failed to persist {reason} for {session_id}")


def _apply_goal_title_if_fallback(core: Any, record: Any, objective: str) -> bool:
    from penguin.web.services.session_view import get_session_info

    info = get_session_info(core, record.session.id)
    if not isinstance(info, dict) or info.get("fallback_title") is not True:
        return False
    metadata = _metadata(record)
    line = objective.split("\n", 1)[0].strip()
    metadata["title"] = (line or objective.strip())[:64]
    metadata[_TITLE_SOURCE_KEY] = "auto"
    return True


def _text_part_ids(entry: Any) -> list[str]:
    if not isinstance(entry, dict):
        return []
    parts = entry.get("parts")
    order = entry.get("part_order")
    if not isinstance(parts, dict) or not isinstance(order, list):
        return []
    return [
        part_id
        for part_id in order
        if isinstance(part_id, str)
        and isinstance(parts.get(part_id), dict)
        and parts[part_id].get("type") == "text"
    ]


def _stage_display_command(
    core: Any,
    record: Any,
    *,
    command: str,
    message_id: str,
    part_id: str | None,
) -> tuple[str, _TranscriptMutation | None]:
    """Stage one complete user message in transcript metadata without I/O."""

    session_id = str(record.session.id)
    existing = _transcript_message_text(record, message_id)
    if existing is not None:
        role, text = existing
        if role != "user" or (text and text != command):
            raise GoalConflictError(
                f"client_message_id {message_id} already belongs to another message"
            )
        if text == command:
            transcript = _metadata(record).get(_TRANSCRIPT_KEY)
            messages = (
                transcript.get("messages") if isinstance(transcript, dict) else None
            )
            entry = messages.get(message_id) if isinstance(messages, dict) else None
            text_part_ids = _text_part_ids(entry)
            if part_id is not None and text_part_ids and part_id not in text_part_ids:
                raise GoalConflictError(
                    f"client_part_id {part_id} does not match the existing message"
                )
            resolved_part_id = part_id or (text_part_ids[0] if text_part_ids else None)
            if resolved_part_id is None:
                raise GoalPersistenceError(
                    f"Goal command message {message_id} has no text part"
                )
            return resolved_part_id, None

    metadata = _metadata(record)
    transcript_was_present = _TRANSCRIPT_KEY in metadata
    transcript = metadata.get(_TRANSCRIPT_KEY)
    if transcript is None:
        transcript = {"messages": {}, "order": []}
        metadata[_TRANSCRIPT_KEY] = transcript
    if not isinstance(transcript, dict):
        raise GoalPersistenceError("Stored OpenCode transcript is corrupt")
    messages = transcript.get("messages")
    order = transcript.get("order")
    if not isinstance(messages, dict) or not isinstance(order, list):
        raise GoalPersistenceError("Stored OpenCode transcript is corrupt")

    entry_was_present = message_id in messages
    entry_before = deepcopy(messages.get(message_id))
    order_had_message = message_id in order
    existing_text_parts = _text_part_ids(entry_before)
    resolved_part_id = part_id or (
        existing_text_parts[0] if existing_text_parts else f"part_goal_{uuid4().hex}"
    )
    existing_part = (
        entry_before.get("parts", {}).get(resolved_part_id)
        if isinstance(entry_before, dict)
        and isinstance(entry_before.get("parts"), dict)
        else None
    )
    if isinstance(existing_part, dict) and (
        existing_part.get("type") != "text"
        or existing_part.get("text") not in {None, "", command}
    ):
        raise GoalConflictError(
            f"client_part_id {resolved_part_id} already belongs to another part"
        )

    model_state: dict[str, Any] = {}
    resolve_model_state = getattr(core, "_resolve_opencode_model_state", None)
    if callable(resolve_model_state):
        try:
            resolved = resolve_model_state(session_id=session_id)
            if isinstance(resolved, dict):
                model_state = resolved
        except Exception:
            logger.debug(
                "Failed to resolve model metadata for goal command %s",
                session_id,
                exc_info=True,
            )
    agent_id = metadata.get("agent_id") or metadata.get("agentID") or "default"
    now_ms = int(time.time() * 1000)
    message_info = {
        "id": message_id,
        "sessionID": session_id,
        "role": "user",
        "time": {"created": now_ms, "completed": now_ms},
        "agent": str(agent_id),
        "model": {
            "providerID": model_state.get("providerID") or "penguin",
            "modelID": model_state.get("modelID") or "penguin-default",
        },
    }
    part = {
        "id": resolved_part_id,
        "messageID": message_id,
        "sessionID": session_id,
        "type": "text",
        "text": command,
    }
    opencode_transcript.apply_transcript_event(
        metadata=metadata,
        event_type="message.updated",
        properties=message_info,
        session_id=session_id,
        assistant_info_factory=lambda _message_id, _session_id: {},
    )
    opencode_transcript.apply_transcript_event(
        metadata=metadata,
        event_type="message.part.updated",
        properties={"part": part},
        session_id=session_id,
        assistant_info_factory=lambda _message_id, _session_id: {},
    )
    entry_after = deepcopy(messages.get(message_id))
    return resolved_part_id, _TranscriptMutation(
        message_id=message_id,
        transcript_was_present=transcript_was_present,
        entry_was_present=entry_was_present,
        entry_before=entry_before,
        entry_after=entry_after,
        order_had_message=order_had_message,
    )


def _rollback_transcript_mutation(
    metadata: dict[str, Any],
    mutation: _TranscriptMutation | None,
) -> bool:
    """Undo only an unchanged transcript entry owned by this operation."""

    if mutation is None:
        return False
    transcript = metadata.get(_TRANSCRIPT_KEY)
    messages = transcript.get("messages") if isinstance(transcript, dict) else None
    order = transcript.get("order") if isinstance(transcript, dict) else None
    if not isinstance(messages, dict) or not isinstance(order, list):
        return False
    if messages.get(mutation.message_id) != mutation.entry_after:
        return False

    if mutation.entry_was_present:
        messages[mutation.message_id] = deepcopy(mutation.entry_before)
    else:
        messages.pop(mutation.message_id, None)
    if not mutation.order_had_message:
        transcript["order"] = [item for item in order if item != mutation.message_id]
    if (
        not mutation.transcript_was_present
        and transcript.get("messages") == {}
        and transcript.get("order") == []
        and set(transcript) <= {"messages", "order"}
    ):
        metadata.pop(_TRANSCRIPT_KEY, None)
    return True


async def _broadcast_display_command(
    core: Any,
    record: Any,
    *,
    command: str,
    message_id: str,
    part_id: str,
) -> None:
    """Broadcast an already-durable goal command without persisting it again."""

    emitter = getattr(core, "_emit_opencode_user_message_with_metadata", None)
    if not callable(emitter):
        logger.warning("Goal command transcript emitter is unavailable")
        return
    session_id = str(record.session.id)
    metadata = _metadata(record)
    directory = metadata.get("directory")
    resolved_directory = None
    if isinstance(directory, str) and directory.strip():
        try:
            candidate = Path(directory).expanduser().resolve(strict=True)
            if candidate.is_dir():
                resolved_directory = str(candidate)
        except OSError:
            resolved_directory = None
    agent_id = metadata.get("agent_id") or metadata.get("agentID") or "default"
    agent_mode = (
        metadata.get("_opencode_agent_mode_v1") or metadata.get("agent_mode") or "build"
    )
    context = ExecutionContext(
        session_id=session_id,
        conversation_id=session_id,
        agent_id=str(agent_id),
        agent_mode=str(agent_mode),
        directory=resolved_directory,
        project_root=resolved_directory,
        workspace_root=resolved_directory,
        request_id=f"{message_id}:goal-command",
    )
    try:
        with execution_context_scope(context):
            emitter_kwargs: dict[str, Any] = {
                "message_id": message_id,
                "agent_id": str(agent_id),
                "part_id": part_id,
                "persist": False,
            }
            await asyncio.wait_for(
                emitter(command, **emitter_kwargs),
                timeout=_DISPLAY_EMIT_TIMEOUT_SECONDS,
            )
    except asyncio.CancelledError:
        logger.warning("Goal command broadcast cancelled for %s", session_id)
    except asyncio.TimeoutError:
        logger.warning("Timed out broadcasting goal command for %s", session_id)
    except Exception:
        logger.warning(
            "Failed to broadcast goal command for %s",
            session_id,
            exc_info=True,
        )


def get_goal(core: Any, session_id: str) -> dict[str, Any] | None:
    """Return a goal for an existing session, or ``None`` when unset."""

    return load_session_goal_record(core, session_id).goal


async def _emit_goal_events_bounded(
    core: Any,
    session_id: str,
    goal: dict[str, Any] | None,
) -> None:
    try:
        await asyncio.wait_for(
            emit_session_goal_updated_events(core, session_id, goal),
            timeout=_GOAL_EVENT_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        logger.warning("Goal event broadcast cancelled for %s", session_id)
    except asyncio.TimeoutError:
        logger.warning("Timed out emitting goal events for %s", session_id)
    except Exception:
        logger.warning(
            "Failed to emit goal events for %s",
            session_id,
            exc_info=True,
        )


def _restore_owned_metadata_value(
    metadata: dict[str, Any],
    key: str,
    *,
    before_present: bool,
    before: Any,
    after_present: bool,
    after: Any,
) -> bool:
    """Restore one metadata value only while it still matches our staged value."""

    if after_present:
        if key not in metadata or metadata.get(key) != after:
            return False
    elif key in metadata:
        return False

    if before_present:
        metadata[key] = deepcopy(before)
    else:
        metadata.pop(key, None)
    return before_present != after_present or before != after


async def update_goal(
    core: Any,
    session_id: str,
    payload: SessionGoalUpdateRequest,
) -> dict[str, Any]:
    """Create, replace, pause, or resume a goal and emit lifecycle events."""

    if payload.objective is not None and payload.status is not None:
        raise GoalValidationError("objective and status cannot be updated together")
    if payload.objective is None and payload.status is None:
        raise GoalValidationError("objective or status is required")
    if payload.status is not None and (
        payload.replace
        or payload.token_budget is not None
        or payload.metadata is not None
        or payload.display_command is not None
        or payload.client_message_id is not None
        or payload.client_part_id is not None
    ):
        raise GoalValidationError("status controls cannot include create fields")
    command = _display_command(payload)
    create_metadata, create_fingerprint, create_request = _create_request_metadata(
        payload,
        command,
    )

    lock = get_session_goal_lock(core, session_id)
    async with lock:
        record = load_session_goal_record(core, session_id)
        before = record.goal
        session_metadata = _metadata(record)
        goal_present = GOAL_METADATA_KEY in session_metadata
        goal_before = deepcopy(session_metadata.get(GOAL_METADATA_KEY))
        title_present = "title" in session_metadata
        title_before = deepcopy(session_metadata.get("title"))
        title_source_present = _TITLE_SOURCE_KEY in session_metadata
        title_source_before = deepcopy(session_metadata.get(_TITLE_SOURCE_KEY))
        create_request_present = _CREATE_REQUEST_KEY in session_metadata
        create_request_before = deepcopy(session_metadata.get(_CREATE_REQUEST_KEY))
        stored_create_request = session_metadata.get(_CREATE_REQUEST_KEY)
        stored_fingerprint = (
            stored_create_request.get("fingerprint")
            if isinstance(stored_create_request, dict)
            else None
        )
        stored_client_message_id = (
            stored_create_request.get("client_message_id")
            if isinstance(stored_create_request, dict)
            else None
        )
        stored_client_part_id = (
            stored_create_request.get("client_part_id")
            if isinstance(stored_create_request, dict)
            else None
        )
        stored_goal_id = (
            stored_create_request.get("goal_id")
            if isinstance(stored_create_request, dict)
            else None
        )
        idempotent_unrun_create = bool(
            payload.objective is not None
            and payload.client_message_id is not None
            and create_fingerprint is not None
            and before is not None
            and before["status"] == "active"
            and before.get("active_run_id") is None
            and before.get("last_run_id") is None
            and before.get("tokens_used") == 0
            and stored_fingerprint == create_fingerprint
            and stored_client_message_id == payload.client_message_id
            and stored_client_part_id == payload.client_part_id
            and stored_goal_id == before["id"]
        )
        goal = (
            before
            if idempotent_unrun_create
            else set_session_goal(
                core,
                session_id,
                objective=payload.objective,
                status=payload.status,
                replace=bool(payload.replace),
                token_budget=payload.token_budget,
                metadata=create_metadata,
                persist=payload.objective is None,
            )
        )
        assert goal is not None
        if payload.objective is None:
            await _emit_goal_events_bounded(core, session_id, goal)
            return goal

        if not idempotent_unrun_create and payload.objective is not None:
            if create_request is not None:
                session_metadata[_CREATE_REQUEST_KEY] = {
                    **create_request,
                    "goal_id": goal["id"],
                }
            else:
                session_metadata.pop(_CREATE_REQUEST_KEY, None)

        goal_after_present = GOAL_METADATA_KEY in session_metadata
        goal_after = deepcopy(session_metadata.get(GOAL_METADATA_KEY))
        create_request_after_present = _CREATE_REQUEST_KEY in session_metadata
        create_request_after = deepcopy(session_metadata.get(_CREATE_REQUEST_KEY))
        title_after_present = title_present
        title_after = title_before
        title_source_after_present = title_source_present
        title_source_after = title_source_before
        transcript_mutation: _TranscriptMutation | None = None
        resolved_part_id: str | None = None
        title_changed = False
        try:
            title_changed = _apply_goal_title_if_fallback(
                core,
                record,
                payload.objective,
            )
            title_after_present = "title" in session_metadata
            title_after = deepcopy(session_metadata.get("title"))
            title_source_after_present = _TITLE_SOURCE_KEY in session_metadata
            title_source_after = deepcopy(session_metadata.get(_TITLE_SOURCE_KEY))
            if command is not None and payload.client_message_id is not None:
                resolved_part_id, transcript_mutation = _stage_display_command(
                    core,
                    record,
                    command=command,
                    message_id=payload.client_message_id,
                    part_id=payload.client_part_id,
                )
            _save_record_checked(record, session_id, reason="session goal creation")
        except BaseException as exc:
            changed = _rollback_transcript_mutation(
                session_metadata,
                transcript_mutation,
            )
            changed = (
                _restore_owned_metadata_value(
                    session_metadata,
                    GOAL_METADATA_KEY,
                    before_present=goal_present,
                    before=goal_before,
                    after_present=goal_after_present,
                    after=goal_after,
                )
                or changed
            )
            if title_changed:
                changed = (
                    _restore_owned_metadata_value(
                        session_metadata,
                        "title",
                        before_present=title_present,
                        before=title_before,
                        after_present=title_after_present,
                        after=title_after,
                    )
                    or changed
                )
                changed = (
                    _restore_owned_metadata_value(
                        session_metadata,
                        _TITLE_SOURCE_KEY,
                        before_present=title_source_present,
                        before=title_source_before,
                        after_present=title_source_after_present,
                        after=title_source_after,
                    )
                    or changed
                )
            changed = (
                _restore_owned_metadata_value(
                    session_metadata,
                    _CREATE_REQUEST_KEY,
                    before_present=create_request_present,
                    before=create_request_before,
                    after_present=create_request_after_present,
                    after=create_request_after,
                )
                or changed
            )
            if changed:
                try:
                    _save_record_checked(
                        record,
                        session_id,
                        reason="session goal creation rollback",
                    )
                except GoalPersistenceError as rollback_exc:
                    raise rollback_exc from exc
            raise

        if (
            command is not None
            and payload.client_message_id is not None
            and resolved_part_id is not None
        ):
            await _broadcast_display_command(
                core,
                record,
                command=command,
                message_id=payload.client_message_id,
                part_id=resolved_part_id,
            )
        await _emit_goal_events_bounded(core, session_id, goal)
    return goal


async def clear_goal(core: Any, session_id: str) -> None:
    """Clear a non-running goal and emit lifecycle events."""

    lock = get_session_goal_lock(core, session_id)
    async with lock:
        record = load_session_goal_record(
            core,
            session_id,
            allow_corrupt_goal=True,
        )
        metadata = _metadata(record)
        goal_present = GOAL_METADATA_KEY in metadata
        goal_before = deepcopy(metadata.get(GOAL_METADATA_KEY))
        create_request_present = _CREATE_REQUEST_KEY in metadata
        create_request_before = deepcopy(metadata.get(_CREATE_REQUEST_KEY))

        clear_session_goal(core, session_id, persist=False)
        metadata.pop(_CREATE_REQUEST_KEY, None)
        try:
            _save_record_checked(record, session_id, reason="goal clear")
        except BaseException as exc:
            changed = _restore_owned_metadata_value(
                metadata,
                GOAL_METADATA_KEY,
                before_present=goal_present,
                before=goal_before,
                after_present=False,
                after=None,
            )
            changed = (
                _restore_owned_metadata_value(
                    metadata,
                    _CREATE_REQUEST_KEY,
                    before_present=create_request_present,
                    before=create_request_before,
                    after_present=False,
                    after=None,
                )
                or changed
            )
            if changed:
                try:
                    _save_record_checked(
                        record,
                        session_id,
                        reason="goal clear rollback",
                    )
                except GoalPersistenceError as rollback_exc:
                    raise rollback_exc from exc
            raise
        await _emit_goal_events_bounded(core, session_id, None)


async def run_goal(
    core: Any,
    session_id: str,
    payload: SessionGoalRunRequest,
) -> dict[str, Any]:
    """Delegate goal execution to the core runtime facade."""

    return await core.run_session_goal(
        session_id,
        max_iterations=payload.max_iterations,
        timeout_seconds=payload.timeout_seconds,
        directory=payload.directory.strip()
        if isinstance(payload.directory, str)
        else None,
    )
