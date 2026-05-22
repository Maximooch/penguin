"""Agent lifecycle helpers used by :class:`penguin.core.PenguinCore`."""

from __future__ import annotations

from typing import Any

from penguin.agent.persona_runtime import (
    model_config_for_agent_settings,
    model_config_metadata,
)
from penguin.llm.api_client import APIClient
from penguin.utils.parser import ActionExecutor

__all__ = ["register_agent_compat"]


def register_agent_compat(core: Any, *args: Any, **kwargs: Any) -> None:
    """Register a legacy persona agent through the conversation-centered path."""

    agent_id = kwargs.pop("agent_id", None)
    if agent_id is None and args:
        agent_id = args[0]
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValueError("register_agent() requires a non-empty agent_id")
    agent_id = agent_id.strip()

    persona_name = kwargs.pop("persona", None)
    personas = getattr(core.config, "agent_personas", {}) or {}
    persona_config = (
        personas.get(persona_name)
        if isinstance(persona_name, str) and persona_name
        else None
    )

    system_prompt = kwargs.pop("system_prompt", None)
    if system_prompt is None and persona_config is not None:
        system_prompt = getattr(persona_config, "system_prompt", None)

    agent_model_config = model_config_for_agent_settings(
        getattr(persona_config, "model", None) if persona_config else None,
        model_configs=getattr(core.config, "model_configs", None),
        current_model_config=getattr(core, "model_config", None),
    )

    conv = core.conversation_manager.get_agent_conversation(
        agent_id, create_if_missing=True
    )
    if system_prompt and conv:
        conv.set_system_prompt(system_prompt)

    session = getattr(conv, "session", None)
    metadata = getattr(session, "metadata", None)
    if isinstance(metadata, dict):
        if persona_config is not None:
            metadata["persona"] = persona_config.name
            if getattr(persona_config, "description", None):
                metadata["persona_description"] = persona_config.description
            if getattr(persona_config, "default_tools", None):
                metadata["default_tools"] = list(persona_config.default_tools or [])
        metadata["model"] = model_config_metadata(agent_model_config)

    agent_context_windows = getattr(
        core.conversation_manager, "agent_context_windows", {}
    )
    if isinstance(agent_context_windows, dict) and agent_id in agent_context_windows:
        agent_context_windows[agent_id].model_config = agent_model_config

    if not hasattr(core, "_agent_api_clients"):
        core._agent_api_clients = {}
    if not hasattr(core, "_agent_model_overrides"):
        core._agent_model_overrides = {}
    if not hasattr(core, "_agent_tool_defaults"):
        core._agent_tool_defaults = {}

    api_client = APIClient(model_config=agent_model_config)
    if system_prompt:
        api_client.set_system_prompt(system_prompt)
    core._agent_api_clients[agent_id] = api_client
    core._agent_model_overrides[agent_id] = agent_model_config
    core._agent_tool_defaults[agent_id] = tuple(
        getattr(persona_config, "default_tools", None) or ()
    )

    if getattr(core, "engine", None):
        action_executor = ActionExecutor(
            core.tool_manager,
            core.project_manager,
            conv,
            ui_event_callback=core.emit_ui_event,
        )
        core.engine.register_agent(
            agent_id=agent_id,
            conversation_manager=core.conversation_manager,
            api_client=api_client,
            tool_manager=core.tool_manager,
            action_executor=action_executor,
        )
        if getattr(persona_config, "activate_by_default", False):
            core.engine.set_default_agent(agent_id)
