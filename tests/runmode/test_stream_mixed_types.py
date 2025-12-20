#!/usr/bin/env python3
"""
Mixed stream types: reasoning/assistant/tool_output/error interleaving.
Validates assistant stream continues and error/message events appear.
"""

import asyncio
from typing import Any, Dict, Optional, Awaitable, Callable

from penguin.core import PenguinCore
from penguin.cli.events import EventBus, EventType


class _MixedEngine:
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
            await message_callback("Thinking…", "reasoning", None)
            await asyncio.sleep(0.01)
            await message_callback("Hello", "assistant", None)
            await asyncio.sleep(0.01)
            await message_callback("Tool says hi", "tool_output", "demo_tool")
            await asyncio.sleep(0.01)
            await message_callback("Oops", "error", None)
            await asyncio.sleep(0.01)
            await message_callback(" world!", "assistant", None)
        return {
            "status": "completed",
            "assistant_response": "Hello world!",
            "iterations": 1,
            "execution_time": 0.1,
        }


async def _run() -> int:
    core = await PenguinCore.create(fast_startup=True, show_progress=False)
    core.engine = _MixedEngine(core)  # type: ignore[attr-defined]
    events: list[tuple[str, Dict[str, Any]]] = []

    async def handler(event_type: str, data: Dict[str, Any]) -> None:
        events.append((event_type, data))

    event_bus = EventBus.get_sync()
    for ev_type in EventType:
        event_bus.subscribe(ev_type.value, handler)

    await core.start_run_mode(
        name="mixed_types",
        description="interleave mixed stream types",
        context={"id": "mixed"},
        continuous=False,
        time_limit=None,
    )
    await asyncio.sleep(0.1)

    stream_events = [e for e in events if e[0] == "stream_chunk"]
    nonfinal = [d for t, d in stream_events if not d.get("is_final")]
    finals = [d for t, d in stream_events if d.get("is_final")]
    msg_errors = [d for t, d in events if t == "message" and (d.get("category") == 5 or (hasattr(d.get("category"), 'name') and getattr(d.get("category"), 'name') == 'ERROR'))]
    tool_msgs = [d for t, d in events if t == "message" and d.get("metadata", {}).get("tool_name")]

    ok = True
    ok &= bool(stream_events)
    ok &= bool(finals)
    ok &= any(d.get("message_type") == "assistant" for d in nonfinal)
    ok &= bool(msg_errors)
    ok &= bool(tool_msgs)

    if ok:
        print("✅ Mixed stream types handled: assistant streamed, errors/tool outputs emitted as messages")
        return 0
    else:
        print("❌ Mixed stream types handling failed")
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        raise

