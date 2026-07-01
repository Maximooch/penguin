"""Token usage runtime helpers used by :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from penguin.system.state import MessageCategory

logger = logging.getLogger(__name__)

__all__ = [
    "build_usage_snapshot",
    "collect_process_token_usage",
    "emit_token_display_update",
    "get_session_token_usage",
    "get_token_usage",
    "merge_latest_usage_into_token_data",
    "usage_from_session_messages",
]


def _normalize_identifier(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _coerce_non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def get_token_usage(
    core: Any,
    *,
    session_id: str | None = None,
    conversation_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Return runtime or scoped token/context-window telemetry."""

    requested_session_id = _normalize_identifier(session_id) or _normalize_identifier(
        conversation_id
    )
    requested_conversation_id = (
        _normalize_identifier(conversation_id) or requested_session_id
    )

    if requested_session_id:
        requested_agent_id = _normalize_identifier(agent_id)
        usage = core._get_session_token_usage(
            requested_session_id,
            conversation_id=requested_conversation_id,
            agent_id=requested_agent_id,
        )
        if usage is not None:
            return usage
        return {
            "scope": "missing",
            "session_id": requested_session_id,
            "conversation_id": requested_conversation_id,
            **({"agent_id": requested_agent_id} if requested_agent_id else {}),
            "error": "session token usage not found",
        }

    try:
        conversation_manager = getattr(core, "conversation_manager", None)
        if not conversation_manager:
            return _empty_runtime_usage()

        raw_usage = conversation_manager.get_token_usage()
        if not isinstance(raw_usage, dict):
            return _empty_runtime_usage()
        usage = {"scope": "runtime", **raw_usage}

        try:
            token_event_data = usage.copy()
            emit_ui_event = getattr(core, "emit_ui_event", None)
            if emit_ui_event is not None and not hasattr(emit_ui_event, "_mock_name"):
                task = asyncio.create_task(
                    emit_ui_event("token_update", token_event_data)
                )
                task.add_done_callback(_log_background_task_exception)
        except (RuntimeError, AttributeError):
            pass

        return usage
    except Exception as exc:
        logger.error("Error getting token usage: %s", exc)
        return _empty_runtime_usage()


def get_session_token_usage(
    core: Any,
    session_id: str,
    *,
    conversation_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any] | None:
    """Return usage for one persisted session without global fallback."""

    session, manager = core._find_session_store(session_id)
    if session is None:
        return None

    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}

    metadata_agent_id = metadata.get("agent_id")
    if isinstance(metadata_agent_id, str):
        metadata_agent_id = metadata_agent_id.strip() or None
    else:
        metadata_agent_id = None

    if agent_id:
        messages = getattr(session, "messages", []) or []
        message_agent_ids = {
            message_agent_id.strip()
            for message in messages
            if isinstance(
                message_agent_id := getattr(message, "agent_id", None),
                str,
            )
            and message_agent_id.strip()
        }
        if agent_id in message_agent_ids:
            usage = usage_from_session_messages(
                core,
                session,
                agent_id=agent_id,
                manager=manager,
            )
        elif metadata_agent_id == agent_id and not message_agent_ids:
            usage_snapshot = metadata.get("_opencode_usage_v1")
            if isinstance(usage_snapshot, dict):
                usage = dict(usage_snapshot)
            else:
                usage = usage_from_session_messages(core, session, manager=manager)
        else:
            return {
                "scope": "missing",
                "session_id": session_id,
                "conversation_id": conversation_id or session_id,
                "agent_id": agent_id,
                "error": "agent token usage not found for session",
            }
    else:
        usage_snapshot = metadata.get("_opencode_usage_v1")
        messages = getattr(session, "messages", []) or []
        if messages:
            usage = _usage_from_session_messages_with_snapshot(
                core,
                session,
                manager=manager,
                metadata=metadata,
            )
        elif isinstance(usage_snapshot, dict):
            usage = dict(usage_snapshot)
        else:
            usage = usage_from_session_messages(core, session, manager=manager)

    usage["scope"] = "session"
    usage["session_id"] = session_id
    usage["conversation_id"] = conversation_id or session_id
    if agent_id:
        usage["agent_id"] = agent_id
    elif metadata_agent_id:
        usage["agent_id"] = metadata_agent_id

    return usage


