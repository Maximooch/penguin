from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import penguin.system.conversation as conversation_module
from penguin.system.conversation import ConversationSystem
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
        "Internal goal continuation",
        category=MessageCategory.INTERNAL,
        metadata={"internal_prompt": True, "visibility": "internal"},
    )
    conversation.add_message("user", "Visible user message")
    await asyncio.sleep(0)

    internal_message = conversation.session.messages[0]
    assert internal_message.category is MessageCategory.INTERNAL
    assert internal_message.metadata["visibility"] == "internal"
    bus.send.assert_awaited_once()
    published = bus.send.await_args.args[0]
    assert published.content == "Visible user message"
