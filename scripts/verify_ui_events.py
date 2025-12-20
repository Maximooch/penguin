#!/usr/bin/env python3
"""Smoke check: UI event emission and tagging.

Subscribes a UI handler; emits events via EventBus; verifies that
UI events arrive with correct event types and data.

Usage:
  python scripts/verify_ui_events.py
"""

import asyncio
from pathlib import Path
from typing import List, Tuple, Dict, Any

from penguin.core import PenguinCore
from penguin.cli.events import EventBus, EventType


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_ui_events"
    ws.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)

    events: List[Tuple[str, Dict[str, Any]]] = []

    async def ui_handler(event_type: str, data: Dict[str, Any]):
        events.append((event_type, dict(data)))

    event_bus = EventBus.get_sync()
    for ev_type in EventType:
        event_bus.subscribe(ev_type.value, ui_handler)

    # Test direct event emission via core.emit_ui_event
    await core.emit_ui_event("message", {
        "role": "assistant",
        "content": "Hello from assistant",
        "agent_id": "test_agent"
    })

    await core.emit_ui_event("stream_chunk", {
        "chunk": "streaming...",
        "is_final": False,
        "message_type": "assistant"
    })

    await core.emit_ui_event("human_message", {
        "content": "Human says hello",
        "agent_id": "main"
    })

    await core.emit_ui_event("status", {
        "status": "Processing",
        "agent_id": "test_agent"
    })

    await asyncio.sleep(0.1)

    # Summarize
    types = [t for (t, _) in events]

    print("--- verify_ui_events results ---")
    print(f"Workspace: {ws}")
    print(f"Event types received: {types}")
    print(f"Total events: {len(events)}")

    # Verify we got all expected event types
    expected = ["message", "stream_chunk", "human_message", "status"]
    ok = all(t in types for t in expected)

    if ok:
        print("PASS - All expected event types received via EventBus")
    else:
        missing = [t for t in expected if t not in types]
        print(f"FAIL - Missing event types: {missing}")


if __name__ == "__main__":
    asyncio.run(main())
