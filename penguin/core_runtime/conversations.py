"""Conversation facade helpers for :mod:`penguin.core`."""

from __future__ import annotations

from typing import Any

__all__ = [
    "create_conversation",
    "delete_conversation",
    "get_conversation",
    "get_conversation_history",
    "get_conversation_stats",
    "list_conversations",
    "session_payload",
]


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
