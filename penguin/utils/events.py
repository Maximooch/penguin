"""
Event system for Penguin.

Provides a central event bus for publishing and subscribing to events
across the system. Designed to support both task management and 
future expansion to other subsystems.
"""

from typing import Any, Callable, Dict, List, Optional, Set, TypeVar, Union, Awaitable
from collections import defaultdict
from enum import Enum, auto
import asyncio
import logging
import inspect
import weakref

logger = logging.getLogger(__name__)

# Type for event data - could be any type
T = TypeVar('T')
# Type for event handlers - could be synchronous or asynchronous
EventHandler = Union[Callable[[T], None], Callable[[T], Awaitable[None]]]


class EventPriority(Enum):
    """Priority levels for event handling."""
    HIGH = auto()    # Critical system events, handled first
    NORMAL = auto()  # Standard events
    LOW = auto()     # Background/non-urgent events


class EventBus:
    """
    Central event bus for Penguin system events.
    
    Features:
    - Supports both sync and async subscribers
    - Prioritized event handling
    - Type-hinted event data
    - Thread-safe event publishing
    - Weak references to prevent memory leaks
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        """Get or create the singleton instance of EventBus."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        # Event handlers grouped by event type and priority
        self._handlers: Dict[str, Dict[EventPriority, List[weakref.ref]]] = defaultdict(
            lambda: {
                EventPriority.HIGH: [],
                EventPriority.NORMAL: [],
                EventPriority.LOW: []
            }
        )
        self._lock = asyncio.Lock()
    
    def subscribe(
        self, 
        event_type: str, 
        handler: EventHandler[T],
        priority: EventPriority = EventPriority.NORMAL
    ) -> None:
        """
        Subscribe to an event with a handler function.
        
        Args:
            event_type: The name/type of the event
            handler: The function to call when event occurs (sync or async)
            priority: Execution priority for this handler
        """
        # Use weakref to allow subscribers to be garbage collected when no longer used
        handler_ref = weakref.ref(handler)
        
        # Add to the appropriate priority queue
        self._handlers[event_type][priority].append(handler_ref)
        logger.debug(f"Subscribed to {event_type} with {priority.name} priority")
    
    def unsubscribe(self, event_type: str, handler: EventHandler[T]) -> None:
        """
        Unsubscribe a handler from an event.
        
        Args:
            event_type: The name/type of the event
            handler: The handler to remove
        """
        if event_type not in self._handlers:
            return
            
        # Check all priority levels
        for priority in EventPriority:
            # Filter out the handler to remove (or refs whose target is gone)
            self._handlers[event_type][priority] = [
                h_ref for h_ref in self._handlers[event_type][priority]
                if h_ref() is not None and h_ref() is not handler
            ]
        
        logger.debug(f"Unsubscribed from {event_type}")
            
    async def publish(self, event_type: str, data: Optional[T] = None) -> None:
        """
        Publish an event to all subscribers.
        
        Args:
            event_type: The name/type of the event
            data: Optional data to pass to handlers
        """
        if event_type not in self._handlers:
            return
            
        async with self._lock:
            # Process handlers in priority order
            for priority in [EventPriority.HIGH, EventPriority.NORMAL, EventPriority.LOW]:
                # Get handlers for this priority (resolving weak refs)
                handlers = []
                for handler_ref in self._handlers[event_type][priority]:
                    handler = handler_ref()
                    if handler is not None:
                        handlers.append(handler)
                    else:
                        # Clean up dead references
                        self._handlers[event_type][priority].remove(handler_ref)
                
                # Execute all handlers at this priority level
                for handler in handlers:
                    try:
                        if inspect.iscoroutinefunction(handler):
                            await handler(data)
                        else:
                            handler(data)
                    except Exception as e:
                        logger.error(f"Error in event handler for {event_type}: {e}")
    
    def clear_all_handlers(self) -> None:
        """Clear all event handlers - useful for testing."""
        self._handlers.clear()
    
    def get_subscriber_count(self, event_type: str) -> int:
        """Get the number of subscribers for an event type."""
        if event_type not in self._handlers:
            return 0
            
        count = 0
        for priority in EventPriority:
            # Only count live references
            count += sum(1 for h_ref in self._handlers[event_type][priority] if h_ref() is not None)
        
        return count


# Example usage:
# 
# Task-specific events (can be moved to task_events.py later if needed)
class TaskEvent(Enum):
    """Task-related events published by the system."""
    CREATED = "task_created"          # New task created
    STARTED = "task_started"          # Task execution started
    PROGRESSED = "task_progressed"    # Task made progress
    PAUSED = "task_paused"            # Task execution paused
    RESUMED = "task_resumed"          # Task execution resumed
    COMPLETED = "task_completed"      # Task completed successfully
    FAILED = "task_failed"            # Task execution failed
    BLOCKED = "task_blocked"          # Task blocked by dependencies
    UNBLOCKED = "task_unblocked"      # Task no longer blocked
    NEEDS_INPUT = "task_needs_input"  # Task requires user input
    UPDATED = "task_updated"          # Task details updated
    DELETED = "task_deleted"          # Task deleted 