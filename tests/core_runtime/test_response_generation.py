"""Tests for response generation helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime import response_generation


class _Conversation:
    def __init__(self) -> None:
        self.iteration_markers: list[tuple[int, int]] = []
        self.assistant_messages: list[str] = []
        self.formatted_messages = [
            {"role": "user", "content": "hello"},
            {"role": "system", "content": "Action executed: ok"},
        ]

    def add_iteration_marker(self, current: int, maximum: int) -> None:
        self.iteration_markers.append((current, maximum))

    def get_formatted_messages(self) -> list[dict[str, str]]:
        return list(self.formatted_messages)

    def add_assistant_message(self, message: str) -> None:
        self.assistant_messages.append(message)


class _ConversationManager:
    def __init__(self) -> None:
        self.conversation = _Conversation()
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


def _owner(*responses: Any) -> SimpleNamespace:
    return SimpleNamespace(
        conversation_manager=_ConversationManager(),
        api_client=SimpleNamespace(get_response=AsyncMock(side_effect=responses)),
    )


async def _process_actions(
    _owner: Any,
    assistant_response: str | None,
    *,
    log: Any,
) -> SimpleNamespace:
    return SimpleNamespace(
        actions=[{"response": assistant_response}],
        action_results=[{"ok": True}],
        exit_continuation=True,
    )


@pytest.mark.asyncio
async def test_get_response_adds_iteration_marker_and_builds_payload() -> None:
    owner = _owner("assistant text")

    response, exit_continuation = await response_generation.get_response(
        owner,
        current_iteration=2,
        max_iterations=5,
        stream_callback="callback",
        streaming=True,
        process_response_actions=_process_actions,
        sleep=AsyncMock(),
        log_error=lambda *_args, **_kwargs: None,
        log=SimpleNamespace(
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        ),
    )

    owner.api_client.get_response.assert_awaited_once_with(
        messages=owner.conversation_manager.conversation.formatted_messages,
        stream=True,
        stream_callback="callback",
    )
    assert owner.conversation_manager.conversation.iteration_markers == [(2, 5)]
    assert owner.conversation_manager.conversation.assistant_messages == [
        "assistant text"
    ]
    assert owner.conversation_manager.save_calls == 1
    assert response == {
        "assistant_response": "assistant text",
        "actions": [{"response": "assistant text"}],
        "action_results": [{"ok": True}],
        "metadata": {"iteration": 2, "max_iterations": 5},
    }
    assert exit_continuation is True


@pytest.mark.asyncio
async def test_get_response_retries_empty_responses_with_injected_sleep() -> None:
    owner = _owner("", "   ", "assistant text")
    sleep = AsyncMock()

    response, _exit_continuation = await response_generation.get_response(
        owner,
        current_iteration=None,
        max_iterations=None,
        stream_callback=None,
        streaming=False,
        process_response_actions=_process_actions,
        sleep=sleep,
        log_error=lambda *_args, **_kwargs: None,
        log=SimpleNamespace(
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        ),
    )

    assert owner.api_client.get_response.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [1, 2]
    assert response["assistant_response"] == "assistant text"


@pytest.mark.asyncio
async def test_get_response_uses_fallback_after_empty_response_retries() -> None:
    owner = _owner("", "", "")

    response, _exit_continuation = await response_generation.get_response(
        owner,
        current_iteration=None,
        max_iterations=None,
        stream_callback=None,
        streaming=False,
        process_response_actions=_process_actions,
        sleep=AsyncMock(),
        log_error=lambda *_args, **_kwargs: None,
        log=SimpleNamespace(
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        ),
    )

    assert response["assistant_response"] == (
        "I apologize, but I encountered an issue generating a response. "
        "Please try again."
    )
    assert owner.conversation_manager.conversation.assistant_messages == [
        response["assistant_response"]
    ]


@pytest.mark.asyncio
async def test_get_response_logs_and_shapes_errors() -> None:
    owner = _owner("assistant text")
    logged_errors: list[dict[str, Any]] = []

    async def failing_process_actions(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("action failure")

    def record_error(exc: BaseException, **kwargs: Any) -> None:
        logged_errors.append({"exc": exc, **kwargs})

    response, exit_continuation = await response_generation.get_response(
        owner,
        current_iteration=1,
        max_iterations=3,
        stream_callback=None,
        streaming=False,
        process_response_actions=failing_process_actions,
        sleep=AsyncMock(),
        log_error=record_error,
        log=SimpleNamespace(
            debug=lambda *_args, **_kwargs: None,
            warning=lambda *_args, **_kwargs: None,
            error=lambda *_args, **_kwargs: None,
        ),
    )

    assert response == {
        "assistant_response": "I apologize, but an error occurred: action failure",
        "action_results": [],
    }
    assert exit_continuation is False
    assert logged_errors[0]["context"] == {
        "component": "core",
        "method": "get_response",
        "iteration": 1,
        "max_iterations": 3,
    }
