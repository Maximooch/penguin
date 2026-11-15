"""Steering queued for a session follows it into its continuation session.

Covers SM-79: the mailbox keyed queued messages by the recipient's session id
at send time. When that session reached its boundary and the agent moved to
a continuation session, the message was never delivered, while the sender
had been told it was queued and ``status`` counted it forever.
"""

from __future__ import annotations

from typing import Any

import pytest

from penguin.system.message_bus import ProtocolMessage
from penguin.system.state import Session
from tests.test_engine_task_finish_contract import _finish_turn, _ScriptedTaskEngine


@pytest.mark.asyncio
async def test_steering_survives_a_session_rollover() -> None:
    engine = _ScriptedTaskEngine([_finish_turn(status="done", summary="Finished")] * 2)
    cm = engine.test_conversation_manager
    original_step = engine._llm_step
    first = cm.conversation.session

    async def step(**kwargs: Any) -> Any:
        if engine.provider_calls == 0:
            engine.agent_mailbox.enqueue(
                "default",
                first.id,
                ProtocolMessage("parent", "default", "Check this", message_id="m1"),
            )
            # The step's messages push the session over its boundary.
            cm.conversation.session = Session(metadata={"continued_from": first.id})
        else:
            engine.agent_mailbox.deliver("default", cm)
        return await original_step(**kwargs)

    engine._llm_step = step
    await engine.run_task("Work", max_iterations=3, enable_events=False)

    assert engine.provider_calls == 2
    delivered = [
        message
        for message in cm.conversation.session.messages
        if isinstance(message.metadata, dict)
        and message.metadata.get("message_id") == "m1"
    ]
    assert len(delivered) == 1
    assert engine.agent_mailbox.status("default")["queued_messages"] == 0
