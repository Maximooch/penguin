"""AgentLauncher – facade for loading & running agents.

Direct copy of legacy `penguin/penguin/agent/launcher.py` with only import
paths adjusted.  Provides a single front-door for agent orchestration.
"""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Type

import yaml  # type: ignore

from penguin.agent.schema import AgentConfig
from penguin.agent.base import BaseAgent

from penguin.core import PenguinCore  # type: ignore
from penguin.system.conversation_manager import ConversationManager  # type: ignore
from penguin.llm.api_client import APIClient  # type: ignore
from penguin.tools import ToolManager  # type: ignore
from penguin.utils.parser import ActionExecutor  # type: ignore

logger = logging.getLogger(__name__)

AGENT_CONFIG_DIR = Path("agents")  # Default directory for agent YAML configs


class AgentLauncher:
    """Facade for loading, configuring, and invoking agents."""

    def __init__(
        self,
        core_instance: Optional[PenguinCore] = None,
        config_dir: Path = AGENT_CONFIG_DIR,
    ) -> None:
        self.core = core_instance
        self.config_dir = config_dir
        self._agent_configs: Dict[str, AgentConfig] = {}
        self._agent_classes: Dict[str, Type[BaseAgent]] = {}
        self.load_agent_configs()

    # ------------------------------------------------------------------
    # Config loading helpers
    # ------------------------------------------------------------------
    def load_agent_configs(self):
        """Load all *.yaml config files from *config_dir*."""
        if not self.config_dir.is_dir():
            logger.warning("Agent config directory not found: %s", self.config_dir)
            return

        for yaml_file in self.config_dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as fh:
                    config_data = yaml.safe_load(fh)
                agent_config = AgentConfig(**config_data)
                if agent_config.name in self._agent_configs:
                    logger.warning("Duplicate agent name '%s' found in %s – overwriting.", agent_config.name, yaml_file)
                self._agent_configs[agent_config.name] = agent_config
                logger.debug("Loaded agent config: %s", agent_config.name)
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Failed to load agent config from %s: %s", yaml_file, exc)

    # ------------------------------------------------------------------
    # Dynamic Class loading
    # ------------------------------------------------------------------
    def _get_agent_class(self, agent_config: AgentConfig) -> Type[BaseAgent]:
        class_path = agent_config.type
        if class_path in self._agent_classes:
            return self._agent_classes[class_path]

        module_path, class_name = class_path.rsplit(".", 1)
        try:
            module = importlib.import_module(module_path)
            agent_class = getattr(module, class_name)
            if not issubclass(agent_class, BaseAgent):
                raise TypeError(f"{class_path} is not a subclass of BaseAgent")
            self._agent_classes[class_path] = agent_class  # cache
            return agent_class
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            logger.error("Failed to load agent class %s: %s", class_path, exc)
            raise ImportError(f"Could not load agent class: {class_path}") from exc

    # ------------------------------------------------------------------
    # Agent instantiation helpers
    # ------------------------------------------------------------------
    def _instantiate_agent(self, agent_config: AgentConfig) -> BaseAgent:
        agent_cls = self._get_agent_class(agent_config)

        if not self.core:
            raise ValueError("PenguinCore instance required by Launcher for dependency injection.")

        conv_manager: ConversationManager = self.core.conversation_manager  # type: ignore[attr-defined]
        api_client: APIClient = self.core.api_client  # type: ignore[attr-defined]
        tool_manager: ToolManager = self.core.tool_manager  # type: ignore[attr-defined]
        action_executor: ActionExecutor = self.core.action_executor  # type: ignore[attr-defined]

        # TODO: Filter tool_manager based on agent_config.tools
        return agent_cls(
            agent_config=agent_config,
            conversation_manager=conv_manager,
            api_client=api_client,
            tool_manager=tool_manager,
            action_executor=action_executor,
        )

    # ------------------------------------------------------------------
    # Public API – invoke
    # ------------------------------------------------------------------
    async def invoke(
        self,
        agent_name: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        caller: str = "unknown",
    ) -> Any:  # noqa: ANN401
        if agent_name not in self._agent_configs:
            logger.error("Agent '%s' not found", agent_name)
            raise ValueError(f"Agent configuration '{agent_name}' not found.")

        agent_config = self._agent_configs[agent_name]
        sandbox_type = agent_config.security.sandbox_type

        if sandbox_type in {"docker", "shared_docker", "firecracker"}:
            # Use container execution for sandboxed agents
            from penguin.agent.container_executor import ContainerExecutor
            
            container_executor = ContainerExecutor()
            return await container_executor.execute_agent(
                agent_config.dict(), 
                prompt, 
                context
            )

        agent_instance = self._instantiate_agent(agent_config)

        try:
            result = await agent_instance.run(prompt, context)
            logger.info("Agent '%s' invoked by '%s' completed", agent_name, caller)
            return result
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Unexpected error invoking agent '%s': %s", agent_name, exc)
            return {"error": str(exc), "agent_name": agent_name} 