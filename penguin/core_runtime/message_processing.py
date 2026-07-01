"""Single-message processing helpers for :mod:`penguin.core`."""

from __future__ import annotations

from typing import Any

__all__ = ["process_message"]


async def process_message(
    owner: Any,
    *,
    message: str,
    context: dict[str, Any] | None,
    conversation_id: str | None,
    agent_id: str | None,
    context_files: list[str] | None,
    streaming: bool,
    resolve_conversation_manager: Any,
    log_error: Any,
    log: Any,
) -> str:
    """Process one user message through a resolved conversation manager."""
    try:
        conversation_manager = resolve_conversation_manager(
            owner,
            agent_id,
            log=log,
        )

        if context:
            for key, value in context.items():
                conversation_manager.add_context(f"{key}: {value}")

        return await conversation_manager.process_message(
            message=message,
            conversation_id=conversation_id,
            streaming=streaming,
            context_files=context_files,
        )

    except Exception as exc:
        log_error(
            exc,
            context={
                "component": "core",
                "method": "process_message",
                "message": message,
            },
        )
        return f"Error processing message: {exc!s}"
