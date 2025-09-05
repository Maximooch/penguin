#!/usr/bin/env python3
"""Smoke check: MessageBus + Human adapter + directed routing.

Runs without hitting an LLM provider. Verifies that:
- Directed messages to an agent emit bus events and land in the agent's conversation
- send_to_human and human_reply produce bus events

Usage:
  python -m penguin.scripts.verify_message_bus
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Any

from penguin.core import PenguinCore
from penguin.utils.events import EventBus


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_bus"
    ws.mkdir(parents=True, exist_ok=True)

    bus_events: List[Dict[str, Any]] = []

    async def on_bus_message(data: Dict[str, Any]):
        if isinstance(data, dict):
            bus_events.append(dict(data))

    eb = EventBus.get_instance()
    eb.subscribe("bus.message", on_bus_message)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)

    # Register an agent and send messages across the bus
    core.register_agent("alpha", system_prompt="You are alpha.", activate=True)

    # 1) Parent → agent
    await core.send_to_agent("alpha", "Hello from parent via MessageBus", message_type="message")

    # 2) Parent → human
    await core.send_to_human("Parent sent a status update", message_type="status")

    # 3) Human → agent
    await core.human_reply("alpha", "Hi alpha, please summarize context.")

    # Allow handlers to run
    await asyncio.sleep(0.1)

    # Inspect results
    cm = core.conversation_manager
    alpha_conv = cm.get_agent_conversation("alpha")
    user_msgs = [m for m in alpha_conv.session.messages if m.role == "user"]

    print("--- verify_message_bus results ---")
    print(f"Workspace: {ws}")
    print(f"bus.message events captured: {len(bus_events)}")
    print(f"alpha user messages: {len(user_msgs)} (expect >= 2 including parent→agent and human→agent)")

    ok = len(user_msgs) >= 2 and len(bus_events) >= 3
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

