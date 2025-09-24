"""
Phase B – Multi-Child Scenario

Spawns 3 sub-agents under the same parent, verifies:
 - list_sub_agents mapping and ordering
 - roster children arrays
 - pause/resume a subset (child2), reflect in roster

Run: python scripts/phaseB_multi_child_scenario.py
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from penguin.api_client import PenguinClient
from penguin.utils.parser import CodeActAction, ActionType


async def main() -> None:
    parent = "default"
    children = ["child_a", "child_b", "child_c"]
    async with PenguinClient() as client:
        core = client.core
        # Spawn children (isolated defaults)
        for cid in children:
            act = CodeActAction(
                ActionType.SPAWN_SUB_AGENT,
                f'{ {"id": cid, "parent": parent} }'.replace("'", '"'),
            )
            await core.action_executor.execute_action(act)

        mapping = core.list_sub_agents(parent)
        print("[list_sub_agents]", mapping)
        roster = core.get_agent_roster()
        parent_entry = next((r for r in roster if r.get("id") == parent), {})
        print("[parent children]", parent_entry.get("children"))

        # Pause child_b
        await core.action_executor.execute_action(
            CodeActAction(ActionType.STOP_SUB_AGENT, '{"id": "child_b"}')
        )
        roster = core.get_agent_roster()
        paused_row = next((r for r in roster if r.get("id") == "child_b"), {})
        print("[child_b paused]", paused_row.get("paused"))
        # Resume child_b
        await core.action_executor.execute_action(
            CodeActAction(ActionType.RESUME_SUB_AGENT, '{"id": "child_b"}')
        )
        roster = core.get_agent_roster()
        resumed_row = next((r for r in roster if r.get("id") == "child_b"), {})
        print("[child_b resumed]", resumed_row.get("paused"))


if __name__ == "__main__":
    asyncio.run(main())

