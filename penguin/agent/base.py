from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from penguin.engine import ResourceSnapshot  # Adjust import path if necessary
from penguin.agent.schema import AgentConfig # Adjust import path if necessary
from penguin.system.conversation_manager import ConversationManager # Adjust import path if necessary
from penguin.llm.api_client import APIClient # Adjust import path if necessary
from penguin.tools import ToolManager # Adjust import path if necessary
from penguin.utils.parser import ActionExecutor # Adjust import path if necessary

class BaseAgent(ABC):
    """Abstract base class for all Penguin agents."""

    def __init__(
        self,
        agent_config: AgentConfig,
        conversation_manager: ConversationManager,
        api_client: APIClient,
        tool_manager: ToolManager,
        action_executor: ActionExecutor,
        # Optional: Add logger, event_bus etc. as needed
    ):
        """Initialize the agent with its configuration and core dependencies."""
        self.agent_config = agent_config
        self.conversation_manager = conversation_manager
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.action_executor = action_executor
        self.current_resources = ResourceSnapshot() # Initialize with zero values

    async def update_resource_snapshot(self, snapshot: ResourceSnapshot):
        """Callback or method to receive updated resource usage."""
        self.current_resources = snapshot
        # Optional: Trigger self-throttling logic if implemented
        await self.on_resource_update(snapshot)

    # --- Lifecycle Hooks --- 
    # These can be overridden by subclasses to implement custom agent logic
    # The Cognition module might call these or similar hooks.

    async def on_resource_update(self, resources: ResourceSnapshot):
        """Called when resource usage information is updated."""
        pass # Default is no-op

    async def before_plan(self, resources: ResourceSnapshot):
        """Hook called before the planning phase (if applicable)."""
        pass # Default is no-op

    @abstractmethod
    async def plan(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> Any:
        """Generate a plan or initial response based on the prompt.
        
        This is the main entry point for agent execution logic. The exact 
        return type depends on the agent's strategy (e.g., a plan object, 
        an initial action, or the final response if single-step).
        """
        raise NotImplementedError

    async def before_act(self, action: Any, resources: ResourceSnapshot):
        """Hook called before executing an action."""
        pass # Default is no-op

    @abstractmethod
    async def act(self, plan_or_action: Any, context: Optional[Dict[str, Any]] = None) -> Any:
        """Execute the plan or a specific action.

        Returns the result of the action or the next step.
        """
        raise NotImplementedError
        
    async def before_observe(self, result: Any, resources: ResourceSnapshot):
        """Hook called before processing the observation/result."""
        pass # Default is no-op

    @abstractmethod
    async def observe(self, result: Any, context: Optional[Dict[str, Any]] = None) -> Any:
        """Process the result of an action (observation).

        Updates internal state or prepares for the next cycle.
        Returns data needed for the next planning step or the final response.
        """
        raise NotImplementedError

    # --- Utility methods (optional examples) ---

    def get_name(self) -> str:
        """Return the agent's configured name."""
        return self.agent_config.name

    def get_allowed_tools(self) -> Optional[list[str]]:
        """Return the list of tools this agent is allowed to use."""
        # Uses the validated tools list from the config schema
        return self.agent_config.tools

    # More methods can be added for accessing config, state, etc. 