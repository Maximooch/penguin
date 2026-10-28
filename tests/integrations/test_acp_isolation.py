"""Concurrent ACP roots own mutable runtimes, services and persisted state."""

import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from acp.stdio import spawn_stdio_connection
from test_acp_sessions import PersistentCore
from test_acp_wire import _CLI_AGENT

from penguin.cli.events import EventBus
from penguin.core_runtime.isolation import RuntimeServices
from penguin.integrations.acp.isolated import IsolatedACPAgent, Runtime
from penguin.integrations.acp.server import PenguinACPAgent
from penguin.security.approval import get_approval_manager
from penguin.security.question import get_question_manager
from penguin.system.execution_context import get_current_execution_context
from penguin.system.message_bus import MessageBus
from penguin.tools.tool_manager import ToolManager


async def setup(tmp_path):
    created = []

    async def factory():
        services = RuntimeServices()
        with services.activate():
            core = PersistentCore(tmp_path / "store")
            core.event_bus = EventBus.get_sync()
            core.tool_manager = ToolManager(
                {"workspace_path": str(tmp_path)}, lambda *_: None, fast_startup=True
            )
            core.tool_manager._core = core
            core.abort_session = AsyncMock()
            core.model_config = SimpleNamespace(vision_enabled=False)
            core.list_available_models = lambda: [{"id": "other", "name": "Other"}]
            core.resolve_request_runtime = AsyncMock(
                return_value=(core.model_config, object())
            )
            runtime = Runtime(
                PenguinACPAgent(core, allowed_roots=(tmp_path,)), services
            )
            created.append(runtime)
            return runtime

    router = IsolatedACPAgent(await factory(), factory)
    conn = AsyncMock()
    router.on_connect(conn)
    await router.initialize(1)
    return router, conn, created


def test_runtime_services_are_context_local_and_default_survives():
    from penguin.llm.api_client import ConnectionPoolManager
    from penguin.multi.executor import AgentExecutor, get_executor, set_executor

    default = get_approval_manager()
    first, second = RuntimeServices(), RuntimeServices()
    with first.activate():
        approvals = get_approval_manager()
        questions = get_question_manager()
        events = EventBus.get_sync()
        messages = MessageBus.get_instance()
        pool = ConnectionPoolManager.get_instance()
        assert get_executor() is None
        executor = AgentExecutor(SimpleNamespace())
        set_executor(executor)
        assert get_executor() is executor
        with second.activate():
            assert get_approval_manager() is not approvals
            assert get_question_manager() is not questions
            assert EventBus.get_sync() is not events
            assert MessageBus.get_instance() is not messages
            assert ConnectionPoolManager.get_instance() is not pool
            assert get_executor() is None
        assert get_executor() is executor
        assert get_approval_manager() is approvals
    assert get_approval_manager() is default


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["cancel", "close"])
async def test_overlapping_runtime_tools_models_cancel_and_history(tmp_path, stop):
    router, _conn, _created = await setup(tmp_path)
    try:
        first = (await router.new_session(str(tmp_path))).session_id
        second = (await router.new_session(str(tmp_path))).session_id
        assert router.roots[first].agent.core is not router.roots[second].agent.core
        entered = {sid: asyncio.Event() for sid in [first, second]}
        release = {sid: asyncio.Event() for sid in [first, second]}
        contexts = {}
        for sid in [first, second]:
            core = router.roots[sid].agent.core

            async def process(
                text, *, conversation_id, stream_callback, _core=core, **kwargs
            ):
                context = get_current_execution_context()
                contexts[conversation_id] = context
                entered[conversation_id].set()
                await release[conversation_id].wait()
                result = await _core.tool_manager.execute_tool_async(
                    "write_file",
                    {
                        "path": str(tmp_path / (conversation_id + ".txt")),
                        "content": conversation_id,
                    },
                )
                assert "error" not in json.loads(result)
                return await PersistentCore.process(
                    _core,
                    text,
                    conversation_id=conversation_id,
                    stream_callback=stream_callback,
                )

            core.process = process
        tasks = {
            sid: asyncio.create_task(router.prompt(sid, [text_block(sid)]))
            for sid in [first, second]
        }
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in entered.values())), 5)
        with pytest.raises(RequestError):
            await router.set_config_option("model", first, "other")
        if stop == "close":
            await router.close_session(first)
        else:
            await router.cancel(first)
        release[second].set()
        results = await asyncio.gather(*tasks.values())
        assert results[0].stop_reason == "cancelled"
        assert results[1].stop_reason == "end_turn"
        assert not (tmp_path / (first + ".txt")).exists()
        assert (tmp_path / (second + ".txt")).read_text() == second
        assert contexts[first].session_id == first
        assert contexts[second].session_id == second
        if stop == "close":
            await router.load_session(str(tmp_path), first)
        await router.set_config_option("model", first, "other")
        assert router.roots[first].agent.sessions[first].model_id == "other"
        assert router.roots[second].agent.sessions[second].model_id == "default"
        listed = await router.list_sessions()
        assert {s.session_id for s in listed.sessions} == {first, second}
        await router.close_session(second)
        await router.load_session(str(tmp_path), second)
        assert (
            router.roots[second].agent._registry.get(second).messages[-1].content
            == "previous=0"
        )
        assert router.roots[first].agent.sessions[first].model_id == "other"
    finally:
        await router.aclose()


