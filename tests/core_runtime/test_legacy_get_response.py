"""The legacy core response path stops when cancelled and never saves an apology.

Covers SM-64: ``_fetch_assistant_response`` logged a cancellation and
retried, so a cancelled request kept calling the provider; and after empty
answers it saved an apology into the conversation as the assistant's own
message.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime.response_generation import get_response


def _owner(answer: Any) -> tuple[SimpleNamespace, list[str]]:
    saved: list[str] = []
    conversation = SimpleNamespace(
        get_formatted_messages=lambda: [{"role": "user", "content": "hi"}],
        add_assistant_message=saved.append,
        add_iteration_marker=lambda *_a: None,
    )
    owner = SimpleNamespace(
        api_client=SimpleNamespace(get_response=answer),
        conversation_manager=SimpleNamespace(
            conversation=conversation, save=lambda: None
        ),
    )
    return owner, saved


async def _actions(_owner: Any, _text: Any, **_kwargs: Any) -> Any:
    return SimpleNamespace(actions=[], action_results=[], exit_continuation=False)


async def _call(owner: Any) -> tuple[dict[str, Any], bool]:
    return await get_response(
        owner,
        current_iteration=None,
        max_iterations=None,
        stream_callback=None,
        streaming=False,
        process_response_actions=_actions,
        sleep=AsyncMock(),
        log_error=lambda *_a, **_k: None,
        log=logging.getLogger(__name__),
    )


@pytest.mark.asyncio
async def test_a_cancelled_request_is_not_retried() -> None:
    calls: list[int] = []

    async def cancelled(**_kwargs: Any) -> str:
        calls.append(1)
        raise asyncio.CancelledError

    owner, _saved = _owner(cancelled)

    with pytest.raises(asyncio.CancelledError):
        await _call(owner)
    assert calls == [1]


@pytest.mark.asyncio
async def test_an_apology_after_empty_answers_is_shown_but_not_saved() -> None:
    async def empty(**_kwargs: Any) -> str:
        return ""

    owner, saved = _owner(empty)

    result, _exit = await _call(owner)

    assert saved == []
    assert "apologize" in result["assistant_response"]
    assert result["error"] == "empty_response"
