"""TUI adapter for OpenCode compatibility.

Provides message/part event model and adapters for OpenCode TUI integration.
"""

from penguin.tui_adapter.part_events import (
    PartType,
    Part,
    Message,
    EventEnvelope,
    PartEventAdapter,
)

__all__ = [
    "PartType",
    "Part",
    "Message", 
    "EventEnvelope",
    "PartEventAdapter",
]