#!/usr/bin/env python3
"""
UI Timeline Test Script

Tests the chronological ordering of messages and tool events in the timeline.
Simulates the conditions observed in cli-run-6.txt and cli-run-7.txt.
"""

import asyncio
import time
from typing import List, Dict, Any


class MockMessage:
    def __init__(self, id: str, role: str, content: str, timestamp: float):
        self.id = id
        self.role = role
        self.content = content
        self.timestamp = timestamp

    def __repr__(self):
        return f"[{self.role}] {self.content[:50]}... @{self.timestamp}"


class MockToolEvent:
    def __init__(self, id: str, action: str, ts: float, status: str, result: str):
        self.id = id
        self.phase = "end"
        self.action = action
        self.ts = ts
        self.status = status
        self.result = result

    def __repr__(self):
        return f"[{self.action}] {self.result[:50]}... @{self.ts}"


class TimelineSimulator:
    """
    Simulates the timeline ordering logic from EventTimeline.tsx
    """

    def __init__(self):
        self.messages: List[MockMessage] = []
        self.tool_events: List[MockToolEvent] = []

    def add_message(self, role: str, content: str, timestamp: float = None):
        """Add a message to the timeline"""
        if timestamp is None:
            timestamp = time.time() * 1000

        msg_id = f"msg-{len(self.messages)}"
        self.messages.append(MockMessage(msg_id, role, content, timestamp))
        print(f"✓ Added message [{len(self.messages)}] {role}: {content[:40]}... @{int(timestamp)}")

    def add_tool_event(self, action: str, result: str, ts: float = None):
        """Add a tool event to the timeline"""
        if ts is None:
            ts = time.time() * 1000

        event_id = f"tool-{len(self.tool_events)}"
        self.tool_events.append(MockToolEvent(event_id, action, ts, "completed", result))
        print(f"  ✓ Added tool event: {action} @{int(ts)}")

    def get_sorted_timeline(self) -> List[Dict[str, Any]]:
        """
        Sort messages and tool events chronologically (mimics EventTimeline.tsx)
        """
        events = []

        # Convert messages to timeline events
        for msg in self.messages:
            events.append({
                "kind": "message",
                "id": msg.id,
                "ts": msg.timestamp,
                "role": msg.role,
                "content": msg.content
            })

        # Convert tool events to timeline events
        for tool in self.tool_events:
            events.append({
                "kind": "tool",
                "id": tool.id,
                "ts": tool.ts,
                "action": tool.action,
                "result": tool.result
            })

        # Sort by timestamp
        events.sort(key=lambda e: e["ts"])
        return events

    def print_timeline(self):
        """Print the sorted timeline"""
        print("\n" + "="*80)
        print("TIMELINE (Chronological Order)")
        print("="*80)

        timeline = self.get_sorted_timeline()
        for i, event in enumerate(timeline, 1):
            if event["kind"] == "message":
                role_label = "You" if event["role"] == "user" else "Penguin"
                print(f"[{i}] {role_label}: {event['content'][:60]}...")
            else:
                print(f"     ✓ using {event['action']} — {event['result'][:60]}...")

        print("="*80 + "\n")

    def verify_ordering(self) -> bool:
        """
        Verify that tool events appear AFTER the message that invoked them
        """
        timeline = self.get_sorted_timeline()

        # Find user message
        user_msg_idx = None
        for i, event in enumerate(timeline):
            if event["kind"] == "message" and event["role"] == "user":
                user_msg_idx = i
                break

        if user_msg_idx is None:
            print("❌ No user message found")
            return False

        # Find assistant message
        assistant_msg_idx = None
        for i, event in enumerate(timeline):
            if i > user_msg_idx and event["kind"] == "message" and event["role"] == "assistant":
                assistant_msg_idx = i
                break

        if assistant_msg_idx is None:
            print("❌ No assistant message found after user message")
            return False

        # Check tool events appear after assistant message
        tool_events_after = [
            e for i, e in enumerate(timeline)
            if i > assistant_msg_idx and e["kind"] == "tool"
        ]

        if len(tool_events_after) == 0:
            print("❌ No tool events found after assistant message")
            return False

        print(f"✓ Ordering verified: User → Assistant → {len(tool_events_after)} tool events")
        return True


