#!/usr/bin/env python3
"""
Lightweight RunMode streaming test

This test fakes the Engine to drive RunMode's streaming pathway and validates
that PenguinCore emits well-formed stream_chunk events that a UI (TUI/CLI)
would consume. It avoids external API calls and focuses on the integration
between run_mode.py, core.py (event system), and expected message types.
"""

import asyncio
from typing import Any, Dict, Optional, Awaitable, Callable

from penguin.core import PenguinCore


class _DummyEngine:
    """Minimal stand-in for Engine that only drives message_callback."""

    def __init__(self, core: PenguinCore) -> None:
        self.core = core
        # Provide a minimal settings object with streaming_default expected by RunMode
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
    ) -> Dict[str, Any]:
        # Simulate a short reasoning blip, then stream assistant text in two chunks
        if message_callback:
            # Reasoning (should not be treated as assistant content by RunMode)
            await message_callback("Thinking…", "reasoning", None)
            await asyncio.sleep(0.05)
            # Assistant visible content, split into chunks
            await message_callback("Hello", "assistant", None)
            await asyncio.sleep(0.05)
            await message_callback(" world!", "assistant", None)

        # Final result with a completion phrase to mirror real Engine behavior
        return {
            "status": "completed",
            "assistant_response": "Hello world! TASK_COMPLETE",
            "iterations": 1,
            "execution_time": 0.1,
        }


async def _run() -> int:
    # Create core quickly; no network calls are made by this test
    core = await PenguinCore.create(fast_startup=True, show_progress=False)

    # Swap in our dummy engine so RunMode uses it
    core.engine = _DummyEngine(core)  # type: ignore[attr-defined]

    # Capture UI events
    events: list[tuple[str, Dict[str, Any]]] = []

    async def handler(event_type: str, data: Dict[str, Any]) -> None:
        events.append((event_type, data))

    core.register_ui(handler)

    # Kick off a one-shot task via RunMode
    await core.start_run_mode(
        name="user_specified_task",
        description="Say hello",
        context={"id": "user_specified"},
        continuous=False,
        time_limit=None,
    )

    # Allow any queued finalization event (emitted via create_task) to flush
    await asyncio.sleep(0.1)

    # Basic validations: ensure we saw streaming and finalization
    stream_events = [e for e in events if e[0] == "stream_chunk"]
    if not stream_events:
        print("❌ No stream_chunk events emitted")
        return 1

    non_final = [d for t, d in stream_events if not d.get("is_final")]
    finals = [d for t, d in stream_events if d.get("is_final")]

    if not non_final:
        print("❌ No non-final streaming chunks observed")
        return 1
    if not finals:
        print("❌ No final streaming event observed")
        return 1

    # Validate assistant message typing for the non-final chunks
    bad_types = [d for d in non_final if d.get("message_type") not in ("assistant", "reasoning")]
    if bad_types:
        print(f"❌ Unexpected message_type in stream chunks: {set(d.get('message_type') for d in bad_types)}")
        return 1

    # Ensure that some assistant content arrived
    assistant_chunks = [d for d in non_final if d.get("message_type") == "assistant" and d.get("chunk")]
    if not assistant_chunks:
        print("❌ No assistant content chunks observed")
        return 1

    print("✅ RunMode streaming emitted assistant chunks and a finalization event as expected")
    return 0


if __name__ == "__main__":
    try:
        exit(asyncio.run(_run()))
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
        raise


#!/usr/bin/env python3
"""
Lightweight RunMode streaming test

This test fakes the Engine to drive RunMode's streaming pathway and validates
that PenguinCore emits well-formed stream_chunk events that a UI (TUI/CLI)
would consume. It avoids external API calls and focuses on the integration
between run_mode.py, core.py (event system), and expected message types.
"""

import asyncio
from typing import Any, Dict, Optional, Awaitable, Callable

from penguin.core import PenguinCore


class _DummyEngine:
    """Minimal stand-in for Engine that only drives message_callback."""

    def __init__(self, core: PenguinCore) -> None:
        self.core = core
        # Provide a minimal settings object with streaming_default expected by RunMode
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
    ) -> Dict[str, Any]:
        # Simulate a short reasoning blip, then stream assistant text in two chunks
        if message_callback:
            # Reasoning (should not be treated as assistant content by RunMode)
            await message_callback("Thinking…", "reasoning", None)
            await asyncio.sleep(0.05)
            # Assistant visible content, split into chunks
            await message_callback("Hello", "assistant", None)
            await asyncio.sleep(0.05)
            await message_callback(" world!", "assistant", None)

        # Final result with a completion phrase to mirror real Engine behavior
        return {
            "status": "completed",
            "assistant_response": "Hello world! TASK_COMPLETE",
            "iterations": 1,
            "execution_time": 0.1,
        }


async def _run() -> int:
    # Create core quickly; no network calls are made by this test
    core = await PenguinCore.create(fast_startup=True, show_progress=False)

    # Swap in our dummy engine so RunMode uses it
    core.engine = _DummyEngine(core)  # type: ignore[attr-defined]

    # Capture UI events
    events: list[tuple[str, Dict[str, Any]]] = []

    async def handler(event_type: str, data: Dict[str, Any]) -> None:
        events.append((event_type, data))

    core.register_ui(handler)

    # Kick off a one-shot task via RunMode
    await core.start_run_mode(
        name="user_specified_task",
        description="Say hello",
        context={"id": "user_specified"},
        continuous=False,
        time_limit=None,
    )

    # Allow any queued finalization event (emitted via create_task) to flush
    await asyncio.sleep(0.1)

    # Basic validations: ensure we saw streaming and finalization
    stream_events = [e for e in events if e[0] == "stream_chunk"]
    if not stream_events:
        print("❌ No stream_chunk events emitted")
        return 1

    non_final = [d for t, d in stream_events if not d.get("is_final")]
    finals = [d for t, d in stream_events if d.get("is_final")]

    if not non_final:
        print("❌ No non-final streaming chunks observed")
        return 1
    if not finals:
        print("❌ No final streaming event observed")
        return 1

    # Validate assistant message typing for the non-final chunks
    bad_types = [d for d in non_final if d.get("message_type") not in ("assistant", "reasoning")]
    if bad_types:
        print(f"❌ Unexpected message_type in stream chunks: {set(d.get('message_type') for d in bad_types)}")
        return 1

    # Ensure that some assistant content arrived
    assistant_chunks = [d for d in non_final if d.get("message_type") == "assistant" and d.get("chunk")]
    if not assistant_chunks:
        print("❌ No assistant content chunks observed")
        return 1

    print("✅ RunMode streaming emitted assistant chunks and a finalization event as expected")
    return 0


if __name__ == "__main__":
    try:
        exit(asyncio.run(_run()))
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
        raise

