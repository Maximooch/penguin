#!/usr/bin/env python3
"""Smoke check: Coordinator role-chain workflow.

Spawns planner/researcher/implementer roles and passes content through the
chain. Verifies each agent received a user message.

Usage:
  python -m penguin.scripts.verify_coord_role_chain
"""

import asyncio
from pathlib import Path

from penguin.core import PenguinCore


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_role_chain"
    ws.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)
    coord = core.get_coordinator()

    await coord.spawn_agent("planner1", role="planner")
    await coord.spawn_agent("research1", role="researcher")
    await coord.spawn_agent("impl1", role="implementer")

    await coord.role_chain_workflow("Draft a plan for X", roles=["planner", "researcher", "implementer"])
    await asyncio.sleep(0.1)

    cm = core.conversation_manager
    got = {}
    for aid in ("planner1", "research1", "impl1"):
        msgs = cm.get_agent_conversation(aid).session.messages
        got[aid] = sum(1 for m in msgs if m.role == "user")

    print("--- verify_coord_role_chain results ---")
    print(f"Workspace: {ws}")
    for k, v in got.items():
        print(f"{k} user messages: {v}")
    ok = all(v >= 1 for v in got.values())
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

