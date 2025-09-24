"""
Phase A – ActionXML Flow Demo

Parses a single string containing multiple ActionXML tags and executes them
sequentially using parse_action + ActionExecutor. Avoids LLM calls.

Run:
  python scripts/phaseA_actionxml_flow_demo.py
"""

from __future__ import annotations

import asyncio
from typing import List

from penguin.api_client import PenguinClient
from penguin.utils.parser import parse_action


BLOCK = """
<spawn_sub_agent>{
  "id": "researcher",
  "parent": "default",
  "persona": "research",
  "share_session": false,
  "share_context_window": false,
  "shared_cw_max_tokens": 512,
  "initial_prompt": "Summarize docs in /docs"
}</spawn_sub_agent>

<delegate>{
  "parent": "default",
  "child": "researcher",
  "content": "Audit README for gaps",
  "channel": "dev-room",
  "metadata": {"priority": "high"}
}</delegate>

<stop_sub_agent>{"id": "researcher"}</stop_sub_agent>
<resume_sub_agent>{"id": "researcher"}</resume_sub_agent>
"""


async def main() -> None:
    async with PenguinClient() as client:
        core = client.core
        actions = parse_action(BLOCK)
        print(f"[parse_action] found {len(actions)} actions")
        for idx, act in enumerate(actions, 1):
            res = await core.action_executor.execute_action(act)
            print(f"[{idx}/{len(actions)}] {act.action_type.value} -> {res}")

        roster = core.get_agent_roster()
        for entry in roster:
            if entry.get("id") == "researcher":
                print("[roster]", entry)
                break


if __name__ == "__main__":
    asyncio.run(main())

