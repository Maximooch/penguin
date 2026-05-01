from pathlib import Path

from penguin.system.context_window import ContextWindowManager
from penguin.system.conversation import ConversationSystem
from penguin.system.state import Message, MessageCategory, Session


def test_skill_context_message_uses_context_category() -> None:
    conversation = ConversationSystem()

    message = conversation.add_context(
        '<skill_content name="demo">Instructions</skill_content>',
        source="skill:demo",
    )
    message.metadata.update({"type": "skill_activation", "skill_name": "demo"})

    assert message.category == MessageCategory.CONTEXT
    assert message.metadata["skill_name"] == "demo"


def test_context_truncation_can_trim_old_skill_context_messages() -> None:
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_window_tokens = 120
    cwm._initialize_token_budgets()
    session = Session()
    session.messages = [
        Message(
            role="system",
            content="old skill instructions " * 5,
            category=MessageCategory.CONTEXT,
            metadata={"type": "skill_activation", "skill_name": "old"},
            tokens=110,
            timestamp="2026-01-01T00:00:00",
        ),
        Message(
            role="system",
            content="new skill instructions",
            category=MessageCategory.CONTEXT,
            metadata={"type": "skill_activation", "skill_name": "new"},
            tokens=10,
            timestamp="2026-01-02T00:00:00",
        ),
    ]

    trimmed = cwm.process_session(session)

    assert [msg.metadata.get("skill_name") for msg in trimmed.messages] == ["new"]
