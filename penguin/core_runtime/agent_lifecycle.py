"""Agent lifecycle helpers used by :class:`penguin.core.PenguinCore`."""

from __future__ import annotations

import logging
import os
from typing import Any

from penguin.llm.api_client import APIClient
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    get_current_execution_context,
    normalize_directory,
)
from penguin.utils.parser import ActionExecutor

__all__ = [
    "create_agent_conversation",
    "create_sub_agent",
    "delete_agent_conversation",
    "delete_agent_conversation_compat",
    "delete_agent_conversation_guarded",
    "ensure_agent_conversation",
    "get_agent_profile",
    "get_agent_roster",
    "get_persona_catalog",
    "is_agent_paused",
    "list_agent_conversations",
    "list_agents",
    "list_sub_agents",
    "load_agent_conversation",
    "publish_sub_agent_session_created",
    "register_agent_compat",
    "resolve_agent_execution_scope",
    "run_agent_prompt_in_session",
    "set_active_agent",
    "set_agent_paused",
    "smoke_check_agents",
    "unregister_agent",
]

logger = logging.getLogger(__name__)


def get_persona_catalog(core: Any) -> list[dict[str, Any]]:
    """Return configured personas as serialisable dictionaries."""
    from penguin.agent.manager import get_persona_catalog as build_persona_catalog

    return build_persona_catalog(core.config)


def _build_agent_manager(core: Any) -> Any:
    """Build the AgentManager facade used by roster/profile API shims."""
    from penguin.agent.manager import AgentManager

    return AgentManager(
        conversation_manager=getattr(core, "conversation_manager", None),
        config=core.config,
        runtime_config=getattr(core, "runtime_config", None),
        is_paused_fn=core.is_agent_paused,
    )


def get_agent_roster(core: Any) -> list[dict[str, Any]]:
    """Return registered agents with their conversation metadata."""
    return _build_agent_manager(core).get_roster()


def get_agent_profile(core: Any, agent_id: str) -> dict[str, Any] | None:
    """Return roster information for a single agent identifier."""
    return _build_agent_manager(core).get_profile(agent_id)


def create_agent_conversation(core: Any, agent_id: str) -> str:
    """Create a new conversation for an agent through ConversationManager."""
    return core.conversation_manager.create_agent_conversation(agent_id)


def list_agent_conversations(
    core: Any,
    *,
    limit_per_agent: int = 1000,
    offset: int = 0,
) -> Any:
    """List agent-scoped conversations through ConversationManager."""
    return core.conversation_manager.list_all_conversations(
        limit_per_agent=limit_per_agent,
        offset=offset,
    )


def load_agent_conversation(
    core: Any,
    agent_id: str,
    conversation_id: str,
    *,
    activate: bool = True,
) -> bool:
    """Load an agent conversation through ConversationManager."""
    return core.conversation_manager.load_agent_conversation(
        agent_id,
        conversation_id,
        activate=activate,
    )


def list_agents(core: Any) -> list[str]:
    """Return all registered agent identifiers."""
    return core.conversation_manager.list_agents()


def list_sub_agents(
    core: Any,
    parent_agent_id: str | None = None,
) -> dict[str, list[str]]:
    """Return mapping of parent agents to sub-agent identifiers."""
    return core.conversation_manager.list_sub_agents(parent_agent_id)


def register_agent_compat(core: Any, *args: Any, **kwargs: Any) -> None:
    """Register a legacy persona agent through the conversation-centered path."""

    from penguin.agent.persona_runtime import (
        model_config_for_agent_settings,
        model_config_metadata,
    )

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


def set_active_agent(core: Any, agent_id: str) -> None:
    """Switch the active agent across ConversationManager and Engine."""
    try:
        core.conversation_manager.set_current_agent(agent_id)
    except Exception:
        logger.error(
            "Failed to switch ConversationManager to agent '%s'",
            agent_id,
            exc_info=True,
        )
        raise

    try:
        if getattr(core, "engine", None):
            core.engine.set_default_agent(agent_id)
    except Exception:
        logger.error(
            "Failed to set Engine default agent '%s'",
            agent_id,
            exc_info=True,
        )
        raise


def ensure_agent_conversation(
    core: Any,
    agent_id: str,
    *,
    system_prompt: str | None = None,
) -> None:
    """Ensure a conversation and optional Engine registration exist for an agent."""

    conv = core.conversation_manager.get_agent_conversation(
        agent_id,
        create_if_missing=True,
    )
    if system_prompt and conv:
        conv.set_system_prompt(system_prompt)

    if getattr(core, "engine", None):
        try:
            action_executor = ActionExecutor(
                core.tool_manager,
                core.project_manager,
                conv,
                ui_event_callback=core.emit_ui_event,
            )
            core.engine.register_agent(
                agent_id=agent_id,
                conversation_manager=core.conversation_manager,
                action_executor=action_executor,
            )
        except Exception:
            logger.debug(
                "Engine registration for '%s' failed",
                agent_id,
                exc_info=True,
            )


