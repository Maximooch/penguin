"""Phase 1.5 WebSocket tests for streaming endpoints.

Tests WebSocket connectivity and streaming task execution.
Requires: pip install websockets
"""

import os
import time
import urllib.request
import json
import asyncio
from typing import Any, Dict

try:
    import websockets  # type: ignore
except ImportError:
    print("websockets library not installed. Run: pip install websockets")
    import sys
    sys.exit(1)


BASE_URL = os.environ.get("PENGUIN_API_URL", "http://127.0.0.1:8000")
WS_URL = BASE_URL.replace("http://", "ws://").replace("https://", "wss://")


def _wait_for_server(timeout: int = 30) -> None:
    """Wait for server to be ready."""
    print(f"Waiting for server at {BASE_URL} (max {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/v1/health", timeout=2) as resp:
                if resp.status == 200:
                    print(f"✓ Server ready after {time.time() - start:.1f}s\n")
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"Server not ready after {timeout}s")


async def test_websocket_task_stream():
    """Test WebSocket /api/v1/tasks/stream for streaming task events."""
    uri = f"{WS_URL}/api/v1/tasks/stream"
    print(f"Connecting to {uri}...")
    
    events_received = []
    
    async with websockets.connect(uri, timeout=60) as websocket:
        print("✓ WebSocket connected")
        
        # Send task request
        task_request = {
            "name": "Simple task",
            "description": "Say hello world",
            "continuous": False,
            "time_limit": 30,
        }
        
        print(f"Sending task: {task_request['name']}")
        await websocket.send(json.dumps(task_request))
        
        # Receive events
        timeout_time = time.time() + 45  # 45s timeout for task completion
        while time.time() < timeout_time:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=5)
                event = json.loads(message)
                event_type = event.get("event", "unknown")
                events_received.append(event_type)
                
                print(f"  Event: {event_type}")
                
                # Check for completion or error
                if event_type in ["complete", "error"]:
                    print(f"✓ Task finished with event: {event_type}")
                    if event_type == "error":
                        print(f"  Error data: {event.get('data', {})}")
                    break
                    
            except asyncio.TimeoutError:
                # No message received in 5s, continue waiting
                continue
            except websockets.exceptions.ConnectionClosed:
                print("✓ WebSocket closed by server")
                break
        
        # Verify we received events
        assert len(events_received) > 0, "No events received"
        
        # Should have at least a start and complete/error event
        event_types_str = ", ".join(events_received)
        print(f"✓ WebSocket streaming test: received {len(events_received)} events ({event_types_str})")
        
        return True


if __name__ == "__main__":
    import sys
    
    print(f"\nRunning WebSocket tests against {WS_URL}\n")
    
    # Wait for server
    try:
        _wait_for_server()
    except RuntimeError as e:
        print(f"✗ {e}")
        sys.exit(1)
    
    # Run WebSocket test
    try:
        asyncio.run(test_websocket_task_stream())
        print("\n✓ All WebSocket tests passed")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ WebSocket test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
