"""Exercise the existing ACP adapter over real stdio, without a model provider."""

# ruff: noqa: E402 -- optional SDK must be skipped before importing its models.

import asyncio
import os
import sys

import pytest

acp = pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from acp.schema import ImageContentBlock

# A subprocess, not an in-process mock connection: assertions cover framing,
# stdout cleanliness and the SDK's actual request/notification dispatcher.
_FAKE_AGENT = """
import asyncio
import os
from pathlib import Path
from acp import run_agent
from penguin.integrations.acp.server import PenguinACPAgent

class Core:
    def __init__(self):
        self.number = 0
    def create_conversation(self):
        self.number += 1
        return f'session-{self.number}'
    async def process(self, text, **kwargs):
        await kwargs['stream_callback'](f'{text}: ', 'assistant')
        await kwargs['stream_callback']('done', 'assistant')
        return {'assistant_response': f'{text}: done'}
    async def abort_session(self, session_id):
        return True

async def main():
    agent = PenguinACPAgent(Core(), allowed_roots=(Path(os.environ['ACP_TEST_ROOT']),))
    try:
        await run_agent(agent)
    finally:
        agent.close()

asyncio.run(main())
"""

# Exercise the shipped entrypoint and serve(), substituting only the expensive
# provider-backed core. Startup and processing prints must never enter stdout.
_CLI_AGENT = """
import os, sys, types
from pathlib import Path
module = types.ModuleType('penguin.core')
class Core:
    def __init__(self):
        from penguin.cli.events import EventBus
        self.event_bus = EventBus()
        if os.environ.get('ACP_TEST_STORE'):
            from penguin.system.session_manager import SessionManager
            self.conversation_manager = types.SimpleNamespace(session_manager=
                SessionManager(os.environ['ACP_TEST_STORE'], auto_save_interval=0))
        self.model_config = types.SimpleNamespace(vision_enabled=True)
    @classmethod
    async def create(cls, **kwargs):
        print('startup diagnostic')
        return cls()
    def create_conversation(self):
        if hasattr(self, 'conversation_manager'):
            return self.conversation_manager.session_manager.create_session().id
        return 'cli-session'
    def list_available_models(self):
        return [{'id': 'other', 'name': 'Other', 'vision_enabled': True}]
    async def resolve_request_runtime(self, model_id):
        return types.SimpleNamespace(vision_enabled=True), object()
    async def process(self, text, **kwargs):
        print('provider diagnostic')
        if text == 'tools':
            sid = kwargs['conversation_id']
            await self.event_bus.emit('action', {
                'session_id': sid, 'id': 'tool-1', 'type': 'execute_command'})
            await self.event_bus.emit('action_result', {
                'session_id': sid, 'id': 'tool-1',
                'status': 'completed', 'result': 'done'})
        await kwargs['stream_callback']('answer: café 🐧', 'assistant')
        return {'assistant_response': 'answer: café 🐧'}
    async def abort_session(self, session_id):
        return True
module.PenguinCore = Core
sys.modules['penguin.core'] = module
from penguin.cli.entrypoint import main
raise SystemExit(main(['acp']))
"""


@pytest.mark.asyncio
async def test_real_cli_stdio_keeps_diagnostics_out_of_protocol(tmp_path):
    client = RecordingClient()
    env = {**os.environ, "PENGUIN_WORKSPACE": str(tmp_path)}
    async with acp.spawn_agent_process(
        client, sys.executable, "-c", _CLI_AGENT, env=env
    ) as (conn, process):
        await asyncio.wait_for(conn.initialize(acp.PROTOCOL_VERSION), 15)
        sid = (await asyncio.wait_for(conn.new_session(str(tmp_path)), 10)).session_id
        from acp.schema import ResourceContentBlock

        response = await asyncio.wait_for(
            conn.prompt(
                sid,
                [
                    text_block("review"),
                    ResourceContentBlock(
                        type="resource_link",
                        uri=(tmp_path / "context.txt").as_uri(),
                        name="context",
                    ),
                ],
            ),
            10,
        )
        assert response.stop_reason == "end_turn"
        assert [update.content.text for _, update in client.updates] == [
            "answer: café 🐧"
        ]
        assert process.returncode is None
        await asyncio.wait_for(conn.prompt(sid, [text_block("tools")]), 10)
        tools = [
            update
            for _, update in client.updates
            if update.session_update.startswith("tool_call")
        ]
        assert [update.status for update in tools] == ["pending", "completed"]
        assert tools[0].tool_call_id == tools[1].tool_call_id == "tool-1"


class RecordingClient:
    def __init__(self):
        self.updates = []
        self.commands = []

    async def session_update(self, session_id, update, **kwargs):
        if update.session_update == "available_commands_update":
            self.commands.append(update)
        else:
            self.updates.append((session_id, update))


