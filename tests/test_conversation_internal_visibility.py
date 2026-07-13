from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import penguin.system.conversation as conversation_module
from penguin.system.conversation import ConversationSystem
from penguin.system.conversation_manager import ConversationManager
from penguin.system.state import MessageCategory


@pytest.mark.asyncio
async def test_internal_prompt_is_private_at_message_insertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = SimpleNamespace(send=AsyncMock())
    monkeypatch.setattr(
        conversation_module.MessageBus,
        "get_instance",
        lambda: bus,
    )
    conversation = ConversationSystem()

    conversation.prepare_conversation(
        "Internal category prompt",
        category=MessageCategory.INTERNAL,
        metadata={"internal_prompt": True},
    )
    conversation.prepare_conversation(
        "Metadata-private prompt",
        category=MessageCategory.DIALOG,
        metadata={"visibility": "internal"},
    )
    conversation.add_message("user", "Visible user message")
    await asyncio.sleep(0)

    internal_category_message = conversation.session.messages[0]
    metadata_private_message = conversation.session.messages[1]
    assert internal_category_message.category is MessageCategory.INTERNAL
    assert metadata_private_message.category is MessageCategory.DIALOG
    assert metadata_private_message.metadata["visibility"] == "internal"
    bus.send.assert_awaited_once()
    published = bus.send.await_args.args[0]
    assert published.content == "Visible user message"


def test_human_history_excludes_category_and_metadata_private_messages() -> None:
    """Human history omits either independent marker; model context stays whole."""

    conversation = ConversationSystem()
    conversation.prepare_conversation(
        "Internal category prompt",
        category=MessageCategory.INTERNAL,
    )
    conversation.prepare_conversation(
        "Metadata-private prompt",
        category=MessageCategory.DIALOG,
        metadata={"visibility": "internal"},
    )
    conversation.add_message("user", "Visible user message")

    assert conversation.get_human_history() == [
        {"role": "user", "content": "Visible user message"}
    ]
    formatted_content = [
        message["content"] for message in conversation.get_formatted_messages()
    ]
    assert formatted_content == [
        "Internal category prompt",
        "Metadata-private prompt",
        "Visible user message",
    ]

    manager = ConversationManager.__new__(ConversationManager)
    manager.session_manager = SimpleNamespace(
        load_session=lambda _session_id: conversation.session
    )
    history = manager.get_conversation_history("session")

    assert [entry["content"] for entry in history] == ["Visible user message"]
