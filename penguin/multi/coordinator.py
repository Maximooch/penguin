from __future__ import annotations

"""MultiAgentCoordinator enhancements for multi-agent orchestration."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class AgentInfo:
    agent_id: str
    role: str
    system_prompt: Optional[str] = None
    model_max_tokens: Optional[int] = None


@dataclass
class LiteAgent:
    agent_id: str
    role: str
    handler: Callable[[str, Dict[str, Any]], Awaitable[Any] | Any]
    description: Optional[str] = None


class MultiAgentCoordinator:
    """Coordinates top-level agents, sub-agents, and lightweight helpers."""

    def __init__(self, core: "PenguinCore") -> None:  # type: ignore[name-defined]
        self.core = core
        self.agents_by_role: Dict[str, List[AgentInfo]] = {}
        self._rr_index: Dict[str, int] = {}
        self.lite_agents_by_role: Dict[str, List[LiteAgent]] = {}
        self._lite_counters: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    async def spawn_agent(
        self,
        agent_id: str,
        *,
        role: str,
        system_prompt: Optional[str] = None,
        model_max_tokens: Optional[int] = None,
        activate: bool = False,
    ) -> None:
        self.core.register_agent(
            agent_id,
            system_prompt=system_prompt,
            activate=activate,
            model_max_tokens=model_max_tokens,
        )
        info = AgentInfo(agent_id=agent_id, role=role, system_prompt=system_prompt, model_max_tokens=model_max_tokens)
        self.agents_by_role.setdefault(role, []).append(info)
        self._rr_index.setdefault(role, 0)
        logger.info("Spawned agent '%s' with role '%s'", agent_id, role)

    def register_existing(self, agent_id: str, *, role: str) -> None:
        info = AgentInfo(agent_id=agent_id, role=role)
        self.agents_by_role.setdefault(role, []).append(info)
        self._rr_index.setdefault(role, 0)

    async def destroy_agent(self, agent_id: str) -> None:
        for role, lst in list(self.agents_by_role.items()):
            self.agents_by_role[role] = [a for a in lst if a.agent_id != agent_id]
            if not self.agents_by_role[role]:
                self.agents_by_role.pop(role, None)
                self._rr_index.pop(role, None)
        logger.info("Destroyed agent '%s'", agent_id)

    # ------------------------------------------------------------------
    # Lite agents
    # ------------------------------------------------------------------

    def register_lite_agent(
        self,
        *,
        role: str,
        handler: Callable[[str, Dict[str, Any]], Awaitable[Any] | Any],
        agent_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        counter = self._lite_counters.get(role, 0) + 1
        self._lite_counters[role] = counter
        lite_id = agent_id or f"lite-{role}-{counter}"
        info = LiteAgent(agent_id=lite_id, role=role, handler=handler, description=description)
        self.lite_agents_by_role.setdefault(role, []).append(info)
        logger.info("Registered lite agent '%s' for role '%s'", lite_id, role)
        return lite_id

    def unregister_lite_agent(self, agent_id: str) -> None:
        for role, agents in list(self.lite_agents_by_role.items()):
            self.lite_agents_by_role[role] = [a for a in agents if a.agent_id != agent_id]
            if not self.lite_agents_by_role[role]:
                self.lite_agents_by_role.pop(role, None)

    async def _invoke_lite_agent(
        self,
        agent: LiteAgent,
        prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Any:
        meta = metadata or {}
        try:
            result = agent.handler(prompt, meta)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.error("Lite agent '%s' failed: %s", agent.agent_id, exc)
            return None

    async def execute_lite_agents(
        self,
        role: str,
        prompt: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        agents = self.lite_agents_by_role.get(role, [])
        if not agents:
            return None
        outputs: List[str] = []
        for agent in agents:
            res = await self._invoke_lite_agent(agent, prompt, metadata)
            if res is None:
                continue
            outputs.append(str(res))
        if not outputs:
            return None
        return {
            "assistant_response": "\n".join(outputs),
            "status": "completed",
            "action_results": [],
            "lite": True,
            "role": role,
        }

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    def select_agent(self, role: str) -> Optional[str]:
        agents = self.agents_by_role.get(role) or []
        if not agents:
            return None
        idx = self._rr_index.get(role, 0) % len(agents)
        self._rr_index[role] = (idx + 1) % len(agents)
        return agents[idx].agent_id

    async def send_to_role(self, role: str, content: Any, *, message_type: str = "message") -> Optional[str]:
        agent_id = self.select_agent(role)
        if agent_id:
            await self.core.send_to_agent(agent_id, content, message_type=message_type)
            return agent_id
        lite = await self.execute_lite_agents(role, str(content), metadata={"message_type": message_type})
        if lite:
            logger.info("Lite agents handled message for role '%s'", role)
            return "lite"
        logger.warning("No agents for role '%s'", role)
        return None

    async def broadcast(self, roles: Iterable[str], content: Any, *, message_type: str = "message") -> List[str]:
        sent_to: List[str] = []
        for role in roles:
            agents = self.agents_by_role.get(role, [])
            if agents:
                for info in agents:
                    await self.core.send_to_agent(info.agent_id, content, message_type=message_type)
                    sent_to.append(info.agent_id)
            else:
                lite = await self.execute_lite_agents(role, str(content), metadata={"message_type": message_type})
                if lite:
                    sent_to.append("lite")
        return sent_to

    # ------------------------------------------------------------------
    # Workflows
    # ------------------------------------------------------------------

    async def simple_round_robin_workflow(self, prompts: List[str], *, role: str) -> None:
        for prompt in prompts:
            target = await self.send_to_role(role, prompt)
            logger.info("Round-robin dispatched to %s", target)

    async def role_chain_workflow(self, content: str, *, roles: List[str]) -> List[str]:
        lineage: List[str] = []
        current = content
        for role in roles:
            target = await self.send_to_role(role, current)
            lineage.append(target or "none")
            current = f"{role} response: {current}"
        return lineage
