#!/usr/bin/env python3
"""
Stress: high-frequency assistant streaming bursts. Ensures coalescing + finalization.
"""

import asyncio
from typing import Any, Dict, Optional, Awaitable, Callable

from penguin.core import PenguinCore


class _BurstEngine:
    def __init__(self, core: PenguinCore, chunks: int = 1000) -> None:
        self.core = core
        self.settings = type("_Settings", (), {})()
        self.settings.streaming_default = True
        self._chunks = chunks

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
    ) -> Dict[str, Any]:
        if message_callback:
            # Emit many tiny assistant chunks
            for i in range(self._chunks):
                await message_callback("x", "assistant", None)
            await asyncio.sleep(0.02)
        return {
            "status": "completed",
            "assistant_response": "x" * self._chunks,
            "iterations": 1,
            "execution_time": 0.1,
        }


async def _run() -> int:
    core = await PenguinCore.create(fast_startup=True, show_progress=False)
    core.engine = _BurstEngine(core, chunks=1000)  # type: ignore[attr-defined]

    events: list[tuple[str, Dict[str, Any]]] = []

    async def handler(event_type: str, data: Dict[str, Any]) -> None:
        events.append((event_type, data))

    core.register_ui(handler)

    await core.start_run_mode(
        name="burst_stream",
        description="emit 1000 assistant chunks",
        context={"id": "burst"},
        continuous=False,
        time_limit=None,
    )
    await asyncio.sleep(0.2)

    stream_events = [e for e in events if e[0] == "stream_chunk"]
    finals = [d for t, d in stream_events if d.get("is_final")]
    nonfinal = [d for t, d in stream_events if not d.get("is_final")]

    ok = True
    ok &= bool(stream_events)
    ok &= bool(finals)
    # Coalescing heuristic: we should not get 1000 nonfinal emissions
    ok &= len(nonfinal) < 200

    if ok:
        print(f"✅ Burst streaming coalesced ({len(nonfinal)} nonfinal emissions) and finalized")
        return 0
    else:
        print(f"❌ Burst streaming did not coalesce/finalize properly; nonfinal={len(nonfinal)}")
        return 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_run()))
    except KeyboardInterrupt:
        raise

