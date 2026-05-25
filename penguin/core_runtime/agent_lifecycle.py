"""Agent lifecycle helpers used by :class:`penguin.core.PenguinCore`."""

from __future__ import annotations

import logging
from typing import Any

from penguin.agent.persona_runtime import (
    model_config_for_agent_settings,
    model_config_metadata,
)
from penguin.llm.api_client import APIClient
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    get_current_execution_context,
    normalize_directory,
)
from penguin.utils.parser import ActionExecutor

__all__ = [
    "register_agent_compat",
    "resolve_agent_execution_scope",
    "run_agent_prompt_in_session",
]

logger = logging.getLogger(__name__)


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


def resolve_agent_execution_scope(
    core: Any,
    agent_id: str,
    *,
    session_id: str | None = None,
    directory: str | None = None,
    agent_mode: str | None = None,
) -> dict[str, str | None]:
    """Resolve session-scoped execution context for an agent run."""
    resolved_session_id = session_id if isinstance(session_id, str) else None
    resolved_directory = directory if isinstance(directory, str) else None
    resolved_agent_mode = agent_mode if isinstance(agent_mode, str) else None

    conversation_manager = getattr(core, "conversation_manager", None)
    session = None
    if conversation_manager is not None:
        try:
            conversation = conversation_manager.get_agent_conversation(agent_id)
            session = getattr(conversation, "session", None)
        except Exception:
            logger.debug(
                "Failed to resolve agent conversation for '%s'",
                agent_id,
                exc_info=True,
            )

    metadata = getattr(session, "metadata", None)
    if not resolved_session_id:
        candidate = getattr(session, "id", None)
        if isinstance(candidate, str) and candidate.strip():
            resolved_session_id = candidate.strip()

    if isinstance(metadata, dict):
        if not resolved_directory:
            candidate_directory = metadata.get("directory")
            if isinstance(candidate_directory, str) and candidate_directory.strip():
                resolved_directory = candidate_directory.strip()
        if not resolved_agent_mode:
            candidate_mode = metadata.get("_opencode_agent_mode_v1") or metadata.get(
                "agent_mode"
            )
            if isinstance(candidate_mode, str) and candidate_mode.strip():
                resolved_agent_mode = candidate_mode.strip().lower()

    if not resolved_directory and resolved_session_id:
        session_dirs = getattr(core, "_opencode_session_directories", None)
        if isinstance(session_dirs, dict):
            mapped = session_dirs.get(resolved_session_id)
            if isinstance(mapped, str) and mapped.strip():
                resolved_directory = mapped.strip()

    inherited_context = get_current_execution_context()
    if not resolved_directory and inherited_context and inherited_context.directory:
        resolved_directory = inherited_context.directory
    if not resolved_agent_mode and inherited_context and inherited_context.agent_mode:
        resolved_agent_mode = inherited_context.agent_mode

    resolved_directory = normalize_directory(resolved_directory) or resolved_directory
    project_root = (
        inherited_context.project_root
        if inherited_context and inherited_context.project_root
        else resolved_directory
    )
    workspace_root = (
        inherited_context.workspace_root
        if inherited_context and inherited_context.workspace_root
        else resolved_directory
    )

    return {
        "session_id": resolved_session_id,
        "conversation_id": resolved_session_id,
        "directory": resolved_directory,
        "project_root": project_root,
        "workspace_root": workspace_root,
        "agent_mode": resolved_agent_mode,
    }


async def run_agent_prompt_in_session(
    core: Any,
    agent_id: str,
    prompt: str,
    *,
    session_id: str | None = None,
    directory: str | None = None,
    agent_mode: str | None = None,
    streaming: bool | None = None,
) -> dict[str, Any]:
    """Run an agent prompt inside that agent's session-scoped execution context."""
    scope = resolve_agent_execution_scope(
        core,
        agent_id,
        session_id=session_id,
        directory=directory,
        agent_mode=agent_mode,
    )
    execution_context = ExecutionContext(
        session_id=scope.get("session_id"),
        conversation_id=scope.get("conversation_id"),
        agent_id=agent_id,
        agent_mode=scope.get("agent_mode"),
        directory=scope.get("directory"),
        project_root=scope.get("project_root"),
        workspace_root=scope.get("workspace_root"),
        request_id=(f"subagent:{agent_id}:{scope.get('conversation_id') or 'unknown'}"),
    )
    with execution_context_scope(execution_context):
        return await core.process(
            input_data={"text": prompt},
            conversation_id=scope.get("conversation_id"),
            agent_id=agent_id,
            streaming=streaming,
        )
