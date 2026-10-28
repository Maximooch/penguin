"""ACP adapter tests; require the optional acp extra."""

# ruff: noqa: E402 -- optional SDK must be skipped before importing the adapter.

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

acp = pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from acp.schema import AllowedOutcome, RequestPermissionResponse, ResourceContentBlock

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
    assert (
        connection.session_update.call_args.kwargs["update"].content.text == "fallback"
    )


@pytest.mark.asyncio
async def test_cancel_during_process_and_reject_concurrent_turn(agent, tmp_path):
    agent.on_connect(AsyncMock())
    session = (await agent.new_session(cwd=str(tmp_path))).session_id
    started = asyncio.Event()

    async def process(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    agent.core.process.side_effect = process
    turn = asyncio.create_task(
        agent.prompt(session_id=session, prompt=[text_block("wait")])
    )
    await started.wait()
    with pytest.raises(RequestError):
        await agent.prompt(session_id=session, prompt=[text_block("second")])
    await agent.cancel(session_id=session)
    assert (await turn).stop_reason == "cancelled"
    agent.core.abort_session.assert_awaited_once_with(session)
    assert agent.sessions[session].task is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selected,expected", [("allow_once", "approved"), ("reject_once", "denied")]
)
async def test_permission_round_trip(agent, tmp_path, selected, expected):
    manager = get_approval_manager()
    await agent.initialize(protocol_version=acp.PROTOCOL_VERSION)
    session = (await agent.new_session(cwd=str(tmp_path))).session_id
    conn = AsyncMock()
    conn.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id=selected)
    )
    agent.on_connect(conn)
    request = manager.create_request(
        "execute", "process.execute", "echo hi", "test", session_id=session
    )
    for _ in range(20):
        if manager.get_request(request.id).status.value != "pending":
            break
        await asyncio.sleep(0.01)
    assert manager.get_request(request.id).status.value == expected
    assert conn.request_permission.call_args.kwargs["session_id"] == session


@pytest.mark.asyncio
async def test_resource_references_preserve_order_without_fetching(agent, tmp_path):
    agent.on_connect(AsyncMock())
    sid = (await agent.new_session(str(tmp_path))).session_id
    local = tmp_path / "file with spaces.txt"
    local.write_text("Must only be read through normal tools", encoding="utf-8")
    await agent.prompt(
        sid,
        [
            text_block("Review these"),
            ResourceContentBlock(
                type="resource_link", uri=local.as_uri(), name=local.name
            ),
            ResourceContentBlock(
                type="resource_link",
                uri="https://example.invalid/context",
                name="remote",
            ),
            text_block("then explain"),
        ],
    )
    message = agent.core.process.call_args.args[0]
    assert message.startswith("Review these\n")
    assert message.endswith("\nthen explain")
    assert "file%20with%20spaces.txt" in message
    assert "https://example.invalid/context" in message
    assert "Must only be read" not in message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "uri",
    [
        "file:///outside.txt",
        "file://remote/share.txt",
        "relative.txt",
        "file:///bad%00.txt",
        "file:relative.txt",
        "https://[bad",
    ],
)
async def test_resource_link_boundaries(agent, tmp_path, uri):
    agent.on_connect(AsyncMock())
    sid = (await agent.new_session(str(tmp_path))).session_id
    with pytest.raises(RequestError):
        await agent.prompt(
            sid, [ResourceContentBlock(type="resource_link", uri=uri, name="test")]
        )
    agent.core.process.assert_not_called()


@pytest.mark.asyncio
async def test_percent_encoded_traversal_is_rejected(agent, tmp_path):
    agent.on_connect(AsyncMock())
    sid = (await agent.new_session(str(tmp_path))).session_id
    uri = tmp_path.as_uri() + "/%2e%2e/private.txt"
    with pytest.raises(RequestError):
        await agent.prompt(
            sid, [ResourceContentBlock(type="resource_link", uri=uri, name="escape")]
        )
    agent.core.process.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["max_tokens", "max_turn_requests", "refusal", "cancelled"]
)
async def test_explicit_stop_reason_is_preserved(agent, tmp_path, reason):
    agent.on_connect(AsyncMock())
    sid = (await agent.new_session(str(tmp_path))).session_id
    agent.core.process.return_value = {
        "assistant_response": "partial",
        "stop_reason": reason,
    }
    assert (await agent.prompt(sid, [text_block("go")])).stop_reason == reason


@pytest.mark.asyncio
async def test_failed_provider_result_releases_session(agent, tmp_path):
    agent.on_connect(AsyncMock())
    sid = (await agent.new_session(str(tmp_path))).session_id
    agent.core.process.return_value = RuntimeError("private provider detail")
    with pytest.raises(RequestError) as failure:
        await agent.prompt(sid, [text_block("go")])
    assert failure.value.code == -32603
    assert agent.sessions[sid].task is None
    agent.core.process.return_value = {"assistant_response": "recovered"}
    assert (await agent.prompt(sid, [text_block("again")])).stop_reason == "end_turn"
