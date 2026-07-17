from __future__ import annotations

import pytest

from penguin.web.services.chat_terminal import (
    build_continuation_prompt,
    normalize_chat_terminal_result,
)


@pytest.mark.parametrize(
    ("process_result", "state", "completed", "recoverable", "primary_action"),
    [
        ({"status": "completed"}, "completed", True, False, None),
        ({"status": "implicit_completion"}, "completed", True, False, None),
        ({"status": "max_iterations"}, "max_iterations", False, True, "resume"),
        (
            {"status": "provider_recoverable_error", "recoverable": True},
            "provider_exhausted",
            False,
            True,
            "retry",
        ),
        (
            {"status": "repeated_empty_tool_only_iterations"},
            "stalled",
            False,
            True,
            "resume",
        ),
        (
            {"status": "llm_empty_response_error", "recoverable": True},
            "stalled",
            False,
            True,
            "resume",
        ),
        ({"status": "stopped", "aborted": True}, "aborted", False, True, "resume"),
        ({"status": "stopped"}, "stopped", False, True, "resume"),
        ({"status": "cancelled"}, "cancelled", False, True, "resume"),
        ({"status": "provider_error"}, "failed", False, False, None),
        ({"status": "error"}, "failed", False, False, None),
    ],
)
def test_normalize_chat_terminal_result_classifies_terminal_truth(
    process_result: dict[str, object],
    state: str,
    completed: bool,
    recoverable: bool,
    primary_action: str | None,
) -> None:
    result = normalize_chat_terminal_result(
        process_result,
        session_id="session-1",
        request_id="request-1",
        continuation_generation=4,
    )

    assert result["state"] == state
    assert result["terminal_reason"] == process_result["status"]
    assert result["completed"] is completed
    assert result["recoverable"] is recoverable
    if primary_action is None:
        assert result["continuation"] is None
    else:
        continuation = result["continuation"]
        assert continuation["available"] is True
        assert continuation["action"] == primary_action
        assert continuation["request"]["session_id"] == "session-1"
        assert continuation["request"]["continuation"] == {
            "action": primary_action,
            "previous_status": process_result["status"],
            "request_id": "request-1",
            "generation": 4,
        }


def test_normalize_chat_terminal_result_preserves_partial_and_error_details() -> None:
    error = {
        "code": "provider_timeout",
        "message": "stream stalled",
        "provider_data": {"partial_output": "actual streamed partial"},
    }
    result = normalize_chat_terminal_result(
        {
            "assistant_response": "partial answer",
            "action_results": [{"action": "read_file"}],
            "iterations": 7,
            "status": "provider_recoverable_error",
            "recoverable": True,
            "error": error,
        },
        session_id="session-1",
    )

    assert result["response"] == "partial answer"
    assert result["partial_response"] == "actual streamed partial"
    assert result["action_count"] == 1
    assert result["iterations"] == 7
    assert result["error"] is error
    assert result["aborted"] is False
    assert result["cancelled"] is False


def test_legacy_chat_terminal_defaults_to_completed() -> None:
    result = normalize_chat_terminal_result(
        {"assistant_response": "done", "action_results": []}
    )

    assert result["status"] == "completed"
    assert result["terminal_reason"] == "completed"
    assert result["completed"] is True
    assert result["partial_response"] == ""


@pytest.mark.parametrize(
    "process_result",
    [
        {},
        {"status": "completed", "error": "boom"},
        {"status": "completed", "completed": False},
        {"status": "completed", "aborted": True},
        {"status": "cancelled", "aborted": True},
        {"status": "aborted", "cancelled": True},
        {"status": "stopped", "aborted": True, "cancelled": True},
    ],
)
def test_empty_or_contradictory_process_results_fail_closed(
    process_result: dict[str, object],
) -> None:
    result = normalize_chat_terminal_result(process_result)

    assert result["status"] == "terminal_contract_error"
    assert result["state"] == "failed"
    assert result["completed"] is False
    assert result["recoverable"] is False
    assert result["continuation"] is None


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ("resume", "max_iterations"),
        ("resume", "repeated_empty_tool_only_iterations"),
        ("resume", "cancelled"),
        ("retry", "provider_recoverable_error"),
    ],
)
def test_build_continuation_prompt_is_structured_and_status_specific(
    action: str,
    status: str,
) -> None:
    prompt = build_continuation_prompt(action=action, previous_status=status)

    assert "durable conversation state" in prompt
    assert status in prompt
    assert "Do not repeat completed work" in prompt


@pytest.mark.parametrize(
    ("action", "status"),
    [
        ("retry", "max_iterations"),
        ("resume", "provider_error"),
        ("unknown", "max_iterations"),
    ],
)
def test_build_continuation_prompt_rejects_unsafe_or_mismatched_actions(
    action: str,
    status: str,
) -> None:
    with pytest.raises(ValueError):
        build_continuation_prompt(action=action, previous_status=status)
