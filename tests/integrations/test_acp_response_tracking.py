"""A new session's response is recognised even if an agent request reuses its id.

Covers SM-99: the transport tracked the client's ``session/new`` request ids
and cleared one when any outgoing message carried that id, including the
agent's own requests (permission, file, terminal), whose ids come from a
separate counter. The real response then went out unrecognised, so the new
session never got its available commands.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("acp")

from penguin.integrations.acp.stdio import ProtocolTransport


class _Writer:
    def __init__(self) -> None:
        self.lines: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.lines.append(data)

    async def drain(self) -> None:
        return None


@pytest.mark.asyncio
async def test_an_agent_request_with_the_same_id_is_not_the_response() -> None:
    writer: Any = _Writer()
    transport = ProtocolTransport(asyncio.StreamReader(), writer)
    announced: list[str] = []

    async def after_session_response(session_id: str) -> None:
        announced.append(session_id)

    transport.after_session_response = after_session_response
    transport.session_responses.add(3)  # the client's session/new request id

    agent_request: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "session/request_permission",
        "params": {"sessionId": "other"},
    }
    await transport.send(agent_request)
    await transport.send({"jsonrpc": "2.0", "id": 3, "result": {"sessionId": "new"}})

    assert announced == ["new"]