@pytest.mark.asyncio
async def test_simultaneous_permission_requests_do_not_cross_roots(tmp_path):
    from acp.schema import AllowedOutcome, RequestPermissionResponse

    from penguin.security.permission_engine import PermissionResult

    router, conn, _ = await setup(tmp_path)
    pending = {}

    async def permission(**kwargs):
        future = asyncio.get_running_loop().create_future()
        pending[kwargs["session_id"]] = future
        return await future

    conn.request_permission.side_effect = permission
    try:
        ids = [(await router.new_session(str(tmp_path))).session_id for _ in range(2)]
        for sid in ids:
            core = router.roots[sid].agent.core
            core.tool_manager._permission_enabled = True
            core.tool_manager.check_tool_permission = lambda *_: (
                PermissionResult.ASK,
                "confirm",
            )

            async def process(*args, _core=core, **kwargs):
                sid = get_current_execution_context().session_id
                result = await _core.tool_manager.execute_tool_async(
                    "write_file",
                    {"path": str(tmp_path / (sid + ".txt")), "content": sid},
                )
                return {"assistant_response": str(result)}

            core.process = process
        tasks = [
            asyncio.create_task(router.prompt(sid, [text_block("write")]))
            for sid in ids
        ]

        async def ready():
            while len(pending) < 2:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(ready(), 5)
        assert (
            router.roots[ids[0]].agent._approvals
            is not router.roots[ids[1]].agent._approvals
        )
        pending[ids[0]].set_result(
            RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id="allow_once")
            )
        )
        await router.cancel(ids[1])
        await asyncio.gather(*tasks)
        assert (tmp_path / (ids[0] + ".txt")).exists()
        assert not (tmp_path / (ids[1] + ".txt")).exists()
        assert not router.roots[ids[1]].agent._approvals.get_pending()
    finally:
        await router.aclose()


@pytest.mark.asyncio
async def test_actual_cli_isolated_mode_routes_two_sessions(tmp_path):
    updates = []

    async def handler(method, params, notification):
        if method == "session/update":
            updates.append(params)

    script = (
        _CLI_AGENT.replace("import os, sys, types", "import os, sys, types, asyncio")
        .replace(
            "class Core:\n",
            "class Core:\n    entered = 0\n    barrier = asyncio.Event()\n",
        )
        .replace(
            "        print('provider diagnostic')",
            """        print('provider diagnostic')
        if text == 'tools':
            Core.entered += 1
            if Core.entered == 2:
                Core.barrier.set()
            await asyncio.wait_for(Core.barrier.wait(), 3)
""",
        )
    )
    env = {
        **os.environ,
        "PENGUIN_WORKSPACE": str(tmp_path),
        "ACP_TEST_STORE": str(tmp_path / "store"),
        "PENGUIN_ACP_ISOLATED_SESSIONS": "1",
    }
    async with spawn_stdio_connection(
        handler, sys.executable, "-c", script, env=env
    ) as (conn, _):
        await conn.send_request("initialize", {"protocolVersion": 1})
        ids = [
            (
                await conn.send_request(
                    "session/new", {"cwd": str(tmp_path), "mcpServers": []}
                )
            )["sessionId"]
            for _ in range(2)
        ]
        await asyncio.gather(
            *(
                conn.send_request(
                    "session/prompt",
                    {"sessionId": sid, "prompt": [{"type": "text", "text": "tools"}]},
                )
                for sid in ids
            )
        )
        assert all(
            any(
                u["sessionId"] == sid and u["update"]["sessionUpdate"] == "tool_call"
                for u in updates
            )
            for sid in ids
        )
        sessions = await conn.send_request("session/list", {})
        assert {s["sessionId"] for s in sessions["sessions"]} == set(ids)


