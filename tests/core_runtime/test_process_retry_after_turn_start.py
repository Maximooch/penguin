"""``process`` is not retried once the turn has started (SM-10).

``process`` handles its own errors, so the only failures that reach the retry
wrapper come from the error handler or the cleanup. By then the user message
is saved and tools may have run; a retry re-added the message and re-ran the
tools. A retry is safe only before the turn starts.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import process_runtime
from tests.core_runtime.test_process_runtime import _process_kwargs


def _wire(
    monkeypatch: pytest.MonkeyPatch, events: list[str], *, fail_before_turn: int = 0
) -> SimpleNamespace:
    async def emit_ui_event(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("ui stream closed")

    owner = SimpleNamespace(engine=object(), emit_ui_event=emit_ui_event)
    conversation_manager = SimpleNamespace(
        conversation=SimpleNamespace(session=SimpleNamespace(id="s1"))
    )
    failures = {"left": fail_before_turn}

    def load_context_files(*_args: Any, **_kwargs: Any) -> int:
        if failures["left"]:
            failures["left"] -= 1
            raise OSError("context file busy")
        return 0

    async def register(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def emit_user_message(*_args: Any, **_kwargs: Any) -> None:
        events.append("user message saved")

    async def run_engine(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        events.append("tool ran")
        if fail_before_turn:
            return {"assistant_response": "done", "action_results": []}
        raise RuntimeError("provider failed after the tool")

    async def finalize(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        process_runtime,
        "get_current_execution_context",
        lambda: SimpleNamespace(request_id="r1", session_id="s1"),
    )
    conversations = process_runtime.core_conversations
    lifecycle = process_runtime.core_process_lifecycle
    monkeypatch.setattr(
        conversations,
        "resolve_conversation_manager",
        lambda *_a, **_k: conversation_manager,
    )
    monkeypatch.setattr(conversations, "load_process_context_files", load_context_files)
    monkeypatch.setattr(lifecycle, "register_opencode_process_request", register)
    monkeypatch.setattr(lifecycle, "emit_process_user_message", emit_user_message)
    monkeypatch.setattr(lifecycle, "finalize_opencode_process_request", finalize)
    monkeypatch.setattr(lifecycle, "finalize_process_response", finalize)
    monkeypatch.setattr(
        process_runtime.core_process_streaming,
        "prepare_engine_process_context",
        lambda *_a, **_k: SimpleNamespace(
            stream_callback=None, scoped_conversation_id="s1"
        ),
    )
    monkeypatch.setattr(
        process_runtime.core_process_engine, "run_engine_process", run_engine
    )
    return owner


async def _no_sleep(_delay: float) -> None:
    return None


@pytest.mark.asyncio
async def test_a_failure_after_the_turn_started_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    owner = _wire(monkeypatch, events)

    result = await process_runtime.process_with_retry(
        owner, retry_sleep=_no_sleep, **_process_kwargs()
    )

    assert events == ["user message saved", "tool ran"]
    assert isinstance(result, ConnectionError)


@pytest.mark.asyncio
async def test_a_failure_before_the_turn_starts_is_still_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    owner = _wire(monkeypatch, events, fail_before_turn=1)

    result = await process_runtime.process_with_retry(
        owner, retry_sleep=_no_sleep, **_process_kwargs()
    )

    assert events == ["user message saved", "tool ran"]
    assert result == {"assistant_response": "done", "action_results": []}
