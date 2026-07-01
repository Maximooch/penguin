"""Conversation facade helpers for :mod:`penguin.core`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ConversationLoadResult",
    "create_conversation",
    "delete_conversation",
    "get_conversation",
    "get_conversation_history",
    "get_conversation_stats",
    "list_conversations",
    "load_process_context_files",
    "load_process_conversation",
    "resolve_conversation_manager",
    "session_payload",
]


@dataclass(frozen=True)
class ConversationLoadResult:
    """Result metadata for process conversation loading."""

    via: str
    ok: bool
    scoped_session_id: str | None


def list_conversations(
    conversation_manager: Any,
    *,
    limit: int = 20,
    offset: int = 0,
    search_term: str | None = None,
) -> list[dict[str, Any]]:
    """List available conversations through a conversation manager."""
    return conversation_manager.list_conversations(
        limit=limit,
        offset=offset,
        search_term=search_term,
    )


def resolve_conversation_manager(
    owner: Any,
    agent_id: str | None,
    *,
    log: Any,
) -> Any:
    """Resolve the conversation manager for an optional agent-scoped request."""

    conversation_manager = owner.conversation_manager
    engine = getattr(owner, "engine", None)
    if engine:
        try:
            candidate_cm = engine.get_conversation_manager(agent_id)
            if candidate_cm is not None:
                conversation_manager = candidate_cm
        except Exception as engine_err:
            log.warning(
                "Engine conversation manager lookup failed for agent '%s': %s",
                agent_id,
                engine_err,
            )
    elif agent_id:
        try:
            if hasattr(conversation_manager, "set_current_agent"):
                conversation_manager.set_current_agent(agent_id)
        except Exception as agent_err:
            log.warning(
                "Failed to activate agent '%s' on ConversationManager: %s",
                agent_id,
                agent_err,
            )
    return conversation_manager


def _current_conversation_session_id(conversation_manager: Any) -> str | None:
    return getattr(
        getattr(
            getattr(conversation_manager, "conversation", None),
            "session",
            None,
        ),
        "id",
        None,
    )


def load_process_conversation(
    conversation_manager: Any,
    conversation_id: str,
    *,
    log: Any,
) -> ConversationLoadResult:
    """Load a process conversation through scoped conversation or manager."""

    scoped_conversation = getattr(conversation_manager, "conversation", None)
    via = "conversation"
    if scoped_conversation is not None and hasattr(scoped_conversation, "load"):
        ok = bool(scoped_conversation.load(conversation_id))
    else:
        via = "manager"
        ok = bool(conversation_manager.load(conversation_id))

    if not ok:
        log.warning("Failed to load conversation %s", conversation_id)

    return ConversationLoadResult(
        via=via,
        ok=ok,
        scoped_session_id=_current_conversation_session_id(conversation_manager),
    )


def load_process_context_files(
    conversation_manager: Any,
    context_files: list[str] | None,
) -> int:
    """Load process context files through scoped conversation or manager."""

    if not context_files:
        return 0

    scoped_conversation = getattr(conversation_manager, "conversation", None)
    for file_path in context_files:
        if scoped_conversation is not None and hasattr(
            scoped_conversation,
            "load_context_file",
        ):
            scoped_conversation.load_context_file(file_path)
        else:
            conversation_manager.load_context_file(file_path)
    return len(context_files)


def session_payload(session: Any) -> dict[str, Any]:
    """Serialize a conversation session into the legacy core API payload."""
    return {
        "id": session.id,
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "timestamp": message.timestamp,
                "agent_id": message.agent_id,
                "recipient_id": message.recipient_id,
                "message_type": message.message_type,
                "metadata": message.metadata,
            }
            for message in session.messages
        ],
        "created_at": session.created_at,
        "last_active": session.last_active,
        "metadata": session.metadata,
    }


def get_conversation(
    conversation_manager: Any,
    conversation_id: str,
) -> dict[str, Any] | None:
    """Load and serialize one conversation by ID."""
    if not conversation_manager.load(conversation_id):
        return None

    session = conversation_manager.get_current_session()
    if not session:
        return None

    return session_payload(session)


def get_conversation_history(
    conversation_manager: Any,
    conversation_id: str,
    *,
    include_system: bool = True,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return serialized conversation history from the manager."""
    return conversation_manager.get_conversation_history(
        conversation_id,
        include_system=include_system,
        limit=limit,
    )


def create_conversation(conversation_manager: Any) -> str:
    """Create a new conversation through the manager."""
    return conversation_manager.create_new_conversation()


def delete_conversation(conversation_manager: Any, conversation_id: str) -> bool:
    """Delete a conversation through the manager."""
    return conversation_manager.delete_conversation(conversation_id)


def get_conversation_stats(conversation_manager: Any) -> dict[str, Any]:
    """Return conversation/session statistics from the manager."""
    return conversation_manager.get_session_stats()
