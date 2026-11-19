"""Loading a session resolves its children's unfinished processes and tool calls.

Covers SM-102: restore keyed a child's process by the root and only matched
``process:<pid>`` call ids, while a child's process is recorded as
``<child>:process:<pid>`` (or as a native child envelope), and refresh only
looked at the root's own processes; the replay closed only the root's own
unfinished tool calls. After a reconnect those stayed "in progress" forever.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.children import Child
from penguin.integrations.acp.server import PenguinACPAgent

CHILD = "child-1"


def _agent(storage, tmp_path, *, native: bool) -> tuple[PenguinACPAgent, Any]:
    agent = PenguinACPAgent(PersistentCore(storage), allowed_roots=(tmp_path,))
    conn = AsyncMock()
    agent.on_connect(conn)
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    if native:
        agent._transport = SimpleNamespace(subagents=True, send=send)
    agent.sent = sent  # type: ignore[attr-defined]
    return agent, conn


async def _start_child(agent: PenguinACPAgent, sid: str, tmp_path, *, native: bool):
    agent._children.children[CHILD] = Child(
        parent=sid, root=sid, agent="worker", cwd=tmp_path, active=True
    )
    if native:
        await agent._children.raw(
            sid,
            sid,
            {
                "sessionUpdate": "subagent_update",
                "sessionId": CHILD,
                "state": {"state": "running"},
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_a_childs_process_is_resolved_after_reconnect(tmp_path, native) -> None:
    storage = tmp_path / "store"
    first, _ = _agent(storage, tmp_path, native=native)
    sid = (await first.new_session(str(tmp_path))).session_id
    await _start_child(first, sid, tmp_path, native=native)
    await first._processes.update(
        {
            "session_id": CHILD,
            "process_id": "p",
            "process_status": "running",
            "agent_id": "worker",
        },
        completed=False,
    )
    first.close()

    second, conn = _agent(storage, tmp_path, native=native)
    try:
        await second.load_session(str(tmp_path), sid)

        assert second._processes.states[(CHILD, "p")]["completed"] is True
        if native:
            closing = [
                m["params"]["update"]
                for m in second.sent
                if m["params"]["sessionId"] == CHILD
                and m["params"]["update"].get("toolCallId") == "process:p"
            ]
            assert closing and closing[-1]["status"] == "failed"
        else:
            closing = [
                c.kwargs["update"]
                for c in conn.session_update.call_args_list
                if getattr(c.kwargs["update"], "tool_call_id", "")
                == CHILD + ":process:p"
            ]
            assert closing and closing[-1].status == "failed"
    finally:
        second.close()


@pytest.mark.asyncio
async def test_a_native_childs_open_tool_call_is_closed_on_replay(tmp_path) -> None:
    storage = tmp_path / "store"
    first, _ = _agent(storage, tmp_path, native=True)
    sid = (await first.new_session(str(tmp_path))).session_id
    await _start_child(first, sid, tmp_path, native=True)
    await first._children.raw(
        sid,
        CHILD,
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "call-1",
            "title": "Read",
            "status": "in_progress",
        },
    )
    first.close()

    second, _ = _agent(storage, tmp_path, native=True)
    try:
        await second.load_session(str(tmp_path), sid)

        replayed = [
            m["params"]["update"]
            for m in second.sent
            if m["params"]["sessionId"] == CHILD
            and m["params"]["update"].get("toolCallId") == "call-1"
        ]
        assert replayed[-1]["status"] == "failed"
    finally:
        second.close()
