#!/usr/bin/env python3
"""Smoke check: Coordinator destroy removes agent from role routing.

Spawns two agents under a role, destroys one, then sends RR messages and
verifies only the remaining agent receives them.

Usage:
  python -m penguin.scripts.verify_coord_destroy
"""

import asyncio
from pathlib import Path

from penguin.core import PenguinCore


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_coord_destroy"
    ws.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)
    coord = core.get_coordinator()

    await coord.spawn_agent("rr1", role="runner")
    await coord.spawn_agent("rr2", role="runner")

    # Destroy rr2 and send two prompts; both should target rr1
    await coord.destroy_agent("rr2")
    await coord.simple_round_robin_workflow(["P1", "P2"], role="runner")

    await asyncio.sleep(0.1)

    cm = core.conversation_manager
    msgs_rr1 = [m for m in cm.get_agent_conversation("rr1").session.messages if m.role == "user"]
    msgs_rr2 = [m for m in cm.get_agent_conversation("rr2").session.messages if m.role == "user"]

    print("--- verify_coord_destroy results ---")
    print(f"Workspace: {ws}")
    print(f"rr1 user messages: {len(msgs_rr1)}")
    print(f"rr2 user messages: {len(msgs_rr2)}")

    ok = len(msgs_rr1) >= 2 and len(msgs_rr2) == 0
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

