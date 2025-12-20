#!/usr/bin/env python3
"""
Stress: register many UI handlers and emit many events; ensure no crashes and runtime bounded.
"""

import asyncio
import time
from typing import Any, Dict

from penguin.core import PenguinCore
from penguin.cli.events import EventBus, EventType


async def _dummy_handler(event_type: str, data: Dict[str, Any]) -> None:
    # Simulate tiny processing
    if event_type == "stream_chunk":
        _ = data.get("chunk")


async def _run() -> int:
    core = await PenguinCore.create(fast_startup=True, show_progress=False)

    # Subscribe 10 handlers to event bus
    event_bus = EventBus.get_sync()
    for _ in range(10):
        for ev_type in EventType:
            event_bus.subscribe(ev_type.value, _dummy_handler)

    # Emit 5k events quickly
    t0 = time.time()
    for i in range(5000):
        await core.emit_ui_event("stream_chunk", {"chunk": "x", "is_final": False, "message_type": "assistant"})
    dt = time.time() - t0

    # Bound: emitting 5k events with 10 handlers should complete within a couple seconds locally
    if dt < 3.0:
        print(f"✅ Emitted 5k events to 10 handlers in {dt:.2f}s")
        return 0
    else:
        print(f"❌ Event fanout too slow: {dt:.2f}s")
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        raise