async def test_responses_api_flow():
    """
    Test Case 1: Responses API Flow
    Simulates the flow where tools execute BEFORE text tokens arrive
    """
    print("\n" + "="*80)
    print("TEST 1: Responses API Flow (Tools Before Tokens)")
    print("="*80)

    sim = TimelineSimulator()

    # T0: User sends message, we capture timestamp
    t0 = time.time() * 1000
    print(f"\n[T0] User sends message @{int(t0)}")
    sim.add_message("user", "Make a list of projects markdown file", t0)

    # Capture stream start timestamp (T0)
    stream_start_ts = t0
    print(f"[T0] Captured stream start timestamp: {int(stream_start_ts)}")

    # T1-T5: Backend calls LLM, tools execute BEFORE text tokens
    await asyncio.sleep(0.1)
    t1 = time.time() * 1000
    print(f"\n[T1] Tool executes @{int(t1)}")
    sim.add_tool_event("execute", "Created PROJECT_IDEAS.md with 39 projects", t1)

    # T6: First text token arrives, message created with stream_start_ts
    await asyncio.sleep(0.1)
    t6 = time.time() * 1000
    print(f"\n[T6] First text token arrives @{int(t6)}")
    print(f"     Creating message with stream_start_ts={int(stream_start_ts)} (not {int(t6)})")
    sim.add_message("assistant", "I'll create a comprehensive project ideas list...", stream_start_ts)

    # Print and verify
    sim.print_timeline()

    if sim.verify_ordering():
        print("✅ TEST 1 PASSED: Tools appear after triggering message\n")
        return True
    else:
        print("❌ TEST 1 FAILED: Incorrect ordering\n")
        return False


async def test_multiple_tool_calls():
    """
    Test Case 2: Multiple Tool Calls
    Simulates a task with many tool executions
    """
    print("\n" + "="*80)
    print("TEST 2: Multiple Tool Calls (27+ iterations)")
    print("="*80)

    sim = TimelineSimulator()

    # T0: User request
    t0 = time.time() * 1000
    sim.add_message("user", "Create a whiteboarding app", t0)
    stream_start_ts = t0

    # T1: Assistant response starts
    sim.add_message("assistant", "I'll create a whiteboarding app for you", stream_start_ts)

    # T2-T10: Many tool calls
    for i in range(8):
        await asyncio.sleep(0.01)
        t = time.time() * 1000
        sim.add_tool_event("execute", f"Created file {i+1}", t)

    # Print and verify
    sim.print_timeline()

    if sim.verify_ordering():
        print("✅ TEST 2 PASSED: All tool events in correct order\n")
        return True
    else:
        print("❌ TEST 2 FAILED: Incorrect ordering\n")
        return False


async def test_old_broken_behavior():
    """
    Test Case 3: OLD BROKEN Behavior (timestamp on first token)
    Shows what happens when we capture timestamp on first token instead of send
    """
    print("\n" + "="*80)
    print("TEST 3: OLD BROKEN Behavior (For Comparison)")
    print("="*80)

    sim = TimelineSimulator()

    # T0: User sends message
    t0 = time.time() * 1000
    sim.add_message("user", "Create a file", t0)

    # T1: Tool executes BEFORE first token
    await asyncio.sleep(0.1)
    t1 = time.time() * 1000
    sim.add_tool_event("write", "Created file.txt", t1)

    # T2: First token arrives, we capture timestamp NOW (WRONG!)
    await asyncio.sleep(0.1)
    t2 = time.time() * 1000
    print(f"\n❌ OLD BEHAVIOR: Capturing timestamp on first token @{int(t2)}")
    print(f"   This is AFTER tool execution @{int(t1)}")
    sim.add_message("assistant", "I'll create a file for you", t2)

    # Print and verify
    sim.print_timeline()
    print("❌ This timeline is WRONG - tool appears before message!\n")
    return False


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("PENGUIN UI TIMELINE TESTS")
    print("Testing chronological ordering of messages and tool events")
    print("="*80)

    results = []

    # Run tests
    results.append(await test_responses_api_flow())
    results.append(await test_multiple_tool_calls())
    await test_old_broken_behavior()  # Always fails (by design)

    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
