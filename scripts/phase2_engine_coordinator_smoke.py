"""Phase 2 smoke test for Engine <-> Coordinator integration with lite agents."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from penguin.engine import Engine, EngineSettings
from penguin.multi.coordinator import MultiAgentCoordinator
from penguin.system.conversation_manager import ConversationManager
from penguin.llm.api_client import APIClient
from penguin.tools import ToolManager
from penguin.utils.parser import ActionExecutor


async def main() -> None:
    # Minimal conversation manager & engine setup with mocks
    cm = MagicMock(spec=ConversationManager)
    cm.conversation = MagicMock()
    cm.conversation.prepare_conversation = MagicMock()
    cm.conversation.get_formatted_messages = MagicMock(return_value=[])
    cm.get_agent_conversation = MagicMock(return_value=cm.conversation)

    api_client = MagicMock(spec=APIClient)
    api_client.get_response = AsyncMock(return_value={"assistant_response": "Hello", "action_results": []})
    tool_manager = MagicMock(spec=ToolManager)
    action_executor = MagicMock(spec=ActionExecutor)

    engine = Engine(EngineSettings(), cm, api_client, tool_manager, action_executor)
    coordinator = MultiAgentCoordinator(core=MagicMock())
    engine.coordinator = coordinator

    # Register a light agent handler for the "qa" role
    async def qa_handler(prompt: str, meta):
        return f"QA handled: {prompt}"

    coordinator.register_lite_agent(role="qa", handler=qa_handler)

    result = await engine.run_task("Check logs", task_context={}, agent_role="qa")
    print("Lite agent result:", result)


if __name__ == "__main__":
    asyncio.run(main())
