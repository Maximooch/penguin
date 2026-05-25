"""Tests for OpenCode transcript persistence helpers."""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings, strategies as st

from penguin.core_runtime import opencode_transcript


def _assistant_info(message_id: str, session_id: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "sessionID": session_id,
        "role": "assistant",
        "modelID": "test-model",
        "providerID": "test-provider",
    }


def _part_event(
    *,
    message_id: str = "msg_1",
    part_id: str = "part_1",
    session_id: str = "session_1",
    part_type: str = "text",
    text: str = "hello",
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    part: dict[str, Any] = {
        "id": part_id,
        "sessionID": session_id,
        "messageID": message_id,
        "type": part_type,
        "text": text,
    }
    if state is not None:
        part["state"] = state
    return {"part": part}


def test_resolve_event_session_id_filters_non_transcript_events() -> None:
    assert (
        opencode_transcript.resolve_event_session_id(
            "permission.updated",
            {"sessionID": "session_1"},
        )
        is None
    )
    assert (
        opencode_transcript.resolve_event_session_id(
            "message.updated",
            {"sessionID": "unknown"},
        )
        is None
    )
    assert (
        opencode_transcript.resolve_event_session_id(
            "message.part.updated",
            {"part": {"sessionID": " session_2 "}},
        )
        == "session_2"
    )


def test_apply_message_updated_persists_message_info_and_save_flag() -> None:
    metadata: dict[str, Any] = {}

    result = opencode_transcript.apply_transcript_event(
        metadata=metadata,
        event_type="message.updated",
        properties={
            "id": "msg_1",
            "sessionID": "session_1",
            "role": "assistant",
            "time": {"completed": 123},
        },
        session_id="session_1",
        assistant_info_factory=_assistant_info,
    )

    assert result.mark_modified is True
    assert result.should_save is True
    transcript = metadata[opencode_transcript.TRANSCRIPT_KEY]
    assert transcript["order"] == ["msg_1"]
    assert transcript["messages"]["msg_1"]["info"]["role"] == "assistant"
    assert transcript["messages"]["msg_1"]["parts"] == {}
    assert transcript["messages"]["msg_1"]["part_order"] == []


def test_apply_part_updated_synthesizes_part_first_message_info() -> None:
    metadata: dict[str, Any] = {}

    result = opencode_transcript.apply_transcript_event(
        metadata=metadata,
        event_type="message.part.updated",
        properties=_part_event(part_id="part_text", text="streamed"),
        session_id="session_1",
        assistant_info_factory=_assistant_info,
    )

    assert result.mark_modified is True
    assert result.should_save is False
    transcript = metadata[opencode_transcript.TRANSCRIPT_KEY]
    message = transcript["messages"]["msg_1"]
    assert transcript["order"] == ["msg_1"]
    assert message["info"]["modelID"] == "test-model"
    assert message["part_order"] == ["part_text"]
    assert message["parts"]["part_text"]["text"] == "streamed"


def test_apply_tool_part_updated_requests_save_when_terminal() -> None:
    metadata: dict[str, Any] = {}

    result = opencode_transcript.apply_transcript_event(
        metadata=metadata,
        event_type="message.part.updated",
        properties=_part_event(
            part_id="part_tool",
            part_type="tool",
            state={"status": "completed"},
        ),
        session_id="session_1",
        assistant_info_factory=_assistant_info,
    )

    assert result.mark_modified is True
    assert result.should_save is True


def test_apply_remove_events_keep_order_consistent() -> None:
    metadata: dict[str, Any] = {}
    for part_id in ("part_a", "part_b"):
        opencode_transcript.apply_transcript_event(
            metadata=metadata,
            event_type="message.part.updated",
            properties=_part_event(part_id=part_id),
            session_id="session_1",
            assistant_info_factory=_assistant_info,
        )

    part_result = opencode_transcript.apply_transcript_event(
        metadata=metadata,
        event_type="message.part.removed",
        properties={"messageID": "msg_1", "partID": "part_a"},
        session_id="session_1",
        assistant_info_factory=_assistant_info,
    )
    message = metadata[opencode_transcript.TRANSCRIPT_KEY]["messages"]["msg_1"]
    assert part_result.mark_modified is True
    assert part_result.should_save is False
    assert message["part_order"] == ["part_b"]
    assert "part_a" not in message["parts"]

    message_result = opencode_transcript.apply_transcript_event(
        metadata=metadata,
        event_type="message.removed",
        properties={"messageID": "msg_1"},
        session_id="session_1",
        assistant_info_factory=_assistant_info,
    )
    transcript = metadata[opencode_transcript.TRANSCRIPT_KEY]
    assert message_result.mark_modified is True
    assert message_result.should_save is False
    assert transcript["order"] == []
    assert transcript["messages"] == {}


def test_apply_transcript_event_ignores_invalid_metadata() -> None:
    result = opencode_transcript.apply_transcript_event(
        metadata=None,
        event_type="message.updated",
        properties={"id": "msg_1", "sessionID": "session_1"},
        session_id="session_1",
        assistant_info_factory=_assistant_info,
    )

    assert result.mark_modified is False
    assert result.should_save is False


@settings(max_examples=25)
@given(
    part_ids=st.lists(
        st.text(
            alphabet=st.characters(min_codepoint=97, max_codepoint=122),
            min_size=1,
            max_size=6,
        ),
        min_size=1,
        max_size=20,
    )
)
def test_part_updates_preserve_unique_order_for_repeated_ids(
    part_ids: list[str],
) -> None:
    metadata: dict[str, Any] = {}

    for index, part_id in enumerate(part_ids):
        opencode_transcript.apply_transcript_event(
            metadata=metadata,
            event_type="message.part.updated",
            properties=_part_event(part_id=part_id, text=f"text-{index}"),
            session_id="session_1",
            assistant_info_factory=_assistant_info,
        )

    message = metadata[opencode_transcript.TRANSCRIPT_KEY]["messages"]["msg_1"]
    assert message["part_order"] == list(dict.fromkeys(part_ids))
    last_text_by_part = {
        part_id: f"text-{index}" for index, part_id in enumerate(part_ids)
    }
    for part_id in part_ids:
        assert message["parts"][part_id]["text"] == last_text_by_part[part_id]
