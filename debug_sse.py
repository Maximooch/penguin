#!/usr/bin/env python3
"""Debug script to trace SSE event flow."""

import asyncio
import sys
sys.path.insert(0, '/Users/maximusputnam/Code/Penguin/penguin')

from unittest.mock import MagicMock, AsyncMock

# Mock the event bus to see what's being emitted
class DebugEventBus:
    def __init__(self):
        self.handlers = {}
        self.events = []

    def subscribe(self, event_type, handler):
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)

    def unsubscribe(self, event_type, handler):
        if event_type in self.handlers and handler in self.handlers[event_type]:
            self.handlers[event_type].remove(handler)

    async def emit(self, event_type, data):
        self.events.append((event_type, data))
        print(f"[EVENT] {event_type}: {str(data)[:100]}...")

        # Call handlers
        for handler in self.handlers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_type, data)
                else:
                    handler(event_type, data)
            except Exception as e:
                print(f"  Handler error: {e}")

# Test the adapter
from penguin.engine.part_events import PartEventAdapter

async def main():
    print("Testing PartEventAdapter with DebugEventBus\n")

    bus = DebugEventBus()
    adapter = PartEventAdapter(bus)

    # Set session ID
    adapter.set_session("test-conv-123")
    print(f"[INFO] Set session ID: test-conv-123\n")

    # Start stream
    print("[ACTION] Starting stream...")
    msg_id, part_id = await adapter.on_stream_start(agent_id="default", model_id="gpt-4")
    print(f"[RESULT] message_id={msg_id}, part_id={part_id}\n")

    # Emit chunks
    print("[ACTION] Emitting chunks...")
    await adapter.on_stream_chunk(msg_id, part_id, "Hello", "assistant")
    await adapter.on_stream_chunk(msg_id, part_id, " world!", "assistant")
    print()

    # End stream
    print("[ACTION] Ending stream...")
    await adapter.on_stream_end(msg_id, part_id)
    print()

    # Summary
    print("=== EVENT SUMMARY ===")
    print(f"Total events emitted: {len(bus.events)}")
    for event_type, data in bus.events:
        print(f"  - {event_type}")

    # Check opencode_event count
    opencode_events = [e for e in bus.events if e[0] == "opencode_event"]
    print(f"\nOpenCode-compatible events: {len(opencode_events)}")
    for _, data in opencode_events:
        print(f"  type={data.get('type')}, props_keys={list(data.get('properties', {}).keys())}")

if __name__ == "__main__":
    asyncio.run(main())
