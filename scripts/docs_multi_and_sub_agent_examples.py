"""Smoke tests for multi-agent and sub-agent documentation snippets.

Run with:
    uv run python scripts/docs_multi_and_sub_agent_examples.py

This script patches ``PenguinCore.create`` so no real engine startup or
LLM access is required. It verifies that the public API interactions shown
in the docs execute without touching internal modules.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, patch

workspace = Path(os.environ.get("PENGUIN_WORKSPACE", Path.cwd() / "tmp_workspace"))
workspace.mkdir(parents=True, exist_ok=True)
(workspace / "logs").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PENGUIN_WORKSPACE", str(workspace))

from penguin.api_client import ChatOptions, PenguinClient


class DummyConversationManager:
    """Minimal conversation manager used for doc snippet validation."""

    def __init__(self) -> None:
        self.created_agents: set[str] = set()
        self.sub_agents: Dict[str, Dict[str, Any]] = {}

    def create_agent_conversation(self, agent_id: str) -> str:
        self.created_agents.add(agent_id)
        return f"{agent_id}-session"

    def create_sub_agent(
        self,
        agent_id: str,
        *,
        parent_agent_id: str,
        shared_cw_max_tokens: Optional[int] = None,
    ) -> None:
        self.created_agents.add(agent_id)
        self.sub_agents[agent_id] = {
            "parent": parent_agent_id,
            "shared_cw_max_tokens": shared_cw_max_tokens,
        }


class DummyCore:
    """Stub core that mimics the subset used in the examples."""

    def __init__(self) -> None:
        self.conversation_manager = DummyConversationManager()

    async def process_message(
        self,
        *,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        context_files: Optional[list[str]] = None,
        streaming: bool = False,
    ) -> str:
        agent = agent_id or "default"
        ctx = f" ctx={context}" if context else ""
        return f"[{agent}] {message}{ctx}"

    async def cleanup(self) -> None:  # pragma: no cover - trivial stub
        return None


async def multi_agent_example() -> None:
    async with PenguinClient() as client:
        response = await client.chat(
            "Generate a changelog for v0.3.3",
            options=ChatOptions(
                context={"repository": "penguin"},
                agent_id="release",
            ),
        )
        print("[multi-agent]", response)


async def sub_agent_example() -> None:
    async with PenguinClient() as client:
        parent_id = "primary"
        researcher_id = "research"

        cm = client.core.conversation_manager
        cm.create_agent_conversation(parent_id)
        cm.create_sub_agent(
            researcher_id,
            parent_agent_id=parent_id,
            shared_cw_max_tokens=512,
        )

        research_notes = await client.chat(
            "Compile highlights from the latest changelog.",
            options=ChatOptions(agent_id=researcher_id),
        )

        summary = await client.chat(
            f"Summarize and refine: {research_notes}",
            options=ChatOptions(agent_id=parent_id),
        )
        print("[sub-agent]", summary)


async def main() -> None:
    dummy_core = DummyCore()
    async_create = AsyncMock(return_value=dummy_core)

    with patch("penguin.api_client.PenguinCore.create", async_create):
        await multi_agent_example()
        await sub_agent_example()


if __name__ == "__main__":
    asyncio.run(main())
