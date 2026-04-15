from __future__ import annotations

from types import SimpleNamespace

from penguin.system.conversation import ConversationSystem
from penguin.system.state import Message, MessageCategory, Session


def test_add_action_result_preserves_explicit_tool_call_id() -> None:
    session = Session()
    assistant = Message(
        role="assistant",
        content="Running a tiny Python function now.",
        category=MessageCategory.DIALOG,
        id="msg_assistant",
        timestamp="2026-04-10T12:00:00",
        metadata={},
        tokens=0,
    )
    session.messages.append(assistant)

    conversation = ConversationSystem(
        session_manager=SimpleNamespace(
            current_session=session,
            mark_session_modified=lambda _session_id: None,
            check_session_boundary=lambda _session: False,
        )
    )
    conversation.session = session

    tool_message = conversation.add_action_result(
        "code_execution",
        "13\nRESULT=13",
        tool_call_id="call_123",
        tool_arguments='{"code":"print(13)"}',
    )

    assert tool_message.metadata["tool_call_id"] == "call_123"
    assert assistant.metadata["tool_calls"] == [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "code_execution",
                "arguments": '{"code":"print(13)"}',
            },
        }
    ]
