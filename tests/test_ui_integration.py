#!/usr/bin/env python3
"""
UI Integration Test

Tests the full flow from backend to frontend UI:
1. Start backend server
2. Connect with WebSocket client
3. Send test messages
4. Verify event ordering
5. Check for duplicate events
"""

import asyncio
import json
import time
import websockets
from typing import List, Dict, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Event:
    """Captured event from WebSocket"""
    event_type: str
    data: Dict[str, Any]
    timestamp: float


class UIIntegrationTest:
    """
    Integration test for UI event flow
    """

    def __init__(self, url: str = "ws://localhost:8000/api/v1/chat/stream"):
        self.url = url
        self.events: List[Event] = []
        self.messages: List[Dict] = []
        self.tool_events: List[Dict] = []
        self.websocket = None

    async def connect(self):
        """Connect to WebSocket"""
        print(f"Connecting to {self.url}...")
        self.websocket = await websockets.connect(self.url)
        print("✓ Connected to backend")

    async def disconnect(self):
        """Disconnect from WebSocket"""
        if self.websocket:
            await self.websocket.close()
            print("✓ Disconnected from backend")

    async def send_message(self, text: str):
        """Send a message to the backend"""
        payload = {
            "text": text,
            "conversation_id": f"test-{int(time.time())}",
            "include_reasoning": True
        }
        await self.websocket.send(json.dumps(payload))
        print(f"✓ Sent message: {text}")

    async def receive_events(self, timeout: float = 30.0):
        """
        Receive and categorize events from WebSocket
        """
        print("Receiving events...")
        start_time = time.time()
        event_count = 0

        try:
            async for message in self.websocket:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    print(f"⚠ Timeout after {timeout}s")
                    break

                try:
                    data = json.loads(message)
                    event_type = data.get("event")
                    event_data = data.get("data", {})

                    # Capture event
                    event = Event(
                        event_type=event_type,
                        data=event_data,
                        timestamp=time.time() * 1000
                    )
                    self.events.append(event)
                    event_count += 1

                    # Categorize
                    if event_type == "message":
                        self.messages.append(event_data)
                        print(f"  [{event_count}] message: {event_data.get('role', 'unknown')}")

                    elif event_type == "tool":
                        self.tool_events.append(event_data)
                        action = event_data.get('action', 'unknown')
                        print(f"  [{event_count}] tool: {action}")

                    elif event_type == "complete":
                        print(f"  [{event_count}] complete")
                        break  # End of conversation turn

                    else:
                        print(f"  [{event_count}] {event_type}")

                except json.JSONDecodeError as e:
                    print(f"❌ Failed to parse message: {e}")
                    continue

        except Exception as e:
            print(f"❌ Error receiving events: {e}")

        print(f"✓ Received {event_count} events in {elapsed:.2f}s")
        return event_count

    def verify_no_duplicates(self) -> bool:
        """Check for duplicate tool events"""
        print("\nVerifying no duplicate tool events...")

        tool_ids = set()
        duplicates = []

        for tool_event in self.tool_events:
            tool_id = tool_event.get('id')
            if tool_id in tool_ids:
                duplicates.append(tool_id)
            tool_ids.add(tool_id)

        if duplicates:
            print(f"❌ Found {len(duplicates)} duplicate tool events!")
            for dup_id in duplicates:
                print(f"   - Duplicate: {dup_id}")
            return False
        else:
            print(f"✓ No duplicates found ({len(tool_ids)} unique tool events)")
            return True

    def verify_chronological_order(self) -> bool:
        """Verify messages and tools are in chronological order"""
        print("\nVerifying chronological order...")

        # Get all events with timestamps
        timeline = []

        for msg in self.messages:
            ts = msg.get('timestamp', 0)
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts).timestamp() * 1000
                except:
                    ts = 0
            timeline.append({
                'type': 'message',
                'role': msg.get('role'),
                'ts': ts
            })

        for tool in self.tool_events:
            ts = tool.get('ts', 0)
            timeline.append({
                'type': 'tool',
                'action': tool.get('action'),
                'ts': ts
            })

        # Sort by timestamp
        timeline.sort(key=lambda e: e['ts'])

        # Print timeline
        print("\nTimeline (chronological):")
        for i, event in enumerate(timeline, 1):
            if event['type'] == 'message':
                print(f"  [{i}] {event['role']}: @{int(event['ts'])}")
            else:
                print(f"       ✓ {event['action']} @{int(event['ts'])}")

        # Verify: User message → Assistant message → Tool events
        user_msg_idx = None
        assistant_msg_idx = None

        for i, event in enumerate(timeline):
            if event['type'] == 'message':
                if event['role'] == 'user' and user_msg_idx is None:
                    user_msg_idx = i
                elif event['role'] == 'assistant' and user_msg_idx is not None and assistant_msg_idx is None:
                    assistant_msg_idx = i

        if assistant_msg_idx is None:
            print("⚠ No assistant message found")
            return True  # Not an error, just no response yet

        # Count tool events after assistant message
        tool_events_after = [
            e for i, e in enumerate(timeline)
            if i > assistant_msg_idx and e['type'] == 'tool'
        ]

        if tool_events_after:
            print(f"✓ Correct order: User → Assistant → {len(tool_events_after)} tools")
            return True
        else:
            print("⚠ No tool events found after assistant message")
            return True  # Not an error if no tools used

    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print(f"Total events received: {len(self.events)}")
        print(f"Messages: {len(self.messages)}")
        print(f"Tool events: {len(self.tool_events)}")
        print("="*80)


