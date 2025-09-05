#!/usr/bin/env python3
"""Smoke check: UI event emission and tagging.

Subscribes a UI handler; sends messages via bus to agent/human; verifies that
UI events arrive with agent_id tagging and expected event types.

Usage:
  python -m penguin.scripts.verify_ui_events
"""

import asyncio
from pathlib import Path
from typing import List, Tuple, Dict, Any

from penguin.core import PenguinCore


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_ui_events"
    ws.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)

    events: List[Tuple[str, Dict[str, Any]]] = []

    async def ui_handler(event_type: str, data: Dict[str, Any]):
        events.append((event_type, dict(data)))

    core.register_ui(ui_handler)

    # Register an agent and send various messages
    core.register_agent("ee", system_prompt="You are EE.", activate=True)
    await core.send_to_agent("ee", "hi agent")
    await core.send_to_human("status note", message_type="status")
    await core.human_reply("ee", "hello from human")

    await asyncio.sleep(0.1)

    # Summarize
    types = [t for (t, _) in events]
    tagged = [d.get("agent_id") for (_, d) in events]

    print("--- verify_ui_events results ---")
    print(f"Workspace: {ws}")
    print(f"event types: {types}")
    print(f"agent_id tags present: {all(tagged)}")

    ok = ("message" in types) and ("human_message" in types) and all(tagged)
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