def delete_agent_conversation(core: Any, agent_id: str) -> bool:
    """Delete an agent conversation and unregister the Engine agent if present."""

    if agent_id == "default":
        raise ValueError("Cannot delete the default agent")

    removed = core.conversation_manager.remove_agent(agent_id)

    if getattr(core, "engine", None):
        try:
            core.engine.unregister_agent(agent_id)
        except Exception:
            logger.debug(
                "Engine unregister_agent failed for '%s'",
                agent_id,
                exc_info=True,
            )

    if core.conversation_manager.current_agent_id == agent_id:
        core.set_active_agent("default")

    return removed


def delete_agent_conversation_compat(
    core: Any,
    agent_id: str,
    conversation_id: str | None = None,
) -> bool:
    """Compatibility shim for legacy and conversation-centered delete calls."""

    if conversation_id is not None:
        return core.conversation_manager.delete_agent_conversation(
            agent_id,
            conversation_id,
        )
    return delete_agent_conversation(core, agent_id)


def delete_agent_conversation_guarded(
    core: Any,
    agent_id: str,
    conversation_id: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Delete a conversation with safety checks for shared sessions."""
    conversation_manager = core.conversation_manager

    try:
        shared_agents = conversation_manager.agents_sharing_session(agent_id)
        if len(shared_agents) > 1:
            conversation = conversation_manager.get_agent_conversation(agent_id)
            current_id = getattr(getattr(conversation, "session", None), "id", None)
            if current_id == conversation_id and not force:
                warning = (
                    f"Conversation {conversation_id} is shared by agents "
                    f"{shared_agents}. Deletion aborted. Use force=True to delete "
                    "anyway."
                )
                return {"success": False, "warning": warning}
    except Exception:
        logger.debug(
            "Failed to evaluate shared-session guard for '%s'",
            agent_id,
            exc_info=True,
        )

    success = conversation_manager.delete_agent_conversation(
        agent_id,
        conversation_id,
    )
    return {"success": success, "warning": None}


def create_sub_agent(
    core: Any,
    agent_id: str,
    *,
    parent_agent_id: str,
    system_prompt: str | None = None,
    share_session: bool = True,
    share_context_window: bool = True,
    shared_context_window_max_tokens: int | None = None,
) -> None:
    """Create a child agent and ensure its conversation exists."""

    core.conversation_manager.create_sub_agent(
        agent_id,
        parent_agent_id=parent_agent_id,
        share_session=share_session,
        share_context_window=share_context_window,
        shared_context_window_max_tokens=shared_context_window_max_tokens,
    )
    ensure_agent_conversation(core, agent_id, system_prompt=system_prompt)


def unregister_agent(
    core: Any,
    agent_id: str,
    *,
    preserve_conversation: bool = False,
) -> bool:
    """Unregister an agent while preserving compatibility with legacy callers."""

    if preserve_conversation:
        if getattr(core, "engine", None):
            try:
                core.engine.unregister_agent(agent_id)
            except Exception:
                logger.debug(
                    "Engine unregister_agent failed for '%s'",
                    agent_id,
                    exc_info=True,
                )
        return True
    return delete_agent_conversation(core, agent_id)


async def publish_sub_agent_session_created(
    core: Any,
    agent_id: str,
    *,
    parent_agent_id: str | None = None,
    share_session: bool = False,
) -> dict[str, Any] | None:
    """Bind isolated sub-agent session directory and emit session.created."""
    if share_session:
        return None

    conversation_manager = getattr(core, "conversation_manager", None)
    if conversation_manager is None:
        return None

    conversation = conversation_manager.get_agent_conversation(agent_id)
    session = getattr(conversation, "session", None)
    session_id = getattr(session, "id", None)
    if not isinstance(session_id, str) or not session_id:
        return None

    resolved_directory = None
    metadata = getattr(session, "metadata", None)
    if isinstance(metadata, dict):
        existing = metadata.get("directory")
        if isinstance(existing, str) and existing.strip():
            resolved_directory = existing.strip()

    if not resolved_directory and parent_agent_id:
        try:
            parent_conv = conversation_manager.get_agent_conversation(parent_agent_id)
            parent_session = getattr(parent_conv, "session", None)
            parent_metadata = getattr(parent_session, "metadata", None)
            if isinstance(parent_metadata, dict):
                mapped = parent_metadata.get("directory")
                if isinstance(mapped, str) and mapped.strip():
                    resolved_directory = mapped.strip()
            if not resolved_directory:
                parent_session_id = getattr(parent_session, "id", None)
                session_dirs = getattr(core, "_opencode_session_directories", None)
                if isinstance(parent_session_id, str) and isinstance(
                    session_dirs, dict
                ):
                    mapped = session_dirs.get(parent_session_id)
                    if isinstance(mapped, str) and mapped.strip():
                        resolved_directory = mapped.strip()
        except Exception:
            logger.debug(
                "Failed to resolve parent directory for sub-agent '%s'",
                agent_id,
                exc_info=True,
            )

    if not resolved_directory:
        context = get_current_execution_context()
        if context and context.directory:
            resolved_directory = context.directory

    if not resolved_directory:
        runtime = getattr(core, "runtime_config", None)
        runtime_dir = getattr(runtime, "active_root", None) or getattr(
            runtime, "project_root", None
        )
        if isinstance(runtime_dir, str) and runtime_dir.strip():
            resolved_directory = runtime_dir.strip()

    if not resolved_directory:
        env_dir = os.getenv("PENGUIN_CWD")
        if isinstance(env_dir, str) and env_dir.strip():
            resolved_directory = env_dir.strip()

    if not resolved_directory:
        resolved_directory = os.getcwd()

    session_dirs = getattr(core, "_opencode_session_directories", None)
    if not isinstance(session_dirs, dict):
        session_dirs = {}
        core._opencode_session_directories = session_dirs
    session_dirs[session_id] = resolved_directory

    if not isinstance(metadata, dict):
        metadata = {}
        session.metadata = metadata
    if metadata.get("directory") != resolved_directory:
        metadata["directory"] = resolved_directory
        try:
            conversation._modified = True
            conversation.save()
        except Exception:
            logger.debug(
                "Failed to persist sub-agent session directory for '%s'",
                agent_id,
                exc_info=True,
            )

    try:
        from penguin.web.services.session_view import get_session_info

        info = get_session_info(core, session_id)
    except Exception:
        logger.debug(
            "Failed to build session info for sub-agent '%s'",
            agent_id,
            exc_info=True,
        )
        return None

    if not isinstance(info, dict):
        return None

    try:
        from penguin.web.services.session_events import emit_session_created_event

        await emit_session_created_event(core, info)
    except Exception:
        logger.debug(
            "Failed to emit sub-agent session.created for '%s'",
            agent_id,
            exc_info=True,
        )
    return info


def smoke_check_agents(core: Any) -> dict[str, Any]:
    """Return a diagnostic snapshot of agent wiring and context windows."""
    conversation_manager = core.conversation_manager
    summary: dict[str, Any] = {
        "active_agent": getattr(conversation_manager, "current_agent_id", "default"),
        "agents": [],
        "shared_conversations": [],
        "engine_registry": {},
    }

    conversation_to_agents: dict[int, list[str]] = {}
    agent_sessions = getattr(conversation_manager, "agent_sessions", {})
    for agent_id, conversation in agent_sessions.items():
        try:
            session_id = getattr(conversation.session, "id", None)
            context_windows = getattr(
                conversation_manager,
                "agent_context_windows",
                None,
            )
            context_window = (
                context_windows.get(agent_id)
                if isinstance(context_windows, dict)
                else getattr(conversation_manager, "context_window", None)
            )
            context_window_usage = {}
            context_window_max = None
            if context_window and hasattr(context_window, "get_token_usage"):
                try:
                    usage = context_window.get_token_usage()
                    context_window_usage = {
                        "total": usage.get(
                            "total",
                            usage.get("current_total_tokens"),
                        ),
                        "available": usage.get(
                            "available",
                            usage.get("available_tokens"),
                        ),
                    }
                    context_window_max = usage.get(
                        "max",
                        usage.get(
                            "max_context_window_tokens",
                            usage.get("max_tokens"),
                        ),
                    )
                except Exception:
                    pass

            summary["agents"].append(
                {
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "conversation_obj": id(conversation),
                    "context_window_max": context_window_max,
                    "context_window_usage": context_window_usage,
                }
            )
            conversation_to_agents.setdefault(id(conversation), []).append(agent_id)
        except Exception:
            continue

    summary["shared_conversations"] = [
        {"conversation_obj": conversation_id, "agents": agent_ids}
        for conversation_id, agent_ids in conversation_to_agents.items()
        if len(agent_ids) > 1
    ]

    try:
        engine_agents = (
            set(core.engine.list_agents()) if getattr(core, "engine", None) else set()
        )
    except Exception:
        engine_agents = set()
    for agent in summary["agents"]:
        agent_id = agent.get("agent_id")
        summary["engine_registry"][agent_id] = agent_id in engine_agents

    return summary


def set_agent_paused(core: Any, agent_id: str, paused: bool = True) -> None:
    """Mark an agent as paused or resumed using conversation metadata."""
    conversation = core.conversation_manager.get_agent_conversation(agent_id)
    session = getattr(conversation, "session", None) if conversation else None
    metadata = getattr(session, "metadata", None)
    if isinstance(metadata, dict):
        metadata["paused"] = bool(paused)

    try:
        note = "Paused" if paused else "Resumed"
        core.conversation_manager.add_system_note(
            agent_id,
            f"Agent state: {note}",
            metadata={"type": "agent_state", "paused": bool(paused)},
        )
    except Exception:
        pass


def is_agent_paused(core: Any, agent_id: str) -> bool:
    """Return whether an agent is paused via conversation metadata."""
    conversation = core.conversation_manager.get_agent_conversation(agent_id)
    session = getattr(conversation, "session", None) if conversation else None
    metadata = getattr(session, "metadata", None)
    if isinstance(metadata, dict):
        return bool(metadata.get("paused", False))
    return False


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
