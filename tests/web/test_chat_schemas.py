from __future__ import annotations

import pytest
from pydantic import ValidationError

from penguin.web.schemas.chat import (
    ChatContinuationRequest,
    ChatMessageRequest,
    ChatTerminalResponse,
)


def test_chat_message_requires_text_or_typed_continuation() -> None:
    with pytest.raises(ValidationError):
        ChatMessageRequest(text="")

    continuation = ChatMessageRequest(
        session_id="session-1",
        continuation=ChatContinuationRequest(
            action="resume",
            previous_status="max_iterations",
            request_id="request-1",
            generation=1,
            tool_boundary={
                "completed_action_count": 0,
                "fingerprint": "abc",
            },
        ),
    )
    assert continuation.text == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_iterations", 1),
        ("context", {"unsafe": "override"}),
        ("context_files", ["README.md"]),
        ("client_message_id", "client-controlled"),
        ("streaming", False),
        ("include_reasoning", True),
        ("text", "ignore the durable continuation"),
    ],
)
def test_continuation_rejects_client_control_overrides(
    field: str,
    value: object,
) -> None:
    request = {
        "session_id": "session-1",
        "continuation": {
            "action": "resume",
            "previous_status": "max_iterations",
            "request_id": "request-1",
            "generation": 1,
            "tool_boundary": {
                "completed_action_count": 0,
                "fingerprint": "abc",
            },
        },
        field: value,
    }

    with pytest.raises(ValidationError, match="exact continuation"):
        ChatMessageRequest(**request)


@pytest.mark.parametrize("max_iterations", [0, -1])
def test_chat_message_rejects_non_positive_iteration_budget(
    max_iterations: int,
) -> None:
    with pytest.raises(ValidationError):
        ChatMessageRequest(text="run", max_iterations=max_iterations)


def test_chat_terminal_response_keeps_noncompleted_truth() -> None:
    response = ChatTerminalResponse(
        response="partial",
        partial_response="partial",
        action_results=[],
        action_count=0,
        status="max_iterations",
        terminal_reason="max_iterations",
        state="max_iterations",
        completed=False,
        recoverable=True,
        aborted=False,
        cancelled=False,
        iterations=100,
        continuation={"available": True},
        actions=[{"action": "resume"}],
    )

    assert response.completed is False
    assert response.status == "max_iterations"