@pytest.mark.asyncio
async def test_cli_restart_session_load_resume_and_close(tmp_path):
    env = {
        **os.environ,
        "PENGUIN_WORKSPACE": str(tmp_path),
        "ACP_TEST_STORE": str(tmp_path / "sessions"),
    }
    client = RecordingClient()
    async with acp.spawn_agent_process(
        client, sys.executable, "-c", _CLI_AGENT, env=env, use_unstable_protocol=True
    ) as (conn, _):
        await asyncio.wait_for(conn.initialize(acp.PROTOCOL_VERSION), 15)
        sid = (await conn.new_session(str(tmp_path))).session_id
        await conn.prompt(sid, [text_block("persist")])
    second_client = RecordingClient()
    async with acp.spawn_agent_process(
        second_client,
        sys.executable,
        "-c",
        _CLI_AGENT,
        env=env,
        use_unstable_protocol=True,
    ) as (conn, _):
        response = await asyncio.wait_for(conn.initialize(acp.PROTOCOL_VERSION), 15)
        assert response.agent_capabilities.load_session
        assert [s.session_id for s in (await conn.list_sessions()).sessions] == [sid]
        await conn.load_session(str(tmp_path), sid)
        assert [u.session_update for _, u in second_client.updates] == [
            "user_message_chunk",
            "agent_message_chunk",
        ]
        await conn.close_session(sid)
        before = len(second_client.updates)
        await conn.resume_session(sid, str(tmp_path))
        assert len(second_client.updates) == before
        assert (await conn.prompt(sid, [text_block("again")])).stop_reason == "end_turn"
        from acp.schema import EmbeddedResourceContentBlock, TextResourceContents

        assert response.agent_capabilities.prompt_capabilities.image
        embedded = EmbeddedResourceContentBlock(
            type="resource",
            resource=TextResourceContents(
                uri="file:///virtual/file.txt",
                text="client-provided content",
                mime_type="text/plain",
            ),
        )
        assert (await conn.prompt(sid, [embedded])).stop_reason == "end_turn"
        choices = await conn.set_config_option(
            session_id=sid, config_id="model", value="other"
        )
        assert choices.config_options[0].current_value == "other"
        await conn.prompt(sid, [text_block("/status")])
        assert second_client.updates[-1][1].content.text == "Mode: build; model: other"


@pytest.mark.asyncio
async def test_acp_stdio_initialize_sessions_and_two_turns(tmp_path):
    client = RecordingClient()
    env = {**os.environ, "ACP_TEST_ROOT": str(tmp_path)}
    async with acp.spawn_agent_process(
        client, sys.executable, "-c", _FAKE_AGENT, env=env
    ) as (conn, process):
        response = await asyncio.wait_for(conn.initialize(acp.PROTOCOL_VERSION), 10)
        assert response.protocol_version == acp.PROTOCOL_VERSION
        assert response.agent_capabilities.load_session is False
        first = (await asyncio.wait_for(conn.new_session(str(tmp_path)), 10)).session_id
        second = (
            await asyncio.wait_for(conn.new_session(str(tmp_path)), 10)
        ).session_id
        assert first != second
        for sid, text in ((first, "one"), (second, "other"), (first, "two")):
            result = await asyncio.wait_for(conn.prompt(sid, [text_block(text)]), 10)
            assert result.stop_reason == "end_turn"
            chunks = [
                update.content.text
                for session, update in client.updates
                if session == sid and update.content.text.startswith(text)
            ]
            assert chunks[-1] == f"{text}: "
        assert [
            update.content.text for sid, update in client.updates if sid == first
        ] == ["one: ", "done", "two: ", "done"]
        assert [
            update.content.text for sid, update in client.updates if sid == second
        ] == ["other: ", "done"]
        assert process.returncode is None


@pytest.mark.asyncio
async def test_acp_stdio_rejects_unsupported_requests_without_killing_connection(
    tmp_path,
):
    client = RecordingClient()
    env = {**os.environ, "ACP_TEST_ROOT": str(tmp_path)}
    async with acp.spawn_agent_process(
        client, sys.executable, "-c", _FAKE_AGENT, env=env
    ) as (conn, process):
        with pytest.raises(RequestError):
            await asyncio.wait_for(conn.initialize(0), 10)
        await asyncio.wait_for(conn.initialize(acp.PROTOCOL_VERSION), 10)
        with pytest.raises(RequestError):
            await asyncio.wait_for(conn.new_session(str(tmp_path.parent)), 10)
        sid = (await asyncio.wait_for(conn.new_session(str(tmp_path)), 10)).session_id
        with pytest.raises(RequestError):
            await asyncio.wait_for(
                conn.prompt(
                    sid,
                    [
                        ImageContentBlock(
                            type="image", data="aGVsbG8=", mime_type="image/png"
                        )
                    ],
                ),
                10,
            )
        assert (
            await asyncio.wait_for(conn.prompt(sid, [text_block("okay")]), 10)
        ).stop_reason == "end_turn"
        assert process.returncode is None


@pytest.mark.asyncio
async def test_new_session_response_precedes_command_discovery(tmp_path):
    """Editors drop updates before the session response registers their target."""
    import json

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _CLI_AGENT,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={**os.environ, "PENGUIN_WORKSPACE": str(tmp_path)},
    )

    async def request(identifier, method, params):
        process.stdin.write(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": identifier,
                        "method": method,
                        "params": params,
                    }
                )
                + "\n"
            ).encode()
        )
        await process.stdin.drain()

    async def read():
        return json.loads(await asyncio.wait_for(process.stdout.readline(), 15))

    try:
        await request(1, "initialize", {"protocolVersion": 1})
        assert (await read())["id"] == 1
        await request(2, "session/new", {"cwd": str(tmp_path), "mcpServers": []})
        response = await read()
        assert response["id"] == 2
        update = await read()
        assert update["params"]["sessionId"] == response["result"]["sessionId"]
        commands = update["params"]["update"]["availableCommands"]
        assert {item["name"] for item in commands} == {"status", "permissions"}
    finally:
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 15)
