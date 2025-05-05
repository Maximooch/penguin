import importlib
import logging
import yaml # type: ignore
from pathlib import Path
from typing import Any, Dict, Optional, List, Type

from penguin.agent.schema import AgentConfig
from penguin.agent.base import BaseAgent

# Assuming core components are passed or accessible
# These imports might need adjustment based on actual project structure
from penguin.core import PenguinCore # Example: If launcher needs access to core state/factory
from penguin.system.conversation_manager import ConversationManager
from penguin.llm.api_client import APIClient
from penguin.tools import ToolManager
from penguin.utils.parser import ActionExecutor

logger = logging.getLogger(__name__)

AGENT_CONFIG_DIR = Path("agents") # Default directory for agent YAML configs

class AgentLauncher:
    """Facade for loading, configuring, and invoking agents."""

    def __init__(
        self, 
        core_instance: Optional[PenguinCore] = None, # Pass core if needed for dependencies
        config_dir: Path = AGENT_CONFIG_DIR
    ):
        """Initialize the launcher, potentially with a core instance for dependencies."""
        self.core = core_instance # Store core if needed to build dependencies
        self.config_dir = config_dir
        self._agent_configs: Dict[str, AgentConfig] = {}
        self._agent_classes: Dict[str, Type[BaseAgent]] = {}
        self.load_agent_configs()

    def load_agent_configs(self):
        """Load agent configurations from YAML files in the config directory."""
        if not self.config_dir.is_dir():
            logger.warning(f"Agent config directory not found: {self.config_dir}")
            return

        for yaml_file in self.config_dir.glob("*.yaml"):
            try:
                with open(yaml_file, 'r') as f:
                    config_data = yaml.safe_load(f)
                    agent_config = AgentConfig(**config_data)
                    if agent_config.name in self._agent_configs:
                        logger.warning(f"Duplicate agent name '{agent_config.name}' found in {yaml_file}. Overwriting.")
                    self._agent_configs[agent_config.name] = agent_config
                    logger.info(f"Loaded agent config: {agent_config.name}")
            except Exception as e:
                logger.error(f"Failed to load agent config from {yaml_file}: {e}")

    def _get_agent_class(self, agent_config: AgentConfig) -> Type[BaseAgent]:
        """Dynamically import and return the agent class."""
        class_path = agent_config.type
        if class_path in self._agent_classes:
            return self._agent_classes[class_path]

        try:
            module_path, class_name = class_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            agent_class = getattr(module, class_name)
            if not issubclass(agent_class, BaseAgent):
                raise TypeError(f"{class_path} is not a subclass of BaseAgent")
            self._agent_classes[class_path] = agent_class
            return agent_class
        except (ImportError, AttributeError, ValueError, TypeError) as e:
            logger.error(f"Failed to load agent class {class_path}: {e}")
            raise ImportError(f"Could not load agent class: {class_path}") from e

    def _instantiate_agent(self, agent_config: AgentConfig) -> BaseAgent:
        """Instantiate the agent, injecting necessary dependencies."""
        agent_class = self._get_agent_class(agent_config)
        
        # --- Dependency Injection --- 
        # This part needs refinement based on how dependencies are managed.
        # Option 1: Assume a Core instance provides factories/singletons
        if self.core:
            # Example: Get dependencies from the core instance
            # These might be specific to the agent or shared
            conv_manager = self.core.conversation_manager # Or a new one for the agent?
            api_client = self.core.api_client
            tool_manager = self.core.tool_manager # Or a filtered one based on agent_config.tools?
            action_executor = self.core.action_executor # Or specific to the agent?
        else:
            # Option 2: Raise error or try to create defaults (less ideal)
            raise ValueError("PenguinCore instance required by Launcher for dependency injection.")
            # Or: Create default instances here (requires more setup)
            # conv_manager = ConversationManager(...)
            # api_client = APIClient(...)
            # ... etc.

        # Filter tool_manager based on agent config (if needed)
        # Example: Create a new ToolManager instance with only allowed tools
        if agent_config.tools is not None:
             allowed_tool_names = set(agent_config.tools)
             # This assumes ToolManager can be filtered or recreated easily
             # filtered_tool_manager = ToolManager(log_error=tool_manager.error_handler)
             # for tool_name, tool_instance in tool_manager.tools.items():
             #    if tool_name in allowed_tool_names:
             #        filtered_tool_manager.register_tool(tool_instance)
             # tool_manager = filtered_tool_manager
             pass # Placeholder for actual tool filtering logic

        # Instantiate the agent
        try:
            agent_instance = agent_class(
                agent_config=agent_config,
                conversation_manager=conv_manager,
                api_client=api_client,
                tool_manager=tool_manager,
                action_executor=action_executor
            )
            return agent_instance
        except Exception as e:
            logger.error(f"Failed to instantiate agent {agent_config.name}: {e}")
            raise RuntimeError(f"Could not instantiate agent: {agent_config.name}") from e

    async def invoke(
        self,
        agent_name: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        # context_files: Optional[List[str]] = None, # Add if needed
        caller: str = "unknown"
    ) -> Any:
        """Invoke an agent by name with the given prompt and context.

        Args:
            agent_name: The name of the agent (must match a loaded config).
            prompt: The primary input/prompt for the agent.
            context: Additional context dictionary.
            caller: Identifier for the source of the invocation (e.g., 'cli', 'emperor', 'http_user').

        Returns:
            The final result from the agent's execution cycle.
        """
        if agent_name not in self._agent_configs:
            logger.error(f"Agent '{agent_name}' not found.")
            # Optionally try reloading configs?
            # self.load_agent_configs()
            # if agent_name not in self._agent_configs:
            raise ValueError(f"Agent configuration '{agent_name}' not found.")
        
        agent_config = self._agent_configs[agent_name]
        
        # --- Execution Environment --- 
        # Placeholder: Decide how to run the agent (in-process, subprocess, docker)
        # Based on agent_config.security.sandbox_type
        sandbox_type = agent_config.security.sandbox_type
        
        if sandbox_type == "docker" or sandbox_type == "shared_docker":
            logger.warning(f"Docker execution for agent '{agent_name}' not yet implemented. Running in-process.")
            # Placeholder for Docker execution logic
            # Requires docker client, image building/pulling, volume mounting etc.
            pass
        elif sandbox_type == "firecracker":
             logger.warning(f"Firecracker execution for agent '{agent_name}' not yet implemented. Running in-process.")
             pass # Placeholder for Firecracker

        # Default: Run in-process using current Python environment
        try:
            agent_instance = self._instantiate_agent(agent_config)
            
            # --- Agent Execution Cycle --- 
            # This is a simplified example. The actual cycle might be more complex
            # involving the Cognition module or a specific execution loop.
            # It needs access to the ResourceMonitor updates.
            
            # TODO: Integrate Resource Monitoring updates
            # TODO: Implement a proper execution loop (plan -> act -> observe)
            
            # Simplified call to plan for now
            result = await agent_instance.plan(prompt, context)
            
            # Placeholder: A more complete loop would call act/observe based on plan result
            # plan_result = await agent_instance.plan(prompt, context)
            # action_result = await agent_instance.act(plan_result, context)
            # final_result = await agent_instance.observe(action_result, context)
            # result = final_result 

            logger.info(f"Agent '{agent_name}' invoked by '{caller}' completed.")
            return result

        except (ValueError, ImportError, RuntimeError, TypeError) as e:
            logger.error(f"Failed to invoke agent '{agent_name}': {e}")
            # Return a structured error or re-raise depending on desired behavior
            return {"error": str(e), "agent_name": agent_name}
        except Exception as e:
            logger.exception(f"Unexpected error invoking agent '{agent_name}': {e}")
            return {"error": f"Unexpected error: {str(e)}", "agent_name": agent_name}

# Example Usage (Conceptual - requires Core setup)
# async def main():
#     # Assume core is initialized elsewhere
#     core = await PenguinCore.create(...)
#     launcher = AgentLauncher(core_instance=core)
#     
#     # Create a dummy agent config YAML file (e.g., agents/echo.yaml)
#     # spec_version: "0.1"
#     # name: "echo_agent"
#     # description: "A simple agent that echoes the prompt."
#     # type: "penguin.agent.basic.EchoAgent" # Assume this class exists

#     try:
#         response = await launcher.invoke(
#             agent_name="echo_agent", 
#             prompt="Hello Penguin Agent!",
#             caller="example_script"
#         )
#         print(f"Agent Response: {response}")
#     except ValueError as e:
#         print(f"Error: {e}")

# if __name__ == "__main__":
#     asyncio.run(main()) 