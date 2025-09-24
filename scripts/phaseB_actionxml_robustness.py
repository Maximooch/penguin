"""
Phase B – ActionXML Robustness

Ensures invalid JSON and missing fields produce clear errors and do not mutate state.

Run: python scripts/phaseB_actionxml_robustness.py
"""

from __future__ import annotations

import asyncio
from penguin.api_client import PenguinClient
from penguin.utils.parser import CodeActAction, ActionType


async def main() -> None:
    async with PenguinClient() as client:
        core = client.core
        parent = "default"
        before = dict(core.list_sub_agents(parent))

        # Invalid JSON
        res1 = await core.action_executor.execute_action(
            CodeActAction(ActionType.SPAWN_SUB_AGENT, "{invalid json}")
        )
        print("[spawn invalid json]", res1)

        # Missing required id
        res2 = await core.action_executor.execute_action(
            CodeActAction(ActionType.SPAWN_SUB_AGENT, "{}")
        )
        print("[spawn missing id]", res2)

        # Delegate missing required fields
        res3 = await core.action_executor.execute_action(
            CodeActAction(ActionType.DELEGATE, '{"child":"x"}')
        )
        print("[delegate missing content]", res3)

        after = dict(core.list_sub_agents(parent))
        print("[list_sub_agents before]", before)
        print("[list_sub_agents after]", after)


if __name__ == "__main__":
    asyncio.run(main())

