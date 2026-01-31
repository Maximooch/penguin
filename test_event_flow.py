#!/usr/bin/env python3
"""Test SSE event flow with actual core processing."""

import asyncio
import sys
import json
sys.path.insert(0, '/Users/maximusputnam/Code/Penguin/penguin')

# Mock the event bus to capture events
captured_events = []

class DebugEventBus:
    def __init__(self):
        self.handlers = {}

    def subscribe(self, event_type, handler):
        if event_type not in self.handlers:
            self.handlers[event_type] = []
        self.handlers[event_type].append(handler)

    def unsubscribe(self, event_type, handler):
        pass

    async def emit(self, event_type, data):
        captured_events.append((event_type, data))
        print(f"[EVENT] {event_type}")

        # Call handlers
        for handler in self.handlers.get(event_type, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event_type, data)
                else:
                    handler(event_type, data)
            except Exception as e:
                print(f"  Handler error: {e}")

# Test with mocked core
from unittest.mock import MagicMock, AsyncMock, patch

async def test_event_flow():
    print("=== Testing SSE Event Flow ===\n")

    # Create mock core
    from penguin.engine.part_events import PartEventAdapter

    mock_bus = DebugEventBus()
    adapter = PartEventAdapter(mock_bus)
    adapter.set_session("test-session-123")

    print("1. Starting stream...")
    msg_id, part_id = await adapter.on_stream_start(
        agent_id="default",
        model_id="gpt-4",
        provider_id="openai"
    )
    print(f"   Message ID: {msg_id}")
    print(f"   Part ID: {part_id}\n")

    print("2. Emitting text chunks...")
    chunks = ["Hello", " there", "!", " How", " can", " I", " help", "?"]
    for chunk in chunks:
        await adapter.on_stream_chunk(msg_id, part_id, chunk, "assistant")
        await asyncio.sleep(0.01)  # Small delay to simulate streaming

    print(f"   Emitted {len(chunks)} chunks\n")

    print("3. Ending stream...")
    await adapter.on_stream_end(msg_id, part_id)
    print("   Stream finalized\n")

    print("4. Emitting user message...")
    user_msg_id = await adapter.on_user_message("Hello assistant!")
    print(f"   User message ID: {user_msg_id}\n")

    # Summary
    print("=== EVENT SUMMARY ===")
    opencode_events = [e for e in captured_events if e[0] == "opencode_event"]
    print(f"Total events: {len(captured_events)}")
    print(f"OpenCode events: {len(opencode_events)}")

    print("\nEvent types:")
    for event_type, data in opencode_events:
        print(f"  - {data.get('type')}")
        if 'part' in data.get('properties', {}):
            part = data['properties']['part']
            print(f"    part_type={part.get('type')}, has_delta={'delta' in data['properties']}")

    # Verify SSE format
    print("\n=== SSE FORMAT CHECK ===")
    from penguin.engine.part_events import EventEnvelope

    test_envelope = EventEnvelope(
        type="message.part.updated",
        properties={
            "part": {
                "id": "part_test",
                "messageID": "msg_test",
                "sessionID": "session_test",
                "type": "text",
                "text": "Hello"
            },
            "delta": "Hello"
        }
    )

    sse_output = test_envelope.to_sse()
    print(f"SSE output: {sse_output[:100]}...")

    # Verify it's valid JSON after "data: " prefix
    json_part = sse_output.replace("data: ", "").strip()
    try:
        parsed = json.loads(json_part)
        print(f"✓ Valid JSON: {list(parsed.keys())}")
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON: {e}")

if __name__ == "__main__":
    asyncio.run(test_event_flow())
