from __future__ import annotations

from penguin.system.context_window import ContextWindowManager
from penguin.system.state import Message, MessageCategory, Session


def test_context_window_trim_preserves_llm_request_lifecycle_records() -> None:
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_window_tokens = 1

    session = Session()
    session.add_message(
        Message(
            role="user",
            content="this message is intentionally over budget",
            category=MessageCategory.DIALOG,
        )
    )
    session.add_llm_request_lifecycle(
        {
            "request_id": "req-cwm-1",
            "provider": "openai",
            "model": "gpt-test",
            "status": "completed",
        }
    )
    session.add_tool_call_record(
        {
            "record_type": "tool_call",
            "call_id": "call-cwm-1",
            "name": "read_file",
            "source": "responses",
            "arguments_hash": "args-hash",
        }
    )
    session.add_tool_result_record(
        {
            "record_type": "tool_result",
            "call_id": "call-cwm-1",
            "name": "read_file",
            "status": "completed",
            "output_hash": "out-hash",
        }
    )

    trimmed = cwm.trim_session(session)

    assert trimmed.llm_request_lifecycles == session.llm_request_lifecycles
    assert trimmed.tool_call_records == session.tool_call_records
    assert trimmed.tool_result_records == session.tool_result_records


def test_context_window_trim_preserves_non_primary_categories() -> None:
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_window_tokens = 1

    session = Session()
    error_message = Message(
        role="system",
        content="error payload",
        category=MessageCategory.ERROR,
    )
    unknown_message = Message(
        role="system",
        content="unknown payload",
        category=MessageCategory.UNKNOWN,
    )
    session.add_message(error_message)
    session.add_message(unknown_message)

    trimmed = cwm.trim_session(session)

    assert error_message in trimmed.messages
    assert unknown_message in trimmed.messages


def test_image_trimming_counts_image_parts_not_messages() -> None:
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_images = 2

    session = Session()
    old_message = Message(
        role="user",
        content=[
            {"type": "text", "text": "old"},
            {"type": "image_url", "image_path": "/tmp/one.png"},
            {"type": "image_url", "image_path": "/tmp/two.png"},
        ],
        category=MessageCategory.DIALOG,
    )
    new_message = Message(
        role="user",
        content=[
            {"type": "text", "text": "new"},
            {"type": "image_url", "image_path": "/tmp/three.png"},
        ],
        category=MessageCategory.DIALOG,
    )
    session.add_message(old_message)
    session.add_message(new_message)

    trimmed = cwm._handle_image_trimming(session)

    stats = cwm.analyze_session(trimmed)
    assert stats["image_count"] == 1
    assert "[Image removed to save tokens]" in str(trimmed.messages[0].content)
    assert trimmed.messages[1] is new_message
