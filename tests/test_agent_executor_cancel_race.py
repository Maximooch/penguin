"""Cancelling an agent does not overwrite an outcome it already reached (SM-54)."""

from __future__ import annotations

import asyncio

import pytest

from penguin.multi.executor import AgentExecutor, AgentState, AgentTask


@pytest.mark.asyncio
async def test_cancel_keeps_the_outcome_of_an_agent_that_finished_first() -> None:
    executor = AgentExecutor.__new__(AgentExecutor)
    record = AgentTask(agent_id="a1", prompt="work", state=AgentState.RUNNING)

    async def finishes_despite_cancel() -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            # The agent reached its result while the cancel was in flight.
            record.result = "done"
            record.state = AgentState.COMPLETED

    record.task = asyncio.create_task(finishes_despite_cancel())
    await asyncio.sleep(0)
    executor._tasks = {"a1": record}

    cancelled = await executor.cancel("a1")

    assert cancelled is False
    assert record.state == AgentState.COMPLETED
    assert record.result == "done"


@pytest.mark.asyncio
async def test_cancel_marks_a_running_agent_cancelled() -> None:
    executor = AgentExecutor.__new__(AgentExecutor)
    record = AgentTask(agent_id="a1", prompt="work", state=AgentState.RUNNING)
    record.task = asyncio.create_task(asyncio.sleep(30))
    await asyncio.sleep(0)
    executor._tasks = {"a1": record}

    assert await executor.cancel("a1") is True
    assert record.state == AgentState.CANCELLED
