"""Actual question producer, negotiated forms, and cancellation cleanup."""

import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.schema import AcceptElicitationResponse
from acp.stdio import spawn_stdio_connection
from test_acp_sessions import PersistentCore
from test_acp_wire import _CLI_AGENT

from penguin.integrations.acp.server import PenguinACPAgent
from penguin.security.question import get_question_manager
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.utils.parser import ActionExecutor

QUESTION = {
    "question": "Which color?",
    "header": "Color",
    "custom": False,
    "options": [
        {"label": "blue", "description": "Blue"},
        {"label": "green", "description": "Green"},
    ],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("supported", [True, False])
async def test_real_question_tool_completes_or_gives_text_fallback(tmp_path, supported):
    manager = get_question_manager()
    manager.reset()
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "sessions"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    conn.create_elicitation.return_value = AcceptElicitationResponse(
        action="accept", content={"0": "blue"}
    )
    agent.on_connect(conn)
    await agent.initialize(1)
    agent._questions.supported = supported
    sid = (await agent.new_session(str(tmp_path))).session_id
    executor = ActionExecutor(
        tool_manager=SimpleNamespace(), task_manager=SimpleNamespace()
    )
    try:
        with execution_context_scope(ExecutionContext(session_id=sid)):
            result = await asyncio.wait_for(executor._question(json.dumps(QUESTION)), 2)
        assert not manager.list_pending(sid)
        if supported:
            assert '"blue"' in result
            assert conn.create_elicitation.call_count == 1
        else:
            assert "rejected" in result
            assert (
                "Please answer in your next message"
                in conn.session_update.call_args.kwargs["update"].content.text
            )
            conn.create_elicitation.assert_not_called()
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_cancel_rejects_waiting_form_and_late_answer(tmp_path):
    manager = get_question_manager()
    manager.reset()
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "sessions"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    started = asyncio.Event()

    async def waiting(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    conn.create_elicitation.side_effect = waiting
    agent.on_connect(conn)
    await agent.initialize(1)
    agent._questions.supported = True
    sid = (await agent.new_session(str(tmp_path))).session_id
    request = manager.create_request(session_id=sid, questions=[QUESTION])
    try:
        await asyncio.wait_for(started.wait(), 2)
        await agent.cancel(sid)
        await asyncio.gather(*agent._questions.tasks[sid], return_exceptions=True)
        assert manager.get_request(request.id).status.value == "rejected"
        assert manager.reply(request.id, [["blue"]]) is None
        assert not manager.list_pending(sid)
        assert not agent._questions.tasks[sid]
    finally:
        agent.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["unlisted", [], None])
async def test_invalid_form_answer_never_becomes_a_user_answer(tmp_path, value):
    manager = get_question_manager()
    manager.reset()
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "store"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    conn.create_elicitation.return_value = AcceptElicitationResponse(
        action="accept", content={"0": value}
    )
    agent.on_connect(conn)
    await agent.initialize(1)
    agent._questions.supported = True
    sid = (await agent.new_session(str(tmp_path))).session_id
    request = manager.create_request(session_id=sid, questions=[QUESTION])
    try:
        resolved = await asyncio.wait_for(manager.wait_for_resolution(request.id), 2)
        assert resolved.status.value == "rejected"
        assert resolved.answers is None
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_form_roundtrip_through_real_stdio(tmp_path):
    script = _CLI_AGENT.replace(
        "        print('provider diagnostic')",
        """
        print('provider diagnostic')
        if text == 'question':
            import json
            from penguin.utils.parser import ActionExecutor
            executor = ActionExecutor(tool_manager=types.SimpleNamespace(),
                                      task_manager=types.SimpleNamespace())
            result = await executor._question(json.dumps({
                'question': 'Which color?', 'header': 'Color', 'custom': False,
                'options': [{'label': 'blue', 'description': 'Blue'},
                            {'label': 'green', 'description': 'Green'}]}))
            return {'assistant_response': result}
""",
    )
    requests = []

    async def handler(method, params, is_notification):
        if method == "elicitation/create":
            requests.append(params)
            return {"action": "accept", "content": {"0": "green"}}

    env = {
        **os.environ,
        "PENGUIN_WORKSPACE": str(tmp_path),
        "ACP_TEST_STORE": str(tmp_path / "sessions"),
    }
    async with spawn_stdio_connection(
        handler, sys.executable, "-c", script, env=env
    ) as (conn, _):
        await asyncio.wait_for(
            conn.send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {"elicitation": {"form": {}}},
                },
            ),
            15,
        )
        sid = (
            await conn.send_request(
                "session/new", {"cwd": str(tmp_path), "mcpServers": []}
            )
        )["sessionId"]
        await asyncio.wait_for(
            conn.send_request(
                "session/prompt",
                {"sessionId": sid, "prompt": [{"type": "text", "text": "question"}]},
            ),
            10,
        )
        assert requests[0]["sessionId"] == sid
        assert requests[0]["mode"] == "form"
        assert requests[0]["requestedSchema"]["properties"]["0"]["enum"] == [
            "blue",
            "green",
        ]
