"""Conversation service helpers for route handlers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def list_conversations_payload(core: Any) -> dict[str, Any]:
    """Build response payload for conversation listing."""
    conversations = core.list_conversations()
    return {"conversations": conversations}


def get_conversation_payload(core: Any, conversation_id: str) -> dict[str, Any]:
    """Build response payload for a single conversation."""
    conversation = core.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(
            status_code=404, detail=f"Conversation {conversation_id} not found"
        )
    return conversation


def create_conversation_payload(core: Any) -> dict[str, str]:
    """Build response payload for conversation creation."""
    conversation_id = core.create_conversation()
    return {"conversation_id": conversation_id}
