"""Offline regressions for process/subagent reports #126 through #130."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from penguin.engine import Engine, EngineSettings, LoopState
from penguin.multi.executor import AgentExecutor
from penguin.multi.mailbox import AgentMailbox
from penguin.system.message_bus import MessageBus, ProtocolMessage
from penguin.system.state import MessageCategory, Session, create_message
from penguin.tools.core.conversation_archive import open_session, search
from penguin.tools.process_runtime import ProcessRuntime
from penguin.tools.process_tools import ProcessTools
from penguin.tools.runtime import ToolCall, execute_tool_calls_serially
from penguin.tools.tool_manager import ToolManager


def test_mailbox_is_session_scoped_and_retries_failed_save_without_duplicate():
    mailbox = AgentMailbox()
    session = SimpleNamespace(id="target", messages=[])

    def append(**kwargs):
        session.messages.append(SimpleNamespace(**kwargs))

    manager = SimpleNamespace(
        conversation=SimpleNamespace(session=session, add_message=append),
        save=Mock(return_value=False),
    )
    mailbox.enqueue(
        "child",
        "target",
        ProtocolMessage("parent", "child", "steer", message_id="receipt"),
    )
    session.id = "other"
    mailbox.deliver("child", manager)
    assert not session.messages
    session.id = "target"
    with pytest.raises(RuntimeError, match="persist"):
        mailbox.deliver("child", manager)
    assert mailbox.status("child")["queued_messages"] == 1
    assert "last_delivered_message_id" not in mailbox.status("child")
    manager.save.return_value = True
    mailbox.deliver("child", manager)
    assert len(session.messages) == 1
    assert mailbox.status("child")["queued_messages"] == 0


@pytest.mark.skipif(os.name != "posix", reason="POSIX process tool contract")
def test_status_tool_registry_permissions_and_non_consuming_dispatch(
    tmp_path, monkeypatch
):
    from penguin.security.permission_engine import Operation
    from penguin.security.tool_permissions import get_tool_operations

    monkeypatch.setenv("PENGUIN_YOLO", "1")
    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    manager._process_runtime = ProcessRuntime(log_dir=tmp_path)
    assert get_tool_operations("process_status") == [Operation.PROCESS_INSPECT]
    assert "process_status" in {tool["name"] for tool in manager._define_tool_schemas()}
    context = {"session_id": "session", "agent_id": "parent"}
    try:
        result = manager.execute_tool("process_start", {"command": "read go"}, context)
        status = manager.execute_tool(
            "process_status", {"process_id": result["process_id"]}, context
        )
        assert status["process_status"] == "running"
        stopped = manager.execute_tool(
            "process_stop", {"process_id": result["process_id"]}, context
        )
        assert stopped["process_status"] == "exited"
        status = manager.execute_tool(
            "process_status", {"process_id": result["process_id"]}, context
        )
        assert status["completion_reason"] == "cancelled"
        assert status["returncode"] is not None
    finally:
        manager.process_tools.cleanup()


@pytest.mark.skipif(os.name != "posix", reason="POSIX shell process contract")
def test_process_survives_turn_loops_and_status_preserves_output(tmp_path, monkeypatch):
    monkeypatch.delenv("PENGUIN_TOOL_TIMEOUT", raising=False)
    runtime = ProcessRuntime(log_dir=tmp_path)
    service = ProcessTools(runtime)
    owner = {"session_id": "session", "agent_id": "parent"}
    try:
        started = service.execute(
            "process_start", {"command": "read go; printf done; exit 7"}, owner
        )
        pid = started["process_id"]
        state = LoopState()
        for turn in range(4):

            async def poll():
                return service.execute(
                    "process_poll",
                    {"process_id": pid, "since_sequence": 0, "wait_ms": 0},
                    {**owner, "tool_call_id": f"poll-{turn}"},
                )

            result = asyncio.run(poll())  # Independent assistant turn loops.
            assert result["process_status"] == "running"
            assert result["output"] == ""
            assert state.check_empty_tool_only("", [result]) == (False, None)
        assert (
            service.execute(
                "process_status", {"process_id": pid}, {**owner, "session_id": "other"}
            )["error"]
            == "unknown_process_id"
        )
        runtime.write_stdin(pid, "go\n")
        record = runtime._processes[pid]
        record.reader.join(3)
        assert not record.reader.is_alive()
        for _ in range(2):
            status = service.execute("process_status", {"process_id": pid}, owner)
            assert status["process_status"] == "exited"
            assert status["returncode"] == 7
            assert status["output"] == ""
        result = service.execute(
            "process_poll", {"process_id": pid, "wait_ms": 0}, owner
        )
        assert result["output"] == "[stdout] done"
        assert result["returncode"] == 7
    finally:
        service.cleanup()


@pytest.mark.asyncio
async def test_distinct_silent_commands_and_genuine_silent_loop():
    state = LoopState()
    for command in ("mkdir a", "chmod 700 a", "git add a"):
        result = await execute_tool_calls_serially(
            [
                ToolCall(
                    id=command,
                    name="execute_command",
                    source="responses",
                    arguments={"command": command},
                )
            ],
            lambda call: "",
        )
        assert state.check_empty_tool_only("", result) == (False, None)
    for index in range(3):
        result = await execute_tool_calls_serially(
            [
                ToolCall(
                    id=str(index),
                    name="execute_command",
                    source="responses",
                    arguments={"command": "true"},
                )
            ],
            lambda call: {
                "action": "execute_command",
                "command": "true",
                "process_id": str(index),
                "process_status": "exited",
                "returncode": 0,
                "output": "",
            },
        )
        stop, _ = state.check_empty_tool_only("", result)
        assert stop is (index == 2)


@pytest.mark.skipif(os.name != "posix", reason="descriptor-safe archive reader")
@pytest.mark.parametrize("stopped", [False, True])
def test_archive_pages_persisted_tool_schema(tmp_path, stopped):
    folder = tmp_path / "conversations" / "child"
    folder.mkdir(parents=True)
    session = Session(id="child-session")
    for index in range(87):
        session.messages.append(
            create_message(
                "tool" if 20 <= index < 28 else "assistant",
                f"message-{index}",
                MessageCategory.SYSTEM_OUTPUT
                if 20 <= index < 28
                else MessageCategory.DIALOG,
            )
        )
    (folder / "child-session.json").write_text(session.to_json(), encoding="utf-8")
    # Both active saves and the final stopped archive use Session.to_dict schema.
    if stopped:
        session.metadata["stopped"] = True
        (folder / "child-session.json").write_text(session.to_json(), encoding="utf-8")
    hit = search(tmp_path, "message-30", agent_id="child")["results"][0]
    assert hit["message_index"] == 30
    page = open_session(
        tmp_path, "child-session", agent_id="child", message_start=20, limit=8
    )
    assert page["total_messages"] == 87
    assert page["next_message_start"] == 28
    assert [m["content"] for m in page["messages"]] == [
        f"message-{i}" for i in range(20, 28)
    ]
    assert {m["role"] for m in page["messages"]} == {"tool"}


def make_manager(executor):
    manager = ToolManager.__new__(ToolManager)
    manager._core = executor._core
    manager._agent_executor = executor
    return manager


@pytest.mark.asyncio
async def test_running_child_receives_steering_at_next_step(monkeypatch):
    monkeypatch.setattr(MessageBus, "_instance", MessageBus())
    transcript = []
    session = SimpleNamespace(id="child-session", messages=transcript)

    def append(**kwargs):
        transcript.append(SimpleNamespace(**kwargs))

    cm = SimpleNamespace(
        conversation=SimpleNamespace(session=session, add_message=append),
        save=lambda: True,
    )
    engine = Engine(EngineSettings(), cm, Mock(), Mock(), Mock())
    engine.register_agent(agent_id="child", conversation_manager=cm)
    monkeypatch.setattr(engine, "get_conversation_manager", lambda aid: cm)
    cm.conversation.get_formatted_messages = lambda: [
        {"role": item.role, "content": item.content} for item in transcript
    ]
    monkeypatch.setattr(
        engine,
        "_resolve_components",
        lambda aid: (cm, SimpleNamespace(model_config=None), Mock(), Mock()),
    )
    monkeypatch.setattr(engine, "_get_runtime_model_config", lambda: None)
    monkeypatch.setattr(engine, "_apply_agent_mode_notice", lambda messages: messages)
    monkeypatch.setattr(engine, "_log_context_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(engine, "_persist_llm_request_lifecycle", lambda *args: None)
    provider_requests = []

    async def provider(client, messages, *args):
        provider_requests.append(messages)
        raise RuntimeError("fake provider boundary")

    monkeypatch.setattr(engine, "_call_llm_with_retry", provider)
    entered, proceed = asyncio.Event(), asyncio.Event()

    async def run(**kwargs):
        entered.set()
        await proceed.wait()  # Child is inside a tool/provider call.
        with pytest.raises(RuntimeError, match="fake provider boundary"):
            await engine._llm_step(agent_id="child", tools_enabled=False)
        return {"assistant_response": transcript[-1].content}

    executor = AgentExecutor(SimpleNamespace(process=run, engine=engine))
    manager = make_manager(executor)
    await executor.spawn_agent("child", "work")
    await entered.wait()
    sent = json.loads(
        await manager._execute_send_message(
            {"target": "child", "content": "change direction"}
        )
    )
    assert sent["status"] == "ok"
    assert transcript == []
    assert executor.get_status("child")["messaging"]["queued_messages"] == 1
    busy = json.loads(
        await manager._execute_delegate(
            {"child": "child", "content": "duplicate", "background": True}
        )
    )
    assert busy["code"] == "agent_busy"
    proceed.set()
    await executor.wait_for("child")
    assert transcript[0].content == "change direction"
    assert provider_requests[0][-1] == {"role": "user", "content": "change direction"}
    assert transcript[0].metadata["sender"] == "default"
    status = executor.get_status("child")
    assert (
        status["messaging"]["last_delivered_message_id"] == sent["message_ids"]["child"]
    )
    assert status["finished_at"] >= status["started_at"]
    assert status["messaging"]["queued_messages"] == 0
    missing = json.loads(
        await manager._execute_send_message({"target": "missing", "content": "test"})
    )
    assert missing["error"] == "message_delivery_failed"
    assert missing["recovery"]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["complete", "cancel", "cancel_wait"])
async def test_wait_wakes_without_polling_and_does_not_cancel_children(action):
    entered, finish = asyncio.Event(), asyncio.Event()

    async def run(**kwargs):
        entered.set()
        await finish.wait()
        return "done"

    executor = AgentExecutor(SimpleNamespace(process=run))
    manager = make_manager(executor)
    await executor.spawn_agent("child", "work")
    await entered.wait()
    executor.get_status = Mock(wraps=executor.get_status)
    wait = asyncio.create_task(
        manager._execute_wait_for_agents({"ids": ["child"], "timeout": 5})
    )
    await asyncio.sleep(0.02)
    if action == "cancel_wait":
        wait.cancel()
        with pytest.raises(asyncio.CancelledError):
            await wait
        assert executor.get_status("child")["state"] == "running"
        await executor.cancel_all()
    else:
        if action == "complete":
            finish.set()
        else:
            await executor.cancel("child")
        result = json.loads(await asyncio.wait_for(wait, 0.5))
        assert result["status"] == "ok"
        assert result["poll_count"] == 2
    assert executor.get_status.call_count <= 4


@pytest.mark.asyncio
@pytest.mark.slow
async def test_two_children_sixty_second_wait_has_two_status_scans():
    finish = asyncio.Event()

    async def run(**kwargs):
        await finish.wait()

    executor = AgentExecutor(SimpleNamespace(process=run))
    manager = make_manager(executor)
    await executor.spawn_agent("one", "work")
    await executor.spawn_agent("two", "work")
    executor.get_status = Mock(wraps=executor.get_status)
    try:
        result = json.loads(
            await manager._execute_wait_for_agents(
                {"ids": ["one", "two"], "timeout": 60}
            )
        )
        assert result["status"] == "timeout"
        assert 60 <= result["elapsed_seconds"] < 61
        assert result["poll_count"] == 2
        assert executor.get_status.call_count == 4
        assert executor.running_count == 2
    finally:
        await executor.cancel_all()
