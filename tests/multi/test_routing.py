"""Tests for multi-agent message routing helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from penguin.multi import routing


@pytest.mark.asyncio
async def test_route_message_forwards_to_engine_with_scope() -> None:
    engine = SimpleNamespace(route_message=AsyncMock(return_value=True))
    core = SimpleNamespace(engine=engine)

    delivered = await routing.route_message(
        core,
        "planner",
        {"task": "plan"},
        message_type="task",
        metadata={"priority": "high"},
        agent_id="default",
        channel="work",
    )

    assert delivered is True
    engine.route_message.assert_awaited_once_with(
        "planner",
        {"task": "plan"},
        message_type="task",
        metadata={"priority": "high"},
        agent_id="default",
        channel="work",
    )


@pytest.mark.asyncio
async def test_route_message_returns_false_and_logs_when_engine_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("tests.multi.routing")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        delivered = await routing.route_message(
            SimpleNamespace(engine=None),
            "planner",
            "hello",
            logger=logger,
        )

    assert delivered is False
    assert "Engine not available for message routing" in caplog.text


@pytest.mark.asyncio
async def test_send_helpers_delegate_to_engine_methods() -> None:
    engine = SimpleNamespace(
        send_to_agent=AsyncMock(return_value=True),
        send_to_human=AsyncMock(return_value=True),
        human_reply=AsyncMock(return_value=True),
    )
    core = SimpleNamespace(engine=engine)

    assert await routing.send_to_agent(
        core,
        "worker",
        "build it",
        metadata={"via": "test"},
        channel="tasks",
    )
    assert await routing.send_to_human(
        core,
        {"status": "running"},
        message_type="status",
        metadata={"source": "worker"},
        channel="ui",
    )
    assert await routing.human_reply(
        core,
        "worker",
        "approved",
        message_type="reply",
        metadata={"decision": "yes"},
        channel="tasks",
    )

    engine.send_to_agent.assert_awaited_once_with(
        "worker",
        "build it",
        message_type="message",
        metadata={"via": "test"},
        channel="tasks",
    )
    engine.send_to_human.assert_awaited_once_with(
        {"status": "running"},
        message_type="status",
        metadata={"source": "worker"},
        channel="ui",
    )
    engine.human_reply.assert_awaited_once_with(
        "worker",
        "approved",
        message_type="reply",
        metadata={"decision": "yes"},
        channel="tasks",
    )


@pytest.mark.asyncio
async def test_send_helpers_return_false_without_engine() -> None:
    core = SimpleNamespace(engine=None)

    assert await routing.send_to_agent(core, "worker", "build") is False
    assert await routing.send_to_human(core, "status") is False
    assert await routing.human_reply(core, "worker", "done") is False
