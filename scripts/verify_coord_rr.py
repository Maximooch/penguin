#!/usr/bin/env python3
"""Smoke check: Coordinator round-robin routing.

Spawns two agents under the same role and sends multiple prompts using the
coordinator's round-robin helper. Verifies even-ish distribution by counting
user messages in each agent's conversation.

Usage:
  python -m penguin.scripts.verify_coord_rr
"""

import asyncio
from pathlib import Path

from penguin.core import PenguinCore


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_rr"
    ws.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)
    coord = core.get_coordinator()

    await coord.spawn_agent("impl1", role="implementer")
    await coord.spawn_agent("impl2", role="implementer")

    prompts = ["Do A", "Do B", "Do C", "Do D"]
    await coord.simple_round_robin_workflow(prompts, role="implementer")

    await asyncio.sleep(0.1)

    cm = core.conversation_manager
    c1 = cm.get_agent_conversation("impl1").session.messages
    c2 = cm.get_agent_conversation("impl2").session.messages
    u1 = [m for m in c1 if m.role == "user"]
    u2 = [m for m in c2 if m.role == "user"]

    print("--- verify_coord_rr results ---")
    print(f"Workspace: {ws}")
    print(f"impl1 user messages: {len(u1)}")
    print(f"impl2 user messages: {len(u2)}")
    ok = (len(u1) + len(u2)) >= len(prompts) and abs(len(u1) - len(u2)) <= 1
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