def test_actual_core_construction_has_separate_engine_and_message_routes(tmp_path):
    from penguin.config import Config
    from penguin.core import PenguinCore
    from penguin.llm.model_config import ModelConfig

    cores = []
    scopes = [RuntimeServices(), RuntimeServices()]
    for index, scope in enumerate(scopes):
        with scope.activate():
            model = ModelConfig(model="test-model", provider="openai")
            config = Config(workspace_path=tmp_path, model_config=model)
            manager = ToolManager(
                {"workspace_path": str(tmp_path)}, lambda *_: None, fast_startup=True
            )
            core = PenguinCore(
                config=config,
                model_config=model,
                api_client=SimpleNamespace(model_config=model),
                tool_manager=manager,
            )
            cores.append(core)
    try:
        assert cores[0].engine is not None and cores[1].engine is not None
        for attr in (
            "engine",
            "conversation_manager",
            "api_client",
            "model_config",
            "runtime_config",
            "action_executor",
            "event_bus",
            "tool_manager",
        ):
            assert getattr(cores[0], attr) is not getattr(cores[1], attr), attr
        buses = []
        for core, scope in zip(cores, scopes):
            with scope.activate():
                buses.append(MessageBus.get_instance())
                assert get_approval_manager() is not None
                assert core.engine.conversation_manager is core.conversation_manager
        assert buses[0] is not buses[1]
    finally:
        for core in cores:
            core.conversation_manager.session_manager._stop_auto_save.set()


@pytest.mark.asyncio
async def test_background_pipe_thread_retains_root_services_after_turn(tmp_path):
    import shlex
    import subprocess

    from penguin.core_runtime.process_notifications import prepare_process_step

    router, conn, _ = await setup(tmp_path)
    try:
        ids = [(await router.new_session(str(tmp_path))).session_id for _ in range(2)]
        finished = {sid: asyncio.Event() for sid in ids}
        wrong_scope = []
        for index, sid in enumerate(ids):
            runtime = router.roots[sid]
            core = runtime.agent.core
            owner_approvals = runtime.agent._approvals

            async def emit(event, data, _core=core, _owner=owner_approvals, _sid=sid):
                if get_approval_manager() is not _owner:
                    wrong_scope.append(_sid)
                await _core.event_bus.emit(event, data)
                if (
                    event == "opencode_event"
                    and data.get("type") == "notification.process.completed"
                ):
                    finished[_sid].set()

            core.emit_ui_event = emit

            async def process(*args, _core=core, _index=index, **kwargs):
                context = get_current_execution_context()
                prepare_process_step(
                    _core.tool_manager, SimpleNamespace(core=_core), context
                )
                argv = [
                    sys.executable,
                    "-c",
                    f"import time; time.sleep({0.15 if _index == 0 else 0.7}); "
                    "print('owned-output',flush=True)",
                ]
                command = (
                    subprocess.list2cmdline(argv)
                    if os.name == "nt"
                    else shlex.join(argv)
                )
                result = await asyncio.to_thread(
                    _core.tool_manager.process_tools.execute,
                    "process_start",
                    {"command": command},
                    context.as_dict(),
                )
                assert result.get("process_id")
                return {"assistant_response": "started"}

            core.process = process
        await asyncio.gather(
            *(router.prompt(sid, [text_block("start")]) for sid in ids)
        )
        await asyncio.wait_for(finished[ids[0]].wait(), 10)
        await router.close_session(ids[0])
        await asyncio.wait_for(finished[ids[1]].wait(), 10)
        assert not wrong_scope
        assert ids[1] in router.roots
        updates = conn.session_update.call_args_list
        for sid in ids:
            assert any(
                c.kwargs["session_id"] == sid
                and getattr(c.kwargs["update"], "tool_call_id", "").startswith(
                    "process:"
                )
                for c in updates
            )
    finally:
        await router.aclose()


@pytest.mark.asyncio
async def test_legacy_worker_thread_keeps_runtime_scope(tmp_path, monkeypatch):
    from penguin.tools.core import support

    captured = []
    monkeypatch.setattr(
        support,
        "enhanced_diff",
        lambda *a, **k: captured.append(get_approval_manager()) or "diff",
    )
    scope = RuntimeServices()
    with scope.activate():
        owner = get_approval_manager()
        manager = ToolManager(
            {"workspace_path": str(tmp_path)}, lambda *_: None, fast_startup=True
        )
        await asyncio.to_thread(
            manager._execute_enhanced_diff, {"file1": "a", "file2": "b"}
        )
    assert captured == [owner]


