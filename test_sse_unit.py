#!/usr/bin/env python3
"""Unit test for SSE endpoint."""

import asyncio
import sys
sys.path.insert(0, '/Users/maximusputnam/Code/Penguin/penguin')

from unittest.mock import MagicMock, AsyncMock, patch

# Mock the core and event bus before importing
mock_core = MagicMock()
mock_event_bus = MagicMock()
mock_event_bus.subscribe = MagicMock()
mock_event_bus.unsubscribe = MagicMock()
mock_event_bus.emit = AsyncMock()
mock_core.event_bus = mock_event_bus

# Set up the mock core before importing the module
import penguin.web.sse_events as sse_module
sse_module._core_instance = mock_core

# Now we can test
from fastapi.testclient import TestClient
from fastapi import FastAPI

app = FastAPI()
app.include_router(sse_module.router)

client = TestClient(app)

def test_sse_endpoint():
    print("Testing SSE endpoint...")

    # Mock the event handler to emit one event immediately
    def mock_subscribe(event_type, handler):
        # Simulate an event after a short delay
        async def emit_test_event():
            await asyncio.sleep(0.1)
            handler("opencode_event", {
                "type": "message.updated",
                "properties": {"id": "msg_123", "role": "assistant"}
            })
        asyncio.create_task(emit_test_event())

    mock_event_bus.subscribe = mock_subscribe

    try:
        with client.get("/api/v1/events/sse", timeout=2) as response:
            print(f"Status: {response.status_code}")
            print(f"Content-Type: {response.headers.get('content-type')}")

            # Read events
            content = b""
            for chunk in response.iter_content(chunk_size=1024):
                content += chunk
                if len(content) > 500:
                    break

            text = content.decode('utf-8', errors='replace')
            print(f"Received ({len(text)} chars):\n{text[:500]}")

            # Verify it's SSE format
            assert "data:" in text
            assert "server.connected" in text or "message.updated" in text
            print("✓ SSE format looks correct!")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        raise

if __name__ == "__main__":
    test_sse_endpoint()
    print("\n✓ All tests passed!")
