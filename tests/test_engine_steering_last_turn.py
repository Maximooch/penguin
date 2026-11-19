"""Steering that arrives in the last allowed turn does not discard a finish.

Covers SM-84: a pending steering message made the loop continue before the
finish signal was checked, even when no further turn was allowed, so a task
that called ``finish_task`` in its last iteration (or with its token budget
spent) ended as ``iterations_exceeded`` (or ``budget_limited``) instead.
The message stays queued for the agent's next run.
"""

from __future__ import annotations

from typing import Any

import pytest

from penguin.system.message_bus import ProtocolMessage
from tests.test_engine_task_finish_contract import _finish_turn, _ScriptedTaskEngine


def _engine_with_late_steering() -> _ScriptedTaskEngine:
    engine = _ScriptedTaskEngine([_finish_turn(status="done", summary="Finished")] * 2)
    cm = engine.test_conversation_manager
    original_step = engine._llm_step

    async def step(**kwargs: Any) -> Any:
        engine.agent_mailbox.enqueue(
            "default",
            cm.conversation.session.id,
            ProtocolMessage("parent", "default", "One more thing", message_id="m1"),
        )
        return await original_step(**kwargs)

    engine._llm_step = step
    return engine


@pytest.mark.asyncio
async def test_a_finish_in_the_last_iteration_is_kept() -> None:
    engine = _engine_with_late_steering()

    result = await engine.run_task("Work", max_iterations=1, enable_events=False)

    assert engine.provider_calls == 1
    assert result["status"] == "pending_review"
    session = engine.test_conversation_manager.conversation.session
    assert engine.agent_mailbox.has_pending("default", session)


@pytest.mark.asyncio
async def test_a_finish_with_the_budget_spent_is_kept() -> None:
    engine = _engine_with_late_steering()

    result = await engine.run_task("Work", token_budget=1, enable_events=False)

    assert engine.provider_calls == 1
    assert result["status"] == "pending_review"
