from __future__ import annotations

"""Lightweight MessageBus for agent/human routing (Phase 3).

Provides a minimal protocol envelope and a singleton bus for publishing
messages between agents and to UI adapters. Built on top of the existing
EventBus for fan-out while allowing direct handler registration by id.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional
import asyncio
import logging

from penguin.utils.events import EventBus

logger = logging.getLogger(__name__)


@dataclass
class ProtocolMessage:
    sender: Optional[str]  # agent_id or "human"
    recipient: Optional[str]  # target agent_id or "human" or None (broadcast)
    content: Any
    message_type: str = "message"  # message|action|status|event
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    message_id: Optional[str] = None


class MessageBus:
    _instance: Optional["MessageBus"] = None

    @classmethod
    def get_instance(cls) -> "MessageBus":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._handlers: Dict[str, Callable[[ProtocolMessage], Awaitable[None]] | Callable[[ProtocolMessage], None]] = {}
        self._lock = asyncio.Lock()
        self._event_bus = EventBus.get_instance()

    def register_handler(
        self,
        target_id: str,
        handler: Callable[[ProtocolMessage], Awaitable[None]] | Callable[[ProtocolMessage], None],
    ) -> None:
        """Register a handler for messages addressed to `target_id` (agent_id or "human")."""
        self._handlers[target_id] = handler

    def unregister_handler(self, target_id: str) -> None:
        if target_id in self._handlers:
            del self._handlers[target_id]

    async def send(self, msg: ProtocolMessage) -> None:
        """Dispatch `msg` to a handler if one is registered, and fan-out via EventBus."""
        # Publish to EventBus so UI/Web can observe
        try:
            await self._event_bus.publish("bus.message", msg.__dict__)
        except Exception:
            # EventBus is best-effort
            pass

        # Deliver to specific recipient when registered
        recipient = msg.recipient or "human"
        handler = self._handlers.get(recipient)
        if handler is None:
            return
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(msg)
            else:
                handler(msg)
        except Exception as e:
            logger.error(f"MessageBus handler error for recipient '{recipient}': {e}")

