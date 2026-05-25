"""RunMode event bridge helpers for :mod:`penguin.core`.

The helpers here keep RunMode event interpretation outside ``PenguinCore`` while
preserving the existing private shim used by ``RunMode`` and web callbacks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from penguin.system.state import MessageCategory

if TYPE_CHECKING:
    import logging

__all__ = [
    "handle_run_mode_event",
    "run_mode_status_summary",
]


def run_mode_status_summary(status_type: str, status_data: Any) -> str | None:
    """Return the user-facing RunMode status summary for a status event."""
    if status_type in {"task_started", "task_started_legacy"}:
        task_name = status_data.get(
            "task_name",
            status_data.get("task_prompt", "Unknown task"),
        )
        return f"Task: {task_name} - Running"

    if status_type == "task_progress":
        iteration = status_data.get("iteration", "?")
        max_iter = status_data.get("max_iterations", "?")
        progress = status_data.get("progress", 0)
        return f"Progress: {progress}% (Iter: {iteration}/{max_iter})"

    if status_type in {
        "task_completed",
        "task_completed_legacy",
        "task_completed_eventbus",
    }:
        task_name = status_data.get("task_name", "Last task")
        return f"Task: {task_name} - Completed"

    if status_type in {"run_mode_ended", "shutdown_completed"}:
        return status_data.get("summary", "RunMode ended.")

    if status_type in {"clarification_needed", "clarification_needed_eventbus"}:
        return status_data.get("summary", "Awaiting user clarification.")

    if status_type == "time_limit_reached":
        return status_data.get(
            "summary",
            "RunMode stopped because the explicit time limit was reached.",
        )

    if status_type == "idle_no_ready_tasks":
        return status_data.get(
            "summary",
            "RunMode stopped because no ready work remained.",
        )

    if status_type == "exploratory_continuation":
        return status_data.get(
            "summary",
            "RunMode is continuing exploratorily by determining next steps.",
        )

    return None


def _normalize_message_category(value: Any, *, logger: logging.Logger) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return MessageCategory[value.upper()]
    except KeyError:
        logger.warning(
            "Invalid message category string '%s' from RunMode event. "
            "Defaulting to SYSTEM.",
            value,
        )
        return MessageCategory.SYSTEM


async def _notify_callbacks(
    owner: Any,
    event: dict[str, Any],
    *,
    logger: logging.Logger,
) -> None:
    ui_callback = getattr(owner, "_ui_update_callback", None)
    if ui_callback:
        try:
            await ui_callback()
        except Exception as exc:
            logger.error("Error in UI update callback: %s", exc, exc_info=True)

    websocket_callback = getattr(owner, "_temp_ws_callback", None)
    if websocket_callback:
        try:
            await websocket_callback(event)
        except Exception as exc:
            logger.error("Error in WebSocket callback: %s", exc, exc_info=True)


async def handle_run_mode_event(
    owner: Any,
    event: dict[str, Any],
    *,
    logger: logging.Logger,
) -> None:
    """Process one RunMode event against a core-like owner."""
    try:
        logger.debug("Core received RunMode event: %s", event)
        event_type = event.get("type")

        if event_type == "message":
            message_data = {
                "role": event.get("role", "system"),
                "content": event.get("content", ""),
                "category": _normalize_message_category(
                    event.get("category", MessageCategory.SYSTEM),
                    logger=logger,
                ),
                "metadata": event.get("metadata", {}),
            }
            owner.conversation_manager.conversation.add_message(**message_data)
            owner.conversation_manager.save()
            logger.debug(
                "Core added message to ConversationManager from RunMode event: "
                "%s - %s...",
                message_data["role"],
                message_data["content"][:50],
            )

        elif event_type == "status":
            status_type = event.get("status_type", "unknown")
            status_data = event.get("data", {})
            logger.info(
                "RunMode status update: %s - Data: %s",
                status_type,
                status_data,
            )
            summary = run_mode_status_summary(status_type, status_data)
            if summary is not None:
                owner.current_runmode_status_summary = summary

        elif event_type == "error":
            error_message = event.get("message", "Unknown error from RunMode")
            error_source = event.get("source", "runmode")
            error_details = event.get("details", {})
            logger.error(
                "RunMode Error Event (Source: %s): %s | Details: %s",
                error_source,
                error_message,
                error_details,
            )
            owner.current_runmode_status_summary = f"Error: {error_message}"

        else:
            logger.warning(
                "Core received unknown RunMode event type: %s | Event: %s",
                event_type,
                event,
            )

        await _notify_callbacks(owner, event, logger=logger)

    except Exception as exc:
        logger.error(
            "Error in PenguinCore._handle_run_mode_event: %s",
            str(exc),
            exc_info=True,
        )
