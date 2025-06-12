"""Abstract base class for Penguin Agents.

Copied from legacy `penguin/penguin/agent/base.py`.  Any future changes
should be made here – the authoritative source under `penguin.agent.*`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from penguin.engine import ResourceSnapshot  # Adjust path if Engine moves
from penguin.agent.schema import AgentConfig
from penguin.system.conversation_manager import ConversationManager  # type: ignore
from penguin.llm.api_client import APIClient  # type: ignore
from penguin.tools import ToolManager  # type: ignore
from penguin.utils.parser import ActionExecutor  # type: ignore


class BaseAgent(ABC):
    """Abstract base class for all Penguin agents."""

    def __init__(
        self,
        agent_config: AgentConfig,
        conversation_manager: ConversationManager,
        api_client: APIClient,
        tool_manager: ToolManager,
        action_executor: ActionExecutor,
    ) -> None:
        self.agent_config = agent_config
        self.conversation_manager = conversation_manager
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.action_executor = action_executor
        # Initialise with zero-usage snapshot
        self.current_resources = ResourceSnapshot()

    # ------------------------------------------------------------------
    # Resource monitoring hooks
    # ------------------------------------------------------------------
    async def update_resource_snapshot(self, snapshot: ResourceSnapshot):
        self.current_resources = snapshot
        await self.on_resource_update(snapshot)

    async def on_resource_update(self, resources: ResourceSnapshot):  # noqa: D401
        """Optional hook; agents may implement self-throttling."""

    # ------------------------------------------------------------------
    # Cognitive cycle – plan ▸ act ▸ observe
    # ------------------------------------------------------------------
    async def before_plan(self, resources: ResourceSnapshot):  # noqa: D401
        """Hook invoked before each **plan** call."""

    @abstractmethod
    async def plan(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> Any:
        """Produce a plan or immediate answer given *prompt*."""

    async def before_act(self, action: Any, resources: ResourceSnapshot):  # noqa: D401
        """Hook invoked before **act**."""

    @abstractmethod
    async def act(self, plan_or_action: Any, context: Optional[Dict[str, Any]] = None) -> Any:
        """Execute the plan / action produced by :py:meth:`plan`."""

    async def before_observe(self, result: Any, resources: ResourceSnapshot):  # noqa: D401
        """Hook invoked before **observe**."""

    @abstractmethod
    async def observe(self, result: Any, context: Optional[Dict[str, Any]] = None) -> Any:
        """Process outcome of **act** step."""

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    def get_name(self) -> str:
        return self.agent_config.name

    def get_allowed_tools(self) -> Optional[list[str]]:
        return self.agent_config.tools 