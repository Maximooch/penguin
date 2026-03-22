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
