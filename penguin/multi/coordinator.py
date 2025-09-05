from __future__ import annotations

"""MultiAgentCoordinator scaffold (Phase 4 preview).

Provides a minimal coordinator capable of:
- Registering agents by role
- Spawning/destroying agents via PenguinCore wrappers
- Simple round-robin and role-based routing examples

This is a thin orchestrator; scheduling strategies can be extended.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Iterable
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class AgentInfo:
    agent_id: str
    role: str
    system_prompt: Optional[str] = None
    model_max_tokens: Optional[int] = None


class MultiAgentCoordinator:
    def __init__(self, core: "PenguinCore") -> None:  # type: ignore[name-defined]
        self.core = core
        self.agents_by_role: Dict[str, List[AgentInfo]] = {}
        self._rr_index: Dict[str, int] = {}

    # --------------------- Agent lifecycle ---------------------
    async def spawn_agent(
        self,
        agent_id: str,
        *,
        role: str,
        system_prompt: Optional[str] = None,
        model_max_tokens: Optional[int] = None,
        activate: bool = False,
    ) -> None:
        """Create/register an agent with the core and coordinator."""
        self.core.register_agent(
            agent_id,
            system_prompt=system_prompt,
            activate=activate,
            model_max_tokens=model_max_tokens,
        )
        info = AgentInfo(agent_id=agent_id, role=role, system_prompt=system_prompt, model_max_tokens=model_max_tokens)
        self.agents_by_role.setdefault(role, []).append(info)
        self._rr_index.setdefault(role, 0)
        logger.info(f"Spawned agent '{agent_id}' with role '{role}'")

    def register_existing(self, agent_id: str, *, role: str) -> None:
        info = AgentInfo(agent_id=agent_id, role=role)
        self.agents_by_role.setdefault(role, []).append(info)
        self._rr_index.setdefault(role, 0)

    async def destroy_agent(self, agent_id: str) -> None:
        """Teardown hooks placeholder (deregister bus handlers as needed)."""
        # Remove from role map
        for role, lst in list(self.agents_by_role.items()):
            self.agents_by_role[role] = [a for a in lst if a.agent_id != agent_id]
        logger.info(f"Destroyed agent '{agent_id}' (conversation persists; re-register to reactivate)")

    # --------------------- Routing helpers ---------------------
    async def send_to_role(self, role: str, content: Any, *, message_type: str = "message") -> Optional[str]:
        """Round-robin to an agent with the given role. Returns agent_id if sent."""
        agents = self.agents_by_role.get(role) or []
        if not agents:
            logger.warning(f"No agents for role '{role}'")
            return None
        idx = self._rr_index.get(role, 0) % len(agents)
        target = agents[idx]
        self._rr_index[role] = (idx + 1) % len(agents)
        await self.core.send_to_agent(target.agent_id, content, message_type=message_type)
        return target.agent_id

    async def broadcast(self, roles: Iterable[str], content: Any, *, message_type: str = "message") -> List[str]:
        """Broadcast a message to all agents for the specified roles."""
        sent_to: List[str] = []
        for r in roles:
            for info in self.agents_by_role.get(r, []):
                await self.core.send_to_agent(info.agent_id, content, message_type=message_type)
                sent_to.append(info.agent_id)
        return sent_to

    # --------------------- Demo workflows ---------------------
    async def simple_round_robin_workflow(self, prompts: List[str], *, role: str) -> None:
        for p in prompts:
            target = await self.send_to_role(role, p)
            logger.info(f"Sent to {target}: {p[:40]}")

    async def role_chain_workflow(self, content: str, *, roles: List[str]) -> None:
        """Pass content through a sequence of roles (planner→researcher→implementer)."""
        current = content
        for r in roles:
            target = await self.send_to_role(r, current)
            logger.info(f"Delegated to {r} ({target})")

