from __future__ import annotations

"""MultiAgentCoordinator enhancements for multi-agent orchestration."""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence
import asyncio
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class AgentInfo:
    """Information about a registered agent.
    
    Attributes:
        agent_id: Unique identifier for the agent
        role: Role/function of the agent (e.g., "analyzer", "implementer")
        system_prompt: Custom system prompt override
        model_max_tokens: Token limit for this agent
        persona: Persona config name to apply
        model_config_id: Model configuration override
        default_tools: Tool name restrictions (legacy, use permissions)
        permissions: Permission configuration dict for this agent
        parent_agent_id: Parent agent for permission inheritance
    """
    agent_id: str
    role: str
    system_prompt: Optional[str] = None
    model_max_tokens: Optional[int] = None
    persona: Optional[str] = None
    model_config_id: Optional[str] = None
    default_tools: Optional[Sequence[str]] = None
    permissions: Optional[Dict[str, Any]] = None
    parent_agent_id: Optional[str] = None


@dataclass
class LiteAgent:
    """Lightweight agent with a simple handler function.
    
    Lite agents are registered callable handlers that can be invoked
    when no full agent is available for a role. They receive the same
    permission enforcement as full agents.
    
    Attributes:
        agent_id: Unique identifier
        role: Role/function of the agent
        handler: Async or sync callable for processing requests
        description: Human-readable description
        permissions: Permission configuration dict (same as AgentInfo)
    """
    agent_id: str
    role: str
    handler: Callable[[str, Dict[str, Any]], Awaitable[Any] | Any]
    description: Optional[str] = None
    permissions: Optional[Dict[str, Any]] = None


