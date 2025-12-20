#!/usr/bin/env python3
"""
RunMode persistence-ish behavior: ensure streaming continues across a recoverable error.
Uses print + exit style.
"""

import asyncio
from typing import Any, Dict, Optional, Awaitable, Callable

from penguin.core import PenguinCore
from penguin.cli.events import EventBus, EventType


class _DummyEngine:
    def __init__(self, core: PenguinCore) -> None:
        self.core = core
        self.settings = type("_Settings", (), {})()
        self.settings.streaming_default = True

    async def run_task(
        self,
        *,
        task_prompt: str,
        max_iterations: Optional[int] = None,
        task_context: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        task_name: Optional[str] = None,
        completion_phrases: Optional[list[str]] = None,
        enable_events: bool = True,
        message_callback: Optional[Callable[[str, str, Optional[str]], Awaitable[None]]] = None,
        agent_id: Optional[str] = None,
        agent_role: Optional[str] = None,
    ) -> Dict[str, Any]:
        if message_callback:
            # Emit an error-like chunk followed by normal assistant text
            await message_callback("File not found, retrying with fallback…", "error", None)
            await asyncio.sleep(0.02)
            await message_callback("Recovered.", "assistant", None)
            await asyncio.sleep(0.02)
            await message_callback(" Carrying on.", "assistant", None)
        return {
            "status": "completed",
            "assistant_response": "Recovered. Carrying on.",
            "iterations": 1,
            "execution_time": 0.05,
        }


async def _run() -> int:
    core = await PenguinCore.create(fast_startup=True, show_progress=False)
    core.engine = _DummyEngine(core)  # type: ignore[attr-defined]

    events: list[tuple[str, Dict[str, Any]]] = []

    async def handler(event_type: str, data: Dict[str, Any]) -> None:
        events.append((event_type, data))

    event_bus = EventBus.get_sync()
    for ev_type in EventType:
        event_bus.subscribe(ev_type.value, handler)

    await core.start_run_mode(
        name="persistence_test",
        description="Ensure streaming continues after recoverable error",
        context={"id": "persistence"},
        continuous=False,
        time_limit=None,
    )
    await asyncio.sleep(0.1)

    stream_events = [e for e in events if e[0] == "stream_chunk"]
    non_final = [d for t, d in stream_events if not d.get("is_final")]
    finals = [d for t, d in stream_events if d.get("is_final")]

    ok = True
    ok &= bool(stream_events)
    ok &= bool(finals)
    # Expect at least one assistant stream chunk
    types = [d.get("message_type") for d in non_final]
    ok &= ("assistant" in types)

    # And also expect a non-stream error message event emitted separately
    msg_errors = [d for t, d in events if t == "message" and (d.get("category") == 5 or (hasattr(d.get("category"), 'name') and getattr(d.get("category"), 'name') == 'ERROR'))]
    ok &= bool(msg_errors)

    if ok:
        print("✅ Streaming persisted across recoverable error (assistant chunk + error message event)")
        return 0
    else:
        print("❌ Streaming did not persist as expected")
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
        raise