def usage_from_session_messages(
    core: Any,
    session: Any,
    *,
    agent_id: str | None = None,
    manager: Any | None = None,
) -> dict[str, Any]:
    """Build a conservative session-scoped usage payload from messages."""

    messages = getattr(session, "messages", []) or []
    if agent_id:
        messages = [
            message
            for message in messages
            if getattr(message, "agent_id", None) == agent_id
        ]
    categories: dict[str, int] = {category.name: 0 for category in MessageCategory}
    current_total_tokens = 0

    for message in messages:
        token_count = _coerce_non_negative_int(getattr(message, "tokens", 0))
        current_total_tokens += token_count

        category = getattr(message, "category", None)
        if hasattr(category, "name"):
            category_name = category.name
        elif isinstance(category, str):
            category_name = category
        else:
            category_name = "UNKNOWN"
        categories[category_name] = categories.get(category_name, 0) + token_count

    context_window = _session_context_window(core, manager)
    max_tokens = int(getattr(context_window, "max_context_window_tokens", 0) or 0)
    available_tokens = max(max_tokens - current_total_tokens, 0) if max_tokens else 0
    percentage = (current_total_tokens / max_tokens) * 100 if max_tokens else 0

    return {
        "current_total_tokens": current_total_tokens,
        "max_context_window_tokens": max_tokens,
        "available_tokens": available_tokens,
        "percentage": percentage,
        "categories": categories,
        "truncations": {
            "total_truncations": 0,
            "messages_removed": 0,
            "tokens_freed": 0,
            "by_category": {},
            "recent_events": [],
        },
    }


