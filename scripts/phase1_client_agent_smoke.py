"""Phase 1 smoke test for PenguinClient multi-agent helpers.

This script mirrors the behaviours covered in `tests/test_api_client.py` for the
new agent-management helpers but runs as a standalone Python module so it can be
executed with `uv run` without importing the pytest suite.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

from penguin.api_client import PenguinClient


class StubCore:
    def __init__(self) -> None:
        self.register_agent = MagicMock()
        self.create_sub_agent = MagicMock()
        self.list_agents = MagicMock(return_value=["default", "planner"])
        self.list_sub_agents = MagicMock(return_value={"default": ["planner"]})
        self.unregister_agent = AsyncMock(return_value=True)
        self.send_to_agent = AsyncMock(return_value=True)
        self.send_to_human = AsyncMock(return_value=True)
        self.human_reply = AsyncMock(return_value=True)

    # required for existing client initialisation in other helpers
    conversation_manager = MagicMock()
    conversation_manager.load_context_file = MagicMock()


async def main() -> None:
    core = StubCore()
    client = PenguinClient()
    client._core = core
    client._initialized = True

    print("Registering planner agent…")
    client.create_agent(
        "planner",
        system_prompt="You are a planner",
        share_session_with="default",
        shared_cw_max_tokens=512,
    )
    print("register_agent call:", core.register_agent.call_args)

    print("Creating QA sub-agent…")
    client.create_sub_agent(
        "qa",
        parent_agent_id="planner",
        share_session=False,
        share_context_window=False,
        shared_cw_max_tokens=256,
    )
    print("create_sub_agent call:", core.create_sub_agent.call_args)

    print("Listing agents:", client.list_agents())
    print("Listing sub-agents:", client.list_sub_agents("default"))

    print("Sending bus messages…")
    await client.send_to_agent("planner", {"task": "plan"})
    await client.send_to_human("status")
    await client.human_reply("planner", "ack")

    print("Removing planner…")
    await client.unregister_agent("planner")
    print("unregister_agent call:", core.unregister_agent.call_args)


if __name__ == "__main__":
    asyncio.run(main())
