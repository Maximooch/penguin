"""Token usage runtime helpers used by :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from penguin.system.state import MessageCategory

logger = logging.getLogger(__name__)

__all__ = [
    "get_session_token_usage",
    "get_token_usage",
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

    session, _manager = core._find_session_store(session_id)
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
        message_agent_ids = {
            message_agent_id.strip()
            for message in getattr(session, "messages", []) or []
            if isinstance(
                message_agent_id := getattr(message, "agent_id", None),
                str,
            )
            and message_agent_id.strip()
        }
        if agent_id in message_agent_ids:
            usage = core._usage_from_session_messages(
                session,
                agent_id=agent_id,
            )
        elif metadata_agent_id == agent_id and not message_agent_ids:
            usage_snapshot = metadata.get("_opencode_usage_v1")
            if isinstance(usage_snapshot, dict):
                usage = dict(usage_snapshot)
            else:
                usage = core._usage_from_session_messages(session)
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
        if isinstance(usage_snapshot, dict):
            usage = dict(usage_snapshot)
        else:
            usage = core._usage_from_session_messages(session)

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

    context_window = getattr(core.conversation_manager, "context_window", None)
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


def _empty_runtime_usage() -> dict[str, Any]:
    return {
        "scope": "runtime",
        "total": {"input": 0, "output": 0},
        "session": {"input": 0, "output": 0},
    }


def _log_background_task_exception(task: asyncio.Task[Any]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception as exc:
        logger.debug("Token update event emission failed: %s", exc)
