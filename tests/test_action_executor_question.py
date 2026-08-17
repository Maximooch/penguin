"""Tests for ActionExecutor question flow."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from penguin.security.question import get_question_manager
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.utils.parser import ActionExecutor


async def _resolve_pending_question(
    session_id: str,
    *,
    answers: list[list[str]] | None = None,
    reject: bool = False,
) -> None:
    manager = get_question_manager()
    for _ in range(200):
        pending = manager.list_pending(session_id=session_id)
        if pending:
            request = pending[0]
            if reject:
                manager.reject(request.id)
            else:
                manager.reply(request.id, answers=answers or [["Default"]])
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Question request was never created")


@pytest.mark.asyncio
async def test_wait_for_resolution_returns_answered_request() -> None:
    manager = get_question_manager()
    manager.reset()

    request = manager.create_request(
        session_id="session_question_wait",
        questions=[
            {
                "question": "Pick one",
                "header": "Pick",
                "options": [
                    {"label": "A", "description": "Option A"},
                    {"label": "B", "description": "Option B"},
                ],
            }
        ],
    )

    waiter = asyncio.create_task(
        manager.wait_for_resolution(request.id, timeout_seconds=1.0)
    )
    await asyncio.sleep(0)
    manager.reply(request.id, answers=[["A"]])
    resolved = await waiter

    assert resolved is not None
    assert resolved.status.value == "answered"
    assert resolved.answers == [["A"]]


@pytest.mark.asyncio
async def test_question_shutdown_rejects_and_wakes_pending_waiters() -> None:
    """Shutdown must resolve suspended question actions without orphaned tasks."""
    manager = get_question_manager()
    manager.reset()
    request = manager.create_request(
        session_id="session_question_shutdown",
        questions=[{"question": "Continue?", "header": "Continue"}],
    )
    waiter = asyncio.create_task(manager.wait_for_resolution(request.id))
    await asyncio.sleep(0)

    assert manager.shutdown() == 1
    resolved = await asyncio.wait_for(waiter, timeout=1.0)

    assert resolved is not None
    assert resolved.status.value == "rejected"
    assert manager.list_pending() == []
    manager.reset()


@pytest.mark.asyncio
async def test_cancelled_question_waiter_rejects_stale_request() -> None:
    """Cancelling an action must not leave an answerable orphan request."""
    manager = get_question_manager()
    manager.reset()
    request = manager.create_request(
        session_id="session_question_cancel",
        questions=[{"question": "Continue?", "header": "Continue"}],
    )
    waiter = asyncio.create_task(manager.wait_for_resolution(request.id))
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    resolved = manager.get_request(request.id)
    assert resolved is not None
    assert resolved.status.value == "rejected"
    manager.reset()


def test_question_callback_can_be_unregistered() -> None:
    """Adapters can detach lifecycle callbacks during clean shutdown."""
    manager = get_question_manager()
    manager.reset()
    observed: list[str] = []

    def _on_created(request: object) -> None:
        observed.append(str(request))

    manager.on_request_created(_on_created)
    manager.remove_callback(_on_created)
    manager.create_request(
        session_id="session_question_callback",
        questions=[{"question": "Continue?", "header": "Continue"}],
    )

    assert observed == []
    manager.reset()


@pytest.mark.asyncio
async def test_question_action_blocks_until_reply_and_returns_summary() -> None:
    manager = get_question_manager()
    manager.reset()

    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    payload = json.dumps(
        {
            "questions": [
                {
                    "question": "Which provider should I use?",
                    "header": "Provider",
                    "options": [
                        {"label": "GitHub", "description": "Use GitHub OAuth"},
                        {"label": "Google", "description": "Use Google OAuth"},
                    ],
                }
            ]
        }
    )

    session_id = "session_question_action_reply"
    with execution_context_scope(
        ExecutionContext(session_id=session_id, conversation_id=session_id)
    ):
        resolver = asyncio.create_task(
            _resolve_pending_question(session_id, answers=[["GitHub"]])
        )
        result = await asyncio.wait_for(executor._question(payload), timeout=3.0)
        await resolver

    assert "User has answered your questions" in result
    assert '"Which provider should I use?"="GitHub"' in result


@pytest.mark.asyncio
async def test_question_action_returns_error_when_rejected() -> None:
    manager = get_question_manager()
    manager.reset()

    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    payload = json.dumps(
        {
            "questions": [
                {
                    "question": "Apply migration now?",
                    "header": "Migration",
                    "options": [
                        {"label": "Yes", "description": "Apply now"},
                        {"label": "No", "description": "Skip for now"},
                    ],
                }
            ]
        }
    )

    session_id = "session_question_action_reject"
    with execution_context_scope(
        ExecutionContext(session_id=session_id, conversation_id=session_id)
    ):
        resolver = asyncio.create_task(
            _resolve_pending_question(session_id, reject=True)
        )
        result = await asyncio.wait_for(executor._question(payload), timeout=3.0)
        await resolver

    assert result == "Error: The user rejected this question request"


@pytest.mark.asyncio
async def test_question_action_uses_request_scoped_timeout() -> None:
    manager = get_question_manager()
    manager.reset()
    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    payload = json.dumps(
        {
            "questions": [
                {
                    "question": "Continue?",
                    "header": "Continue",
                    "options": [{"label": "Yes", "description": "Continue"}],
                }
            ]
        }
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="session_question_timeout",
            approval_policy={"timeout_seconds": 0.01},
        )
    ):
        result = await asyncio.wait_for(executor._question(payload), timeout=1.0)

    assert result == "Error: Question request was not resolved"
    assert manager.list_pending(session_id="session_question_timeout") == []
    manager.reset()


@pytest.mark.asyncio
async def test_question_policy_without_timeout_waits_for_reply() -> None:
    """An unrelated approval policy must not become a zero-second timeout."""
    manager = get_question_manager()
    manager.reset()
    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    payload = json.dumps(
        {
            "questions": [
                {
                    "question": "Continue?",
                    "header": "Continue",
                    "options": [{"label": "Yes", "description": "Continue"}],
                }
            ]
        }
    )
    session_id = "session_question_without_timeout"

    with execution_context_scope(
        ExecutionContext(
            session_id=session_id,
            approval_policy={"default": "ask"},
        )
    ):
        resolver = asyncio.create_task(
            _resolve_pending_question(session_id, answers=[["Yes"]])
        )
        result = await asyncio.wait_for(executor._question(payload), timeout=3.0)
        await resolver

    assert '"Continue?"="Yes"' in result
    manager.reset()


@pytest.mark.asyncio
async def test_question_request_carries_execution_request_id() -> None:
    """Channel projections can correlate a question to its exact turn."""
    manager = get_question_manager()
    manager.reset()
    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    payload = json.dumps(
        {
            "questions": [
                {
                    "question": "Continue?",
                    "header": "Continue",
                    "options": [{"label": "Yes", "description": "Continue"}],
                }
            ]
        }
    )
    session_id = "session_question_request_id"
    request_id = "telegram-turn-question"

    with execution_context_scope(
        ExecutionContext(session_id=session_id, request_id=request_id)
    ):
        execution = asyncio.create_task(executor._question(payload))
        request = None
        for _ in range(200):
            pending = manager.list_pending(session_id=session_id)
            if pending:
                request = pending[0]
                break
            await asyncio.sleep(0.005)
        assert request is not None
        try:
            assert request.context["request_id"] == request_id
        finally:
            manager.reject(request.id)
            await asyncio.wait_for(execution, timeout=1.0)

    manager.reset()
