"""ACP adapter tests; require the optional acp extra."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

acp = pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

from penguin.integrations.acp.server import PenguinACPAgent
from penguin.security.approval import get_approval_manager
from penguin.system.execution_context import get_current_execution_context


class FakeCore:
    def __init__(self):
        self.process = AsyncMock(return_value={"assistant_response": "done"})
        self.abort_session = AsyncMock(return_value=True)
        self.next_id = 0

    def create_conversation(self):
        self.next_id += 1
        return f"session-{self.next_id}"


@pytest.fixture
def agent(tmp_path):
    manager = get_approval_manager()
    manager.reset()
    instance = PenguinACPAgent(FakeCore(), allowed_roots=(tmp_path,))
    yield instance
    instance.close()
    manager.reset()


@pytest.mark.asyncio
async def test_initialize_new_session_and_reject_unsupported_input(agent, tmp_path):
    response = await agent.initialize(protocol_version=acp.PROTOCOL_VERSION)
    assert response.protocol_version == acp.PROTOCOL_VERSION
    assert response.agent_capabilities.load_session is False
    assert response.agent_capabilities.prompt_capabilities.image is False
    directory = tmp_path / "project"
    directory.mkdir()
    session = await agent.new_session(cwd=str(directory))
    assert agent.sessions[session.session_id].cwd == directory.resolve()
    with pytest.raises(RequestError):
        await agent.new_session(cwd=str(tmp_path.parent))
    with pytest.raises(RequestError):
        await agent.new_session(cwd=str(directory), mcp_servers=[object()])
    with pytest.raises(RequestError):
        await agent.prompt(session_id=session.session_id, prompt=[])


@pytest.mark.asyncio
async def test_prompt_scoped_stream_and_fallback(agent, tmp_path):
    connection = AsyncMock()
    agent.on_connect(connection)
    session = (await agent.new_session(cwd=str(tmp_path))).session_id

    async def process(message, **kwargs):
        context = get_current_execution_context()
        assert message == "hello"
        assert context.session_id == session
        assert Path(context.directory) == tmp_path.resolve()
        assert kwargs["conversation_id"] == session
        await kwargs["stream_callback"]("one", "assistant")
        return {"assistant_response": "one"}

    agent.core.process.side_effect = process
    response = await agent.prompt(session_id=session, prompt=[text_block("hello")])
    assert response.stop_reason == "end_turn"
    assert connection.session_update.await_count == 1
    assert connection.session_update.call_args.kwargs["update"].content.text == "one"
    agent.core.process.side_effect = None
    agent.core.process.return_value = {"assistant_response": "fallback"}
    await agent.prompt(session_id=session, prompt=[text_block("hello")])
    assert connection.session_update.call_args.kwargs["update"].content.text == "fallback"


@pytest.mark.asyncio
async def test_cancel_during_process_and_reject_concurrent_turn(agent, tmp_path):
    agent.on_connect(AsyncMock())
    session = (await agent.new_session(cwd=str(tmp_path))).session_id
    started = asyncio.Event()

    async def process(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    agent.core.process.side_effect = process
    turn = asyncio.create_task(agent.prompt(session_id=session, prompt=[text_block("wait")]))
    await started.wait()
    with pytest.raises(RequestError):
        await agent.prompt(session_id=session, prompt=[text_block("second")])
    await agent.cancel(session_id=session)
    assert (await turn).stop_reason == "cancelled"
    agent.core.abort_session.assert_awaited_once_with(session)
    assert agent.sessions[session].task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("selected,expected", [("allow_once", "approved"), ("reject_once", "denied")])
async def test_permission_round_trip(agent, tmp_path, selected, expected):
    manager = get_approval_manager()
    await agent.initialize(protocol_version=acp.PROTOCOL_VERSION)
    session = (await agent.new_session(cwd=str(tmp_path))).session_id
    conn = AsyncMock()
    conn.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id=selected)
    )
    agent.on_connect(conn)
    request = manager.create_request("execute", "process.execute", "echo hi", "test", session_id=session)
    for _ in range(20):
        if manager.get_request(request.id).status.value != "pending":
            break
        await asyncio.sleep(0.01)
    assert manager.get_request(request.id).status.value == expected
    assert conn.request_permission.call_args.kwargs["session_id"] == session
