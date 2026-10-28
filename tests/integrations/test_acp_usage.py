"""Scoped context usage from Penguin's persisted-session telemetry."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.helpers import text_block
from test_acp_sessions import PersistentCore

from penguin.core_runtime.token_usage_runtime import get_session_token_usage
from penguin.integrations.acp.server import PenguinACPAgent


@pytest.mark.asyncio
async def test_real_session_usage_maps_to_context_not_cost(tmp_path):
    core = PersistentCore(tmp_path / "store")
    core.store.context_window = SimpleNamespace(max_context_window_tokens=128000)
    core._find_session_store = lambda sid: (core.store.load_session(sid), core.store)
    core.get_token_usage = lambda *, session_id: get_session_token_usage(
        core, session_id
    )
    original = core.process

    async def process(*args, **kwargs):
        result = await original(*args, **kwargs)
        core.store.load_session(kwargs["conversation_id"]).messages[-1].tokens = 17
        return result

    core.process = process
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    agent.on_connect(conn)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        await agent.prompt(sid, [text_block("hello")])
        usage = [
            c.kwargs["update"]
            for c in conn.session_update.call_args_list
            if c.kwargs["update"].session_update == "usage_update"
        ]
        assert len(usage) == 1
        assert (usage[0].used, usage[0].size, usage[0].cost) == (17, 128000, None)
        history = agent._registry.history(agent._registry.get(sid))
        assert any(u.session_update == "usage_update" for u in history)
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_missing_global_and_invalid_usage_do_not_leak_or_fabricate(tmp_path):
    core = PersistentCore(tmp_path / "store")
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    agent.on_connect(conn)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        agent.sessions[sid].running = True
        for extra in (
            {"scope": "runtime"},
            {"session_id": "foreign"},
            {"current_total_tokens": -1},
            {"max_context_window_tokens": 0},
            {"current_total_tokens": True},
        ):
            await core.event_bus.emit(
                "token_update",
                {
                    "scope": "session",
                    "session_id": sid,
                    "current_total_tokens": 12,
                    "max_context_window_tokens": 100,
                    **extra,
                },
            )
        assert not conn.session_update.called
    finally:
        agent.close()