@dataclass
class DelegationRecord:
    id: str
    parent_agent_id: str
    child_agent_id: str
    status: str = "started"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    summary: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MultiAgentCoordinator:
    """Coordinates top-level agents, sub-agents, and lightweight helpers."""

    def __init__(self, core: "PenguinCore") -> None:  # type: ignore[name-defined]
        self.core = core
        self.agents_by_role: Dict[str, List[AgentInfo]] = {}
        self._rr_index: Dict[str, int] = {}
        self.lite_agents_by_role: Dict[str, List[LiteAgent]] = {}
        self._lite_counters: Dict[str, int] = {}
        self._delegations: Dict[str, DelegationRecord] = {}

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
        persona: Optional[str] = None,
        model_config_id: Optional[str] = None,
        model_overrides: Optional[Dict[str, Any]] = None,
        default_tools: Optional[Sequence[str]] = None,
        permissions: Optional[Dict[str, Any]] = None,
        parent_agent_id: Optional[str] = None,
        shared_cw_max_tokens: Optional[int] = None,
        share_session_with: Optional[str] = None,
        share_context_window_with: Optional[str] = None,
    ) -> None:
        """Spawn a new agent with optional permission restrictions.
        
        Args:
            agent_id: Unique identifier for the agent
            role: Agent's role (e.g., "analyzer", "implementer")
            system_prompt: Custom system prompt
            model_max_tokens: Token limit
            activate: Whether to make this the active agent
            persona: Persona config name to apply
            model_config_id: Model configuration override
            model_overrides: Additional model parameter overrides
            default_tools: Tool name restrictions (legacy)
            permissions: Permission config dict (mode, operations, paths)
            parent_agent_id: Parent agent for permission inheritance
            shared_cw_max_tokens: Shared context window token limit
            share_session_with: Agent ID to share session with
            share_context_window_with: Agent ID to share context window with
        """
        self.core.register_agent(
            agent_id,
            system_prompt=system_prompt,
            activate=activate,
            model_max_tokens=model_max_tokens,
            persona=persona,
            model_config_id=model_config_id,
            model_overrides=model_overrides,
            default_tools=default_tools,
            shared_cw_max_tokens=shared_cw_max_tokens,
            share_session_with=share_session_with,
            share_context_window_with=share_context_window_with,
        )
        info = AgentInfo(
            agent_id=agent_id,
            role=role,
            system_prompt=system_prompt,
            model_max_tokens=model_max_tokens,
            persona=persona,
            model_config_id=model_config_id,
            default_tools=tuple(default_tools) if default_tools else None,
            permissions=dict(permissions) if permissions else None,
            parent_agent_id=parent_agent_id,
        )
        self.agents_by_role.setdefault(role, []).append(info)
        self._rr_index.setdefault(role, 0)
        
        # Register agent permission policy if permissions specified
        if permissions:
            self._register_agent_permissions(agent_id, permissions, parent_agent_id)
        
        logger.info("Spawned agent '%s' with role '%s'", agent_id, role)
    
    def _register_agent_permissions(
        self,
        agent_id: str,
        permissions: Dict[str, Any],
        parent_agent_id: Optional[str] = None,
    ) -> None:
        """Register permission policy for an agent.
        
        Lazily imports security module to avoid circular imports.
        """
        try:
            from penguin.security.agent_permissions import (
                AgentPermissionConfig,
                register_agent_policy,
            )
            
            config = AgentPermissionConfig.from_dict(permissions)
            register_agent_policy(agent_id, config, parent_agent_id)
            logger.debug(f"Registered permission policy for agent '{agent_id}'")
            
        except ImportError:
            logger.debug("Security module not available, skipping permission registration")
        except Exception as e:
            logger.warning(f"Failed to register agent permissions: {e}")

    def register_existing(
        self,
        agent_id: str,
        *,
        role: str,
        permissions: Optional[Dict[str, Any]] = None,
        parent_agent_id: Optional[str] = None,
    ) -> None:
        """Register an existing agent with the coordinator.
        
        Args:
            agent_id: Agent ID to register
            role: Agent's role
            permissions: Optional permission config dict
            parent_agent_id: Parent agent for permission inheritance
        """
        info = AgentInfo(
            agent_id=agent_id,
            role=role,
            permissions=dict(permissions) if permissions else None,
            parent_agent_id=parent_agent_id,
        )
        self.agents_by_role.setdefault(role, []).append(info)
        self._rr_index.setdefault(role, 0)
        
        if permissions:
            self._register_agent_permissions(agent_id, permissions, parent_agent_id)

    async def destroy_agent(self, agent_id: str) -> None:
        """Destroy an agent and clean up its permission policy."""
        for role, lst in list(self.agents_by_role.items()):
            self.agents_by_role[role] = [a for a in lst if a.agent_id != agent_id]
            if not self.agents_by_role[role]:
                self.agents_by_role.pop(role, None)
                self._rr_index.pop(role, None)
        
        # Unregister permission policy
        self._unregister_agent_permissions(agent_id)
        logger.info("Destroyed agent '%s'", agent_id)
    
    def _unregister_agent_permissions(self, agent_id: str) -> None:
        """Unregister permission policy for an agent."""
        try:
            from penguin.security.agent_permissions import unregister_agent_policy
            unregister_agent_policy(agent_id)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"Failed to unregister agent permissions: {e}")

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
        permissions: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Register a lightweight agent handler.
        
        Args:
            role: Agent role
            handler: Async or sync callable for processing requests
            agent_id: Optional custom ID (auto-generated if not provided)
            description: Human-readable description
            permissions: Optional permission config dict
            
        Returns:
            The agent ID (provided or generated)
        """
        counter = self._lite_counters.get(role, 0) + 1
        self._lite_counters[role] = counter
        lite_id = agent_id or f"lite-{role}-{counter}"
        info = LiteAgent(
            agent_id=lite_id,
            role=role,
            handler=handler,
            description=description,
            permissions=dict(permissions) if permissions else None,
        )
        self.lite_agents_by_role.setdefault(role, []).append(info)
        
        # Register permission policy for lite agent
        if permissions:
            self._register_agent_permissions(lite_id, permissions, parent_agent_id=None)
        
        logger.info("Registered lite agent '%s' for role '%s'", lite_id, role)
        return lite_id

    def unregister_lite_agent(self, agent_id: str) -> None:
        """Unregister a lite agent and clean up its permission policy."""
        for role, agents in list(self.lite_agents_by_role.items()):
            self.lite_agents_by_role[role] = [a for a in agents if a.agent_id != agent_id]
            if not self.lite_agents_by_role[role]:
                self.lite_agents_by_role.pop(role, None)
        
        # Unregister permission policy
        self._unregister_agent_permissions(agent_id)

    # ------------------------------------------------------------------
    # Delegation tracking
    # ------------------------------------------------------------------

    def start_delegation(
        self,
        *,
        parent_agent_id: str,
        child_agent_id: str,
        summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        delegation_id = uuid.uuid4().hex[:12]
        record = DelegationRecord(
            id=delegation_id,
            parent_agent_id=parent_agent_id,
            child_agent_id=child_agent_id,
            summary=summary,
            metadata=dict(metadata or {}),
        )
        self._delegations[delegation_id] = record
        self.core.conversation_manager.log_delegation_event(
            delegation_id=delegation_id,
            parent_agent_id=parent_agent_id,
            child_agent_id=child_agent_id,
            event="started",
            message=summary,
        )
        logger.info(
            "Delegation %s started (%s -> %s)",
            delegation_id,
            parent_agent_id,
            child_agent_id,
        )
        return delegation_id

    def _update_delegation(
        self,
        delegation_id: str,
        *,
        event: str,
        message: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = self._delegations.get(delegation_id)
        if not record:
            logger.warning("Delegation '%s' not found for event '%s'", delegation_id, event)
            return
        record.status = event
        record.updated_at = datetime.utcnow()
        if extra_metadata:
            record.metadata.update(extra_metadata)
        self.core.conversation_manager.log_delegation_event(
            delegation_id=record.id,
            parent_agent_id=record.parent_agent_id,
            child_agent_id=record.child_agent_id,
            event=event,
            message=message,
            metadata=extra_metadata,
        )

    def complete_delegation(
        self,
        delegation_id: str,
        *,
        result_summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._update_delegation(
            delegation_id,
            event="completed",
            message=result_summary,
            extra_metadata=metadata,
        )

    def fail_delegation(
        self,
        delegation_id: str,
        *,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._update_delegation(
            delegation_id,
            event="failed",
            message=error,
            extra_metadata=metadata,
        )

    def get_delegation(self, delegation_id: str) -> Optional[DelegationRecord]:
        return self._delegations.get(delegation_id)

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

    async def delegate_message(
        self,
        *,
        parent_agent_id: str,
        child_agent_id: str,
        content: Any,
        delegation_id: Optional[str] = None,
        message_type: str = "message",
        channel: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        summary: Optional[str] = None,
    ) -> str:
        """Send a message to a sub-agent with delegation tracking metadata."""

        if delegation_id is None:
            delegation_id = self.start_delegation(
                parent_agent_id=parent_agent_id,
                child_agent_id=child_agent_id,
                summary=summary,
                metadata=metadata,
            )

        meta = {
            "delegation_id": delegation_id,
            "parent_agent_id": parent_agent_id,
            "child_agent_id": child_agent_id,
            "delegation_event": "request_sent",
        }
        if metadata:
            meta.update(metadata)

        await self.core.send_to_agent(
            child_agent_id,
            content,
            message_type=message_type,
            metadata=meta,
            channel=channel,
        )

        self._update_delegation(
            delegation_id,
            event="request_sent",
            message=summary,
            extra_metadata=metadata,
        )
        return delegation_id

    def record_child_response(
        self,
        delegation_id: str,
        *,
        response_summary: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log that the delegated agent produced an update/response."""

        self._update_delegation(
            delegation_id,
            event="response_received",
            message=response_summary,
            extra_metadata=metadata,
        )

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