def _usage_from_session_messages_with_snapshot(
    core: Any,
    session: Any,
    *,
    agent_id: str | None = None,
    manager: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build message-derived usage while preserving persisted truncation metadata."""

    usage = usage_from_session_messages(
        core,
        session,
        agent_id=agent_id,
        manager=manager,
    )
    snapshot = (metadata or {}).get("_opencode_usage_v1")
    if isinstance(snapshot, dict):
        truncations = snapshot.get("truncations")
        if isinstance(truncations, dict):
            usage["truncations"] = dict(truncations)
    return usage


def _session_context_window(core: Any, manager: Any | None) -> Any | None:
    """Return the most specific context window available for a session."""

    context_window = getattr(manager, "context_window", None)
    if context_window is not None:
        return context_window

    conversation_manager = getattr(core, "conversation_manager", None)
    session_manager = getattr(conversation_manager, "session_manager", None)
    context_window = getattr(session_manager, "context_window", None)
    if context_window is not None:
        return context_window

    return getattr(conversation_manager, "context_window", None)


def emit_token_display_update(
    core: Any,
    *,
    create_task: Any | None = None,
    log: logging.Logger | None = None,
) -> None:
    """Emit token usage updates to UI subscribers and legacy callbacks."""
    token_data = core.get_token_usage()
    task_factory = create_task or asyncio.create_task
    task = task_factory(core.emit_ui_event("token_update", token_data))
    if hasattr(task, "add_done_callback"):
        task.add_done_callback(_log_background_task_exception)

    active_logger = log or logger
    for callback in getattr(core, "token_callbacks", []) or []:
        try:
            callback(token_data)
        except Exception as exc:
            active_logger.error("Error in token callback: %s", exc)


async def collect_process_token_usage(
    core: Any,
    conversation_manager: Any,
    response: Any,
    request_session_id: str | None,
    *,
    log: logging.Logger | None = None,
) -> Any:
    """Collect, snapshot, and publish per-turn usage after ``core.process``."""

    token_data = conversation_manager.get_token_usage()
    active_logger = log or logger
    try:
        latest_usage = _latest_response_or_model_usage(core, response)
        token_data = merge_latest_usage_into_token_data(token_data, latest_usage)
        _persist_usage_snapshot(conversation_manager, token_data, log=active_logger)

        if latest_usage:
            await core._apply_opencode_usage_to_latest_message(
                request_session_id,
                latest_usage,
            )
    except Exception:
        active_logger.debug("Unable to emit OpenCode usage metadata", exc_info=True)
    return token_data


def merge_latest_usage_into_token_data(token_data: Any, latest_usage: Any) -> Any:
    """Fill empty context usage totals from provider-reported latest usage."""

    if not isinstance(token_data, dict) or not isinstance(latest_usage, dict):
        return token_data

    current_total_tokens = _coerce_non_negative_int(
        token_data.get("current_total_tokens", 0)
    )
    if current_total_tokens > 0:
        return token_data

    usage_total_tokens = _latest_usage_total_tokens(latest_usage)
    if usage_total_tokens <= 0:
        return token_data

    updated = dict(token_data)
    updated["current_total_tokens"] = usage_total_tokens
    max_tokens_value = updated.get("max_context_window_tokens")
    if max_tokens_value is None:
        max_tokens_value = updated.get("max_tokens")
    if isinstance(max_tokens_value, (int, float)):
        max_tokens_int = int(max_tokens_value)
        if max_tokens_int > 0:
            updated["max_context_window_tokens"] = max_tokens_int
            updated["max_tokens"] = max_tokens_int
            updated["available_tokens"] = max(max_tokens_int - usage_total_tokens, 0)
            updated["percentage"] = (usage_total_tokens / max_tokens_int) * 100
    return updated


def build_usage_snapshot(token_data: Any) -> dict[str, Any] | None:
    """Build persisted OpenCode usage metadata from a token usage payload."""

    if not isinstance(token_data, dict):
        return None
    return {
        "current_total_tokens": token_data.get("current_total_tokens", 0),
        "max_context_window_tokens": token_data.get(
            "max_context_window_tokens",
            token_data.get("max_tokens"),
        ),
        "available_tokens": token_data.get("available_tokens", 0),
        "percentage": token_data.get("percentage", 0),
        "categories": token_data.get("categories", {}),
        "truncations": token_data.get("truncations", {}),
    }


def _empty_runtime_usage() -> dict[str, Any]:
    return {
        "scope": "runtime",
        "total": {"input": 0, "output": 0},
        "session": {"input": 0, "output": 0},
    }


def _latest_response_or_model_usage(core: Any, response: Any) -> dict[str, Any]:
    latest_usage: dict[str, Any] = {}
    if isinstance(response, dict):
        response_usage = response.get("usage")
        if isinstance(response_usage, dict):
            latest_usage = response_usage
    if latest_usage:
        return latest_usage

    latest_model_usage = core._latest_model_usage()
    return latest_model_usage if isinstance(latest_model_usage, dict) else {}


def _latest_usage_total_tokens(latest_usage: dict[str, Any]) -> int:
    usage_total_tokens = _coerce_non_negative_int(latest_usage.get("total_tokens", 0))
    if usage_total_tokens > 0:
        return usage_total_tokens
    return sum(
        _coerce_non_negative_int(latest_usage.get(key, 0))
        for key in (
            "input_tokens",
            "output_tokens",
            "reasoning_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
        )
    )


def _persist_usage_snapshot(
    conversation_manager: Any,
    token_data: Any,
    *,
    log: logging.Logger,
) -> None:
    try:
        current_session = conversation_manager.get_current_session()
        if current_session and isinstance(
            getattr(current_session, "metadata", None), dict
        ):
            snapshot = build_usage_snapshot(token_data)
            if snapshot is not None:
                current_session.metadata["_opencode_usage_v1"] = snapshot
    except Exception:
        log.debug("Unable to persist usage snapshot", exc_info=True)


def _log_background_task_exception(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.debug("Token update event emission failed: %s", exc)
