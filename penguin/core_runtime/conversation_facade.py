"""Conversation compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

from typing import Any

from . import conversations as core_conversations

__all__ = ["ConversationCoreFacade"]


class ConversationCoreFacade:
    """Compatibility methods for conversation CRUD and history helpers."""

    def list_conversations(
        self,
        limit: int = 20,
        offset: int = 0,
        search_term: str | None = None,
    ) -> list[dict[str, Any]]:
        """List available conversations."""
        return core_conversations.list_conversations(
            self.conversation_manager,
            limit=limit,
            offset=offset,
            search_term=search_term,
        )

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Get a specific conversation by ID."""
        return core_conversations.get_conversation(
            self.conversation_manager,
            conversation_id,
        )

    def get_conversation_history(
        self,
        conversation_id: str,
        *,
        include_system: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return serialized conversation history."""
        return core_conversations.get_conversation_history(
            self.conversation_manager,
            conversation_id,
            include_system=include_system,
            limit=limit,
        )

    def create_conversation(self) -> str:
        """Create a new conversation."""
        return core_conversations.create_conversation(self.conversation_manager)

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation."""
        return core_conversations.delete_conversation(
            self.conversation_manager,
            conversation_id,
        )

    def get_conversation_stats(self) -> dict[str, Any]:
        """Get statistics about conversations."""
        return core_conversations.get_conversation_stats(self.conversation_manager)
