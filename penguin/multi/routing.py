"""Message routing helpers for Penguin multi-agent coordination."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import logging

__all__ = [
    "human_reply",
    "route_message",
    "send_to_agent",
    "send_to_human",
]


async def route_message(
    core: Any,
    recipient_id: str,
    content: Any,
    *,
    message_type: str = "message",
    metadata: dict[str, Any] | None = None,
    agent_id: str | None = None,
    channel: str | None = None,
    logger: logging.Logger | None = None,
) -> bool:
    """Route a message through the core Engine message bus."""
    if core.engine:
        return await core.engine.route_message(
            recipient_id,
            content,
            message_type=message_type,
            metadata=metadata,
            agent_id=agent_id,
            channel=channel,
        )
    if logger is not None:
        logger.warning("Engine not available for message routing")
    return False


async def send_to_agent(
    core: Any,
    agent_id: str,
    content: Any,
    *,
    message_type: str = "message",
    metadata: dict[str, Any] | None = None,
    channel: str | None = None,
) -> bool:
    """Send a message to an agent through the core Engine."""
    if core.engine:
        return await core.engine.send_to_agent(
            agent_id,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )
    return False


async def send_to_human(
    core: Any,
    content: Any,
    *,
    message_type: str = "status",
    metadata: dict[str, Any] | None = None,
    channel: str | None = None,
) -> bool:
    """Send a message to the human UI through the core Engine."""
    if core.engine:
        return await core.engine.send_to_human(
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )
    return False


async def human_reply(
    core: Any,
    agent_id: str,
    content: Any,
    *,
    message_type: str = "message",
    metadata: dict[str, Any] | None = None,
    channel: str | None = None,
) -> bool:
    """Send a human reply to an agent through the core Engine."""
    if core.engine:
        return await core.engine.human_reply(
            agent_id,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )
    return False
