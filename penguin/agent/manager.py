"""Agent management utilities.

This module provides agent roster and profile functionality,
extracted from core.py for better separation of concerns.
"""

from typing import Any, Callable, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages agent roster and profile queries.

    This class provides read-only views of agent state derived from
    conversation metadata. It does not manage agent lifecycle - that's
    handled by ConversationManager and Engine.

    Usage:
        manager = AgentManager(
            conversation_manager=core.conversation_manager,
            config=core.config,
            is_paused_fn=core.is_agent_paused,
        )
        roster = manager.get_roster()
        profile = manager.get_profile("analyzer")
    """

    def __init__(
        self,
        conversation_manager: Any,
        config: Any,
        is_paused_fn: Optional[Callable[[str], bool]] = None,
    ):
        """Initialize AgentManager.

        Args:
            conversation_manager: ConversationManager instance
            config: Config instance with agent_personas
            is_paused_fn: Optional function to check if agent is paused
        """
        self._cm = conversation_manager
        self._config = config
        self._is_paused_fn = is_paused_fn or (lambda _: False)

    def get_roster(self) -> List[Dict[str, Any]]:
        """Return list of registered agents with their conversation metadata.

        Returns:
            List of agent info dicts with keys:
            - id: Agent identifier
            - persona: Persona name if any
            - persona_description: Description of persona
            - persona_defined: Whether persona is defined in config
            - parent: Parent agent ID if sub-agent
            - children: List of child agent IDs
            - active: Whether this is the current agent
            - paused: Whether agent is paused
            - is_sub_agent: Whether this is a sub-agent
            - system_prompt_preview: First 80 chars of system prompt
        """
        if self._cm is None:
            return []

        try:
            agent_ids = self._cm.list_agents()
        except Exception:
            agent_ids = []

        parent_map = getattr(self._cm, "sub_agent_parent", {}) or {}
        children_map = self._cm.list_sub_agents() if hasattr(self._cm, "list_sub_agents") else {}
        active_agent = getattr(self._cm, "current_agent_id", None)
        personas = getattr(self._config, "agent_personas", {}) or {}

        roster: List[Dict[str, Any]] = []
        for agent_id in agent_ids:
            conv = self._cm.get_agent_conversation(agent_id)

            metadata: Dict[str, Any] = {}
            system_prompt = None
            if conv is not None:
                system_prompt = getattr(conv, "system_prompt", None)
                session = getattr(conv, "session", None)
                if session is not None:
                    metadata = dict(getattr(session, "metadata", {}) or {})

            persona_name = metadata.get("persona")
            persona_config = personas.get(persona_name) if persona_name else None
            persona_description = metadata.get("persona_description")
            if not persona_description and persona_config:
                persona_description = getattr(persona_config, "description", None)

            parent = parent_map.get(agent_id)
            children = list(children_map.get(agent_id, [])) if isinstance(children_map, dict) else []

            preview = None
            if system_prompt:
                preview = system_prompt if len(system_prompt) <= 80 else system_prompt[:77] + "..."

            roster.append({
                "id": agent_id,
                "persona": persona_name,
                "persona_description": persona_description,
                "persona_defined": bool(persona_config),
                "parent": parent,
                "children": children,
                "active": agent_id == active_agent,
                "paused": self._is_paused_fn(agent_id),
                "is_sub_agent": parent is not None,
                "system_prompt_preview": preview,
            })

        roster.sort(key=lambda entry: (entry["parent"] or "", entry["id"]))
        return roster

    def get_profile(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Return roster information for a single agent.

        Args:
            agent_id: Agent identifier to look up

        Returns:
            Agent info dict or None if not found
        """
        for entry in self.get_roster():
            if entry.get("id") == agent_id:
                return entry
        return None


# Convenience function for one-off queries
def get_agent_roster(
    conversation_manager: Any,
    config: Any,
    is_paused_fn: Optional[Callable[[str], bool]] = None,
) -> List[Dict[str, Any]]:
    """Get agent roster without creating a manager instance.

    Args:
        conversation_manager: ConversationManager instance
        config: Config instance
        is_paused_fn: Optional pause check function

    Returns:
        List of agent info dicts
    """
    return AgentManager(conversation_manager, config, is_paused_fn).get_roster()


def get_agent_profile(
    agent_id: str,
    conversation_manager: Any,
    config: Any,
    is_paused_fn: Optional[Callable[[str], bool]] = None,
) -> Optional[Dict[str, Any]]:
    """Get single agent profile without creating a manager instance.

    Args:
        agent_id: Agent to look up
        conversation_manager: ConversationManager instance
        config: Config instance
        is_paused_fn: Optional pause check function

    Returns:
        Agent info dict or None
    """
    return AgentManager(conversation_manager, config, is_paused_fn).get_profile(agent_id)


__all__ = [
    "AgentManager",
    "get_agent_roster",
    "get_agent_profile",
]
