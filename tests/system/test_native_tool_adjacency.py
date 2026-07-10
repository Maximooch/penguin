"""Native-tool history integrity tests.

These tests cover the narrow current-PR exception: a native assistant tool
declaration and its contiguous tool results must survive as one replayable
unit, or be removed together.  They intentionally do not introduce a broader
context-window policy.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from penguin.system.context_window import ContextWindowManager
from penguin.system.conversation import ConversationSystem
from penguin.system.native_tool_history import sanitize_native_tool_messages
from penguin.system.state import Message, MessageCategory, Session


def _conversation(session: Session, *, cwm: Any = None) -> ConversationSystem:
    """Build a minimal conversation around an explicit session."""

    conversation = ConversationSystem(
        context_window_manager=cwm,
        session_manager=SimpleNamespace(
            current_session=session,
            mark_session_modified=lambda _session_id: None,
            check_session_boundary=lambda _session: False,
        ),
    )
    conversation.session = session
    return conversation


def test_action_result_never_backscans_a_historic_assistant() -> None:
    """A later result must not attach native metadata to an older turn."""

    session = Session()
    historic_assistant = Message(
        role="assistant",
        content="This is an earlier answer.",
        category=MessageCategory.DIALOG,
    )
    session.add_message(historic_assistant)
    session.add_message(
        Message(role="user", content="A newer turn", category=MessageCategory.DIALOG)
    )
    conversation = _conversation(session)

    conversation.add_action_result(
        "read_file",
        "README contents",
        tool_call_id="call_current",
        tool_arguments='{"path":"README.md"}',
    )

    assert "tool_calls" not in historic_assistant.metadata
    assert [message.role for message in session.messages] == [
        "assistant",
        "user",
        "assistant",
        "tool",
    ]
    declaration, result = session.messages[-2:]
    assert declaration.content == ""
    assert declaration.metadata["tool_calls"][0]["id"] == "call_current"
    assert result.metadata["tool_call_id"] == "call_current"


def test_native_tool_batch_is_atomic_for_zero_text_multi_tool_turn() -> None:
    """Tool-only streaming turns get a fresh empty assistant declaration."""

    session = Session()
    conversation = _conversation(session)

    appended = conversation.append_native_tool_batch(
        tool_calls=[
            {
                "id": "call_one",
                "name": "read_file",
                "arguments": '{"path":"README.md"}',
            },
            {
                "id": "call_two",
                "name": "list_directory",
                "arguments": '{"path":"."}',
            },
        ],
        action_results=[
            {
                "tool_call_id": "call_one",
                "action": "read_file",
                "result": "README",
                "status": "completed",
                "tool_arguments": '{"path":"README.md"}',
            },
            {
                "tool_call_id": "call_two",
                "action": "list_directory",
                "result": "penguin",
                "status": "completed",
                "tool_arguments": '{"path":"."}',
            },
        ],
    )

    assert [message.role for message in appended] == ["assistant", "tool", "tool"]
    assert appended[0].content == ""
    assert [tool_call["id"] for tool_call in appended[0].metadata["tool_calls"]] == [
        "call_one",
        "call_two",
    ]
    assert [message.metadata["tool_call_id"] for message in appended[1:]] == [
        "call_one",
        "call_two",
    ]


def test_sanitizer_fails_closed_for_interleaved_and_duplicate_native_units() -> None:
    """Interleaving and duplicate call ids can never reach a provider replay."""

    sanitized = sanitize_native_tool_messages(
        [
            {
                "role": "assistant",
                "content": "I will run this.",
                "tool_calls": [
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {"role": "user", "content": "interleaved"},
            {
                "role": "tool",
                "tool_call_id": "call_bad",
                "content": "should not replay",
            },
            {
                "role": "assistant",
                "content": "duplicate id",
                "tool_calls": [
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_bad",
                "content": "also should not replay",
            },
        ]
    )

    assert [message["role"] for message in sanitized] == [
        "assistant",
        "user",
        "assistant",
    ]
    assert all("tool_calls" not in message for message in sanitized)


def test_cwm_pressure_drops_a_split_native_batch_as_one_unit() -> None:
    """Category trimming may remove a full native unit, never only its results."""

    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_window_tokens = 1_000
    cwm._budgets[MessageCategory.SYSTEM_OUTPUT].max_category_tokens = 1
    session = Session(
        messages=[
            Message(
                role="assistant",
                content="",
                category=MessageCategory.DIALOG,
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_one",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        },
                        {
                            "id": "call_two",
                            "type": "function",
                            "function": {
                                "name": "list_directory",
                                "arguments": "{}",
                            },
                        },
                    ]
                },
            ),
            Message(
                role="tool",
                content="long first result",
                category=MessageCategory.SYSTEM_OUTPUT,
                metadata={"tool_call_id": "call_one"},
            ),
            Message(
                role="tool",
                content="long second result",
                category=MessageCategory.SYSTEM_OUTPUT,
                metadata={"tool_call_id": "call_two"},
            ),
        ]
    )

    processed = cwm.process_session(session)

    assert [message.role for message in processed.messages] == ["assistant"]
    assert "tool_calls" not in processed.messages[0].metadata


def test_formatted_messages_preserve_native_order_when_timestamps_match() -> None:
    """Category grouping must not reorder valid raw units with equal timestamps."""

    timestamp = "2026-01-01T00:00:00"
    session = Session(
        messages=[
            Message(
                role="assistant",
                content="",
                category=MessageCategory.DIALOG,
                timestamp=timestamp,
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_one",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ]
                },
            ),
            Message(
                role="tool",
                content="one",
                category=MessageCategory.SYSTEM_OUTPUT,
                timestamp=timestamp,
                metadata={"tool_call_id": "call_one", "action_type": "read_file"},
            ),
            Message(
                role="assistant",
                content="",
                category=MessageCategory.DIALOG,
                timestamp=timestamp,
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_two",
                            "type": "function",
                            "function": {
                                "name": "list_directory",
                                "arguments": "{}",
                            },
                        }
                    ]
                },
            ),
            Message(
                role="tool",
                content="two",
                category=MessageCategory.SYSTEM_OUTPUT,
                timestamp=timestamp,
                metadata={
                    "tool_call_id": "call_two",
                    "action_type": "list_directory",
                },
            ),
        ]
    )

    formatted = _conversation(session).get_formatted_messages()

    assert [message["role"] for message in formatted] == [
        "assistant",
        "tool",
        "assistant",
        "tool",
    ]
    assert [
        message["tool_call_id"] for message in formatted if message["role"] == "tool"
    ] == ["call_one", "call_two"]


def test_cwm_usage_excludes_orphan_removed_after_category_trimming() -> None:
    """CWM diagnostics must not retain tokens from fail-closed tool removals."""

    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_window_tokens = 1_000
    cwm._budgets[MessageCategory.DIALOG].max_category_tokens = 1
    cwm._budgets[MessageCategory.SYSTEM_OUTPUT].max_category_tokens = 500
    session = Session(
        messages=[
            Message(
                role="assistant",
                content="x" * 100,
                category=MessageCategory.DIALOG,
                tokens=100,
                metadata={
                    "tool_calls": [
                        {
                            "id": "call_trimmed",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"},
                        }
                    ]
                },
            ),
            Message(
                role="tool",
                content="result",
                category=MessageCategory.SYSTEM_OUTPUT,
                tokens=10,
                metadata={"tool_call_id": "call_trimmed"},
            ),
        ]
    )

    processed = cwm.process_session(session)

    assert processed.messages == []
    assert cwm.get_token_usage()["total"] == 0
