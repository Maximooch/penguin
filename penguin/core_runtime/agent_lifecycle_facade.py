"""Agent lifecycle and routing compatibility facade for ``PenguinCore``."""

from __future__ import annotations

import logging
from typing import Any

from penguin.core_runtime import agent_lifecycle as core_agent_lifecycle
from penguin.multi import routing as multi_routing

__all__ = ["AgentLifecycleCoreFacade"]

logger = logging.getLogger("penguin.core")


class AgentLifecycleCoreFacade:
    """Compatibility methods for agent, sub-agent, and message-routing helpers."""

    def get_persona_catalog(self) -> list[dict[str, Any]]:
        """Return configured personas as serialisable dictionaries."""
        return core_agent_lifecycle.get_persona_catalog(self)

    def get_agent_roster(self) -> list[dict[str, Any]]:
        """Return list of registered agents with their conversation metadata."""
        return core_agent_lifecycle.get_agent_roster(self)

    def get_agent_profile(self, agent_id: str) -> dict[str, Any] | None:
        """Return roster information for a single agent identifier."""
        return core_agent_lifecycle.get_agent_profile(self, agent_id)

    def register_agent(self, *args: Any, **kwargs: Any) -> None:
        """Compatibility shim for legacy persona-based agent registration."""
        core_agent_lifecycle.register_agent_compat(self, *args, **kwargs)

    def set_active_agent(self, agent_id: str) -> None:
        """Switch the active agent across ConversationManager and Engine."""
        core_agent_lifecycle.set_active_agent(self, agent_id)

    def create_agent_conversation(self, agent_id: str) -> str:
        return core_agent_lifecycle.create_agent_conversation(self, agent_id)

    def list_all_conversations(
        self,
        *,
        limit_per_agent: int = 1000,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return core_agent_lifecycle.list_agent_conversations(
            self,
            limit_per_agent=limit_per_agent,
            offset=offset,
        )

    def load_agent_conversation(
        self,
        agent_id: str,
        conversation_id: str,
        *,
        activate: bool = True,
    ) -> bool:
        return core_agent_lifecycle.load_agent_conversation(
            self,
            agent_id,
            conversation_id,
            activate=activate,
        )

    def delete_agent_conversation_guarded(
        self,
        agent_id: str,
        conversation_id: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Delete a conversation with safety checks for shared sessions."""
        return core_agent_lifecycle.delete_agent_conversation_guarded(
            self,
            agent_id,
            conversation_id,
            force=force,
        )

    def list_agents(self) -> list[str]:
        """Return all registered agent identifiers."""
        return core_agent_lifecycle.list_agents(self)

    def list_sub_agents(
        self,
        parent_agent_id: str | None = None,
    ) -> dict[str, list[str]]:
        """Return mapping of parent agents to sub-agents."""
        return core_agent_lifecycle.list_sub_agents(self, parent_agent_id)

    def set_agent_paused(self, agent_id: str, paused: bool = True) -> None:
        """Mark an agent as paused/resumed using conversation metadata."""
        core_agent_lifecycle.set_agent_paused(self, agent_id, paused)

    def is_agent_paused(self, agent_id: str) -> bool:
        """Check if agent is paused via conversation metadata."""
        return core_agent_lifecycle.is_agent_paused(self, agent_id)

    def ensure_agent_conversation(
        self,
        agent_id: str,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Ensure a conversation exists for an agent."""
        del kwargs
        core_agent_lifecycle.ensure_agent_conversation(
            self,
            agent_id,
            system_prompt=system_prompt,
        )

    def delete_agent_conversation(
        self,
        agent_id: str,
        conversation_id: str | None = None,
    ) -> bool:
        """Delete an agent or a specific agent conversation."""
        return core_agent_lifecycle.delete_agent_conversation_compat(
            self,
            agent_id,
            conversation_id,
        )

    def create_sub_agent(
        self,
        agent_id: str,
        *,
        parent_agent_id: str,
        system_prompt: str | None = None,
        share_session: bool = True,
        share_context_window: bool = True,
        shared_context_window_max_tokens: int | None = None,
        **kwargs: Any,
    ) -> None:
        """Create a sub-agent linked to a parent agent."""
        del kwargs
        core_agent_lifecycle.create_sub_agent(
            self,
            agent_id,
            parent_agent_id=parent_agent_id,
            system_prompt=system_prompt,
            share_session=share_session,
            share_context_window=share_context_window,
            shared_context_window_max_tokens=shared_context_window_max_tokens,
        )

    async def publish_sub_agent_session_created(
        self,
        agent_id: str,
        *,
        parent_agent_id: str | None = None,
        share_session: bool = False,
    ) -> dict[str, Any] | None:
        """Bind isolated sub-agent session directory and emit session.created."""
        return await core_agent_lifecycle.publish_sub_agent_session_created(
            self,
            agent_id,
            parent_agent_id=parent_agent_id,
            share_session=share_session,
        )

    def resolve_agent_execution_scope(
        self,
        agent_id: str,
        *,
        session_id: str | None = None,
        directory: str | None = None,
        agent_mode: str | None = None,
    ) -> dict[str, str | None]:
        """Resolve session-scoped execution context for an agent run."""
        return core_agent_lifecycle.resolve_agent_execution_scope(
            self,
            agent_id,
            session_id=session_id,
            directory=directory,
            agent_mode=agent_mode,
        )

    async def run_agent_prompt_in_session(
        self,
        agent_id: str,
        prompt: str,
        *,
        session_id: str | None = None,
        directory: str | None = None,
        agent_mode: str | None = None,
        streaming: bool | None = None,
    ) -> dict[str, Any]:
        """Run an agent prompt inside that agent's session-scoped execution context."""
        return await core_agent_lifecycle.run_agent_prompt_in_session(
            self,
            agent_id,
            prompt,
            session_id=session_id,
            directory=directory,
            agent_mode=agent_mode,
            streaming=streaming,
        )

    def unregister_agent(
        self,
        agent_id: str,
        *,
        preserve_conversation: bool = False,
    ) -> bool:
        """Unregister an agent. Delegates to delete_agent_conversation()."""
        return core_agent_lifecycle.unregister_agent(
            self,
            agent_id,
            preserve_conversation=preserve_conversation,
        )

    async def route_message(
        self,
        recipient_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: dict[str, Any] | None = None,
        agent_id: str | None = None,
        channel: str | None = None,
    ) -> bool:
        """Route a message via Engine's MessageBus integration."""
        return await multi_routing.route_message(
            self,
            recipient_id,
            content,
            message_type=message_type,
            metadata=metadata,
            agent_id=agent_id,
            channel=channel,
            logger=logger,
        )

    async def send_to_agent(
        self,
        agent_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: dict[str, Any] | None = None,
        channel: str | None = None,
    ) -> bool:
        """Send a message to an agent via Engine."""
        return await multi_routing.send_to_agent(
            self,
            agent_id,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

    async def send_to_human(
        self,
        content: Any,
        *,
        message_type: str = "status",
        metadata: dict[str, Any] | None = None,
        channel: str | None = None,
    ) -> bool:
        """Send a message to the human (UI) via Engine."""
        return await multi_routing.send_to_human(
            self,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

    async def human_reply(
        self,
        agent_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: dict[str, Any] | None = None,
        channel: str | None = None,
    ) -> bool:
        """Send a reply from human to an agent via Engine."""
        return await multi_routing.human_reply(
            self,
            agent_id,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )
