"""
Unified Event System for Penguin CLI

This module provides a centralized event bus for all UI updates, eliminating
duplication between cli.py, ui.py, interface.py, and core.py.

Key Features:
- Single StreamingManager for all streaming state
- Type-safe event definitions
- Async event delivery with proper error handling
- Deduplication of events within time windows
"""

import asyncio
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[[str, Dict[str, Any]], Union[asyncio.Task, None]]
AsyncEventHandler = Callable[[str, Dict[str, Any]], asyncio.Task]


class EventType(Enum):
    """Standard event types for UI updates"""
    # Streaming events
    STREAM_START = "stream_start"
    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"

    # Message events
    MESSAGE = "message"
    MESSAGE_UPDATE = "message_update"

    # Token events
    TOKEN_UPDATE = "token_update"

    # Status events
    STATUS = "status"
    PROGRESS = "progress"

    # Action/Tool events
    ACTION = "action"
    ACTION_RESULT = "action_result"
    TOOL = "tool"  # Tool events for chronological timeline display
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"

    # Error events
    ERROR = "error"
    WARNING = "warning"

    # Human interaction events
    HUMAN_MESSAGE = "human_message"
    HUMAN_PROMPT = "human_prompt"


@dataclass
class StreamingState:
    """Centralized streaming state management"""
    active: bool = False
    stream_id: Optional[str] = None
    content: str = ""
    reasoning_content: str = ""
    message_type: Optional[str] = None
    role: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    last_update: Optional[datetime] = None
    chunks_received: int = 0
    error: Optional[str] = None

    def reset(self):
        """Reset streaming state for new stream"""
        self.active = False
        self.stream_id = None
        self.content = ""
        self.reasoning_content = ""
        self.message_type = None
        self.role = None
        self.metadata = {}
        self.started_at = None
        self.last_update = None
        self.chunks_received = 0
        self.error = None


class EventBus:
    """
    Centralized event bus for all UI updates.

    Replaces duplicate event handling in:
    - PenguinCore.emit_ui_event()
    - PenguinCLI streaming callbacks
    - CLIRenderer.handle_event()
    - PenguinInterface callbacks
    """

    _instance: Optional['EventBus'] = None
    _lock = asyncio.Lock()

    def __init__(self):
        self.subscribers: Dict[str, List[EventHandler]] = {}
        self.event_types: Set[str] = {e.value for e in EventType}

        # Event deduplication
        self._dedup_window = 0.05  # 50ms window
        self._recent_events: List[Tuple[str, str, float]] = []
        self._max_recent = 50

        logger.debug("EventBus initialized")

    @classmethod
    async def get_instance(cls) -> 'EventBus':
        """Get or create singleton instance (async-safe)"""
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def get_sync(cls) -> 'EventBus':
        """Get instance synchronously (for initialization)"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to an event type"""
        if event_type not in self.event_types:
            self.event_types.add(event_type)

        if event_type not in self.subscribers:
            self.subscribers[event_type] = []

        if handler not in self.subscribers[event_type]:
            self.subscribers[event_type].append(handler)
            logger.debug(f"Subscribed handler to {event_type}")

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Unsubscribe from an event type"""
        if event_type in self.subscribers and handler in self.subscribers[event_type]:
            self.subscribers[event_type].remove(handler)
            logger.debug(f"Unsubscribed handler from {event_type}")

    async def emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Emit an event to all subscribers.

        Handles deduplication automatically. Streaming events are passed through
        directly since core.py's StreamingStateManager handles coalescing.
        """
        print(f"[EVENTBUS_EMIT] emit called: {event_type}, bus={id(self)}", flush=True)

        # Validate event type - add unknown types dynamically
        if event_type not in self.event_types:
            self.event_types.add(event_type)
            logger.debug(f"Added dynamic event type: {event_type}")

        # Check for duplicate events (skip dedup for streaming/token events)
        if self._is_duplicate(event_type, data):
            print(f"[EVENTBUS_EMIT] Duplicate detected, skipping: {event_type}", flush=True)
            return

        # Emit directly to all subscribers - core.py handles streaming state
        print(f"[EVENTBUS_EMIT] Calling _emit_to_subscribers for: {event_type}", flush=True)
        await self._emit_to_subscribers(event_type, data)

    async def _emit_to_subscribers(self, event_type: str, data: Dict[str, Any]) -> None:
        """Internal method to emit events to subscribers"""
        if event_type not in self.subscribers:
            print(f"[EVENTBUS] No subscribers for {event_type}", flush=True)
            return

        handlers = self.subscribers[event_type]
        print(f"[EVENTBUS] Emitting {event_type} to {len(handlers)} handlers", flush=True)

        for i, handler in enumerate(handlers):
            try:
                print(f"[EVENTBUS] Calling handler {i}", flush=True)
                # Support both sync and async handlers
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_type, data)
                    print(f"[EVENTBUS] Handler {i} completed", flush=True)
                else:
                    # Run sync handler in thread pool
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, handler, event_type, data)
            except Exception as e:
                logger.error(f"Error in event handler for {event_type}: {e}", exc_info=True)

    def _is_duplicate(self, event_type: str, data: Dict[str, Any]) -> bool:
        """Check if event is duplicate within dedup window"""
        # Don't deduplicate streaming or token events
        if event_type in [EventType.STREAM_CHUNK.value, EventType.TOKEN_UPDATE.value]:
            return False

        # Create hash of event
        content = data.get("content", "")
        event_hash = hashlib.md5(f"{event_type}:{content}".encode()).hexdigest()
        current_time = time.time()

        # Clean old events
        self._recent_events = [
            (t, h, ts) for t, h, ts in self._recent_events
            if current_time - ts < self._dedup_window
        ]

        # Check for duplicate
        for recent_type, recent_hash, _ in self._recent_events:
            if recent_type == event_type and recent_hash == event_hash:
                return True

        # Add to recent events
        self._recent_events.append((event_type, event_hash, current_time))
        if len(self._recent_events) > self._max_recent:
            self._recent_events = self._recent_events[-self._max_recent:]

        return False

    async def emit_message(self, role: str, content: str,
                          category: Optional[str] = None,
                          metadata: Optional[Dict[str, Any]] = None) -> None:
        """Convenience method for emitting message events"""
        await self.emit(EventType.MESSAGE.value, {
            "role": role,
            "content": content,
            "category": category or "DIALOG",
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat()
        })

    async def emit_token_update(self, usage_data: Dict[str, Any]) -> None:
        """Convenience method for token updates"""
        await self.emit(EventType.TOKEN_UPDATE.value, usage_data)

    async def emit_error(self, error: str, details: Optional[str] = None) -> None:
        """Convenience method for error events"""
        await self.emit(EventType.ERROR.value, {
            "message": error,
            "details": details,
            "timestamp": datetime.now().isoformat()
        })

    async def emit_status(self, status: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Convenience method for status updates"""
        await self.emit(EventType.STATUS.value, {
            "status": status,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat()
        })

    def reset(self) -> None:
        """Reset all state (useful for tests)"""
        self._recent_events.clear()


# Singleton instance getter for backward compatibility
def get_event_bus() -> EventBus:
    """Get the singleton EventBus instance"""
    return EventBus.get_sync()