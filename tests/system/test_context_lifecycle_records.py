from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from penguin.system.context_window import ContextWindowManager
from penguin.system.state import Message, MessageCategory, Session


def test_context_snapshot_omits_message_content_by_default(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ordinary INFO telemetry contains sizes and categories, not prompts."""

    sentinel = "CWM-PRIVATE-CONTENT-NEVER-LOG"
    monkeypatch.delenv("PENGUIN_LOG_CONTEXT_PREVIEWS", raising=False)
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    session = Session(
        messages=[
            Message(
                role="user",
                content=sentinel,
                category=MessageCategory.DIALOG,
                tokens=len(sentinel),
            )
        ]
    )

    with caplog.at_level("INFO", logger="penguin.system.context_window"):
        cwm.process_session(session)

    encoded = "\n".join(record.getMessage() for record in caplog.records)
    assert "cwm.snapshot" in encoded
    assert sentinel not in encoded
    assert "'chars':" in encoded


def test_context_snapshot_preview_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Operators can deliberately opt into bounded context previews."""

    sentinel = "CWM-EXPLICIT-PREVIEW"
    monkeypatch.setenv("PENGUIN_LOG_CONTEXT_PREVIEWS", "true")
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    session = Session(
        messages=[
            Message(
                role="user",
                content=sentinel,
                category=MessageCategory.DIALOG,
                tokens=len(sentinel),
            )
        ]
    )

    with caplog.at_level("INFO", logger="penguin.system.context_window"):
        cwm.process_session(session)

    assert sentinel in "\n".join(record.getMessage() for record in caplog.records)


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


def test_context_window_trim_can_remove_over_budget_non_primary_categories() -> None:
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_window_tokens = 100

    for category in (
        MessageCategory.ERROR,
        MessageCategory.INTERNAL,
        MessageCategory.UNKNOWN,
    ):
        cwm._budgets[category].max_category_tokens = 1
        message = Message(
            role="system",
            content=f"{category.name} payload over budget",
            category=category,
        )
        session = Session(messages=[message])

        trimmed = cwm.trim_session(session)

        assert message not in trimmed.messages


def test_image_trimming_counts_image_parts_not_messages(tmp_path: Path) -> None:
    cwm = ContextWindowManager(token_counter=lambda content: len(str(content)))
    cwm.max_context_images = 2

    session = Session()
    old_message = Message(
        role="user",
        content=[
            {"type": "text", "text": "old"},
            {"type": "image_url", "image_path": str(tmp_path / "one.png")},
            {"type": "image_url", "image_path": str(tmp_path / "two.png")},
        ],
        category=MessageCategory.DIALOG,
    )
    new_message = Message(
        role="user",
        content=[
            {"type": "text", "text": "new"},
            {"type": "image_url", "image_path": str(tmp_path / "three.png")},
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


def test_default_token_counter_treats_image_path_parts_as_images(
    tmp_path: Path,
) -> None:
    cwm = ContextWindowManager()

    assert cwm._default_token_counter(
        [{"image_path": str(tmp_path / "image.png")}]
    ) == 4000
