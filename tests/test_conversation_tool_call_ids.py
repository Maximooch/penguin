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
    assert session.tool_call_records[0]["call_id"] == "call_123"
    assert session.tool_result_records[0]["call_id"] == "call_123"


def test_formatted_tool_message_can_repair_replay_metadata_from_records() -> None:
    session = Session()
    session.add_tool_call_record(
        {
            "record_type": "tool_call",
            "call_id": "call_trimmed",
            "name": "read_file",
            "source": "responses",
            "arguments": {"path": "README.md", "max_lines": 20},
            "arguments_hash": "hash",
        }
    )
    session.add_tool_result_record(
        {
            "record_type": "tool_result",
            "call_id": "call_trimmed",
            "name": "read_file",
            "status": "cancelled",
            "output_hash": "output-hash",
        }
    )
    session.add_message(
        Message(
            role="tool",
            content="cancelled while tool was running",
            category=MessageCategory.SYSTEM_OUTPUT,
            metadata={"tool_call_id": "call_trimmed"},
        )
    )

    conversation = ConversationSystem(
        session_manager=SimpleNamespace(
            current_session=session,
            mark_session_modified=lambda _session_id: None,
            check_session_boundary=lambda _session: False,
        )
    )
    conversation.session = session

    formatted = conversation.get_formatted_messages()

    assert formatted[-1] == {
        "role": "tool",
        "tool_call_id": "call_trimmed",
        "content": "cancelled while tool was running",
        "name": "read_file",
        "tool_arguments": '{"max_lines": 20, "path": "README.md"}',
        "status": "cancelled",
    }