@pytest.mark.asyncio
async def test_runtime_limit_freed_by_close_and_saved_session_can_reload(tmp_path):
    router, _, _ = await setup(tmp_path)
    router.limit = 1
    try:
        sid = (await router.new_session(str(tmp_path))).session_id
        first = router.roots[sid]
        with pytest.raises(RequestError):
            await router.new_session(str(tmp_path))
        await router.close_session(sid)
        assert first.agent._closed
        assert sid not in router.roots
        await router.load_session(str(tmp_path), sid)
        assert router.roots[sid] is not first
        assert router.roots[sid].agent._registry.get(sid) is not None
    finally:
        await router.aclose()


@pytest.mark.asyncio
async def test_same_named_native_children_messages_and_approvals_are_isolated(
    tmp_path, monkeypatch
):
    from acp.schema import AllowedOutcome, RequestPermissionResponse

    from penguin.core_runtime import agent_lifecycle
    from penguin.multi.executor import get_executor
    from penguin.security.permission_engine import PermissionResult
    from penguin.system.message_bus import ProtocolMessage

    router, conn, _ = await setup(tmp_path)
    pending, inboxes, executors = {}, {}, {}
    registered = asyncio.Event()
    count = 0

    async def permission(**kwargs):
        future = asyncio.get_running_loop().create_future()
        pending[kwargs["session_id"]] = future
        return await future

    conn.request_permission.side_effect = permission
    monkeypatch.setattr(
        agent_lifecycle,
        "resolve_agent_execution_scope",
        lambda core, agent, **kw: {
            "session_id": kw["session_id"],
            "conversation_id": kw["session_id"],
            "directory": str(tmp_path),
            "project_root": str(tmp_path),
            "workspace_root": str(tmp_path),
            "agent_mode": "build",
        },
    )
    try:
        ids = [(await router.new_session(str(tmp_path))).session_id for _ in range(2)]
        for root in ids:
            core = router.roots[root].agent.core
            core.emit_ui_event = core.event_bus.emit
            core.tool_manager._permission_enabled = True
            core.tool_manager.check_tool_permission = lambda *_: (
                PermissionResult.ASK,
                "confirm",
            )
            inboxes[root] = []

            async def scoped_child(agent_id, prompt, _core=core, **kwargs):
                return await agent_lifecycle.run_agent_prompt_in_session(
                    _core, agent_id, prompt, **kwargs
                )

            core.run_agent_prompt_in_session = scoped_child

            async def process(
                text=None, *, agent_id=None, _core=core, _root=root, **kwargs
            ):
                nonlocal count
                if agent_id:
                    await registered.wait()
                    assert await MessageBus.get_instance().send(
                        ProtocolMessage(
                            sender="parent", recipient="worker", content=_root
                        )
                    )
                    result = await _core.tool_manager.execute_tool_async(
                        "write_file",
                        {
                            "path": str(tmp_path / (_root + "-child.txt")),
                            "content": _root,
                        },
                    )
                    return {"assistant_response": str(result)}

                async def receive(message):
                    inboxes[_root].append(message.content)

                MessageBus.get_instance().register_handler("worker", receive)
                count += 1
                if count == 2:
                    registered.set()
                executor = get_executor(_core)
                executors[_root] = executor
                await executor.spawn_agent(
                    "worker",
                    "write",
                    {"session_id": _root + "-child", "directory": str(tmp_path)},
                )
                return {"assistant_response": await executor.wait_for("worker")}

            core.process = process
        tasks = [
            asyncio.create_task(router.prompt(sid, [text_block("spawn")]))
            for sid in ids
        ]

        async def ready():
            while len(pending) != 2:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(ready(), 5)
        assert executors[ids[0]] is not executors[ids[1]]
        for sid in ids:
            assert sid + "-child" in router.roots[sid].agent._children.children
            assert inboxes[sid] == [sid]
        pending[ids[0]].set_result(
            RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id="allow_once")
            )
        )
        pending[ids[1]].set_result(
            RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id="reject_once")
            )
        )
        await asyncio.gather(*tasks)
        assert (tmp_path / (ids[0] + "-child.txt")).exists()
        assert not (tmp_path / (ids[1] + "-child.txt")).exists()
        assert all(
            executors[sid].get_status("worker")["state"] == "completed" for sid in ids
        )
    finally:
        await router.aclose()