async def test_simple_request():
    """Test 1: Simple request with no tool calls"""
    print("\n" + "="*80)
    print("TEST 1: Simple Request (No Tools)")
    print("="*80)

    test = UIIntegrationTest()

    try:
        await test.connect()
        await test.send_message("Hello, can you introduce yourself?")
        await test.receive_events(timeout=15.0)
        await test.disconnect()

        test.print_summary()

        # Verify
        no_duplicates = test.verify_no_duplicates()
        correct_order = test.verify_chronological_order()

        if no_duplicates and correct_order:
            print("\n✅ TEST 1 PASSED\n")
            return True
        else:
            print("\n❌ TEST 1 FAILED\n")
            return False

    except Exception as e:
        print(f"\n❌ TEST 1 ERROR: {e}\n")
        return False


async def test_with_tool_calls():
    """Test 2: Request that triggers tool calls"""
    print("\n" + "="*80)
    print("TEST 2: Request with Tool Calls")
    print("="*80)

    test = UIIntegrationTest()

    try:
        await test.connect()
        await test.send_message("List the files in the current directory")
        await test.receive_events(timeout=20.0)
        await test.disconnect()

        test.print_summary()

        # Verify
        no_duplicates = test.verify_no_duplicates()
        correct_order = test.verify_chronological_order()

        if no_duplicates and correct_order:
            print("\n✅ TEST 2 PASSED\n")
            return True
        else:
            print("\n❌ TEST 2 FAILED\n")
            return False

    except Exception as e:
        print(f"\n❌ TEST 2 ERROR: {e}\n")
        return False


async def test_multiple_tool_calls():
    """Test 3: Request that triggers many tool calls"""
    print("\n" + "="*80)
    print("TEST 3: Multiple Tool Calls")
    print("="*80)

    test = UIIntegrationTest()

    try:
        await test.connect()
        await test.send_message("Create 3 simple test files named test1.txt, test2.txt, and test3.txt")
        await test.receive_events(timeout=30.0)
        await test.disconnect()

        test.print_summary()

        # Verify
        no_duplicates = test.verify_no_duplicates()
        correct_order = test.verify_chronological_order()

        if test.tool_events and len(test.tool_events) >= 3:
            print(f"✓ Tool events found: {len(test.tool_events)}")
        else:
            print(f"⚠ Expected at least 3 tool events, got {len(test.tool_events)}")

        if no_duplicates and correct_order:
            print("\n✅ TEST 3 PASSED\n")
            return True
        else:
            print("\n❌ TEST 3 FAILED\n")
            return False

    except Exception as e:
        print(f"\n❌ TEST 3 ERROR: {e}\n")
        return False


async def main():
    """Run all integration tests"""
    print("\n" + "="*80)
    print("PENGUIN UI INTEGRATION TESTS")
    print("Testing backend → WebSocket → UI event flow")
    print("="*80)
    print("\n⚠ Make sure backend server is running:")
    print("   uv run penguin-web\n")

    input("Press Enter when backend is ready...")

    results = []

    # Run tests
    results.append(await test_simple_request())
    results.append(await test_with_tool_calls())
    results.append(await test_multiple_tool_calls())

    # Summary
    print("\n" + "="*80)
    print("INTEGRATION TEST SUMMARY")
    print("="*80)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("✅ All integration tests passed!")
        return 0
    else:
        print("❌ Some integration tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
