"""Public async ToolManager dispatch contracts."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.security.approval import get_approval_manager
from penguin.security.permission_engine import PermissionResult
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionExecutor, ActionType, CodeActAction


@pytest.mark.asyncio
async def test_foreground_subagent_executes_on_the_callers_event_loop() -> None:
    """Foreground native dispatch must not create or block a second event loop."""

    caller_loop = asyncio.get_running_loop()
    heartbeat_completed = asyncio.Event()
    observed_loop: asyncio.AbstractEventLoop | None = None

    class _Core:
        def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
            del agent_id, kwargs

        async def publish_sub_agent_session_created(
            self,
            agent_id: str,
            **kwargs: Any,
        ) -> dict[str, Any]:
            del agent_id, kwargs
            return {
                "id": "session_child",
                "directory": "/tmp/penguin-async-dispatch",
                "agent_mode": "implement",
            }

        async def run_agent_prompt_in_session(
            self,
            agent_id: str,
            prompt: str,
            **kwargs: Any,
        ) -> dict[str, str]:
            del agent_id, prompt, kwargs
            nonlocal observed_loop
            observed_loop = asyncio.get_running_loop()
            await asyncio.sleep(0.01)
            return {"assistant_response": "child completed"}

    async def _heartbeat() -> None:
        await asyncio.sleep(0)
        heartbeat_completed.set()

    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    manager.set_core(_Core())

    heartbeat = asyncio.create_task(_heartbeat())
    raw_result = await manager.execute_tool_async(
        "spawn_sub_agent",
        {
            "id": "child-agent",
            "initial_prompt": "Complete one deterministic turn.",
            "background": False,
        },
    )
    await heartbeat

    result = json.loads(raw_result)
    assert result["status"] == "ok"
    assert observed_loop is caller_loop
    assert heartbeat_completed.is_set()


@pytest.mark.asyncio
async def test_background_subagents_are_isolated_per_tool_manager() -> None:
    """Background runs must survive return and never share executor state."""

    class _Core:
        def __init__(self, response: str) -> None:
            self.response = response
            self.completed = asyncio.Event()

        def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
            del agent_id, kwargs

        async def publish_sub_agent_session_created(
            self,
            agent_id: str,
            **kwargs: Any,
        ) -> dict[str, Any]:
            del kwargs
            return {
                "id": f"session_{self.response}",
                "directory": "/tmp/penguin-async-dispatch",
                "agent_mode": "implement",
                "agent_id": agent_id,
            }

        async def run_agent_prompt_in_session(
            self,
            agent_id: str,
            prompt: str,
            **kwargs: Any,
        ) -> dict[str, str]:
            del agent_id, prompt, kwargs
            await asyncio.sleep(0)
            self.completed.set()
            return {"assistant_response": self.response}

    cores = (_Core("first"), _Core("second"))
    managers = tuple(
        ToolManager(
            {"diagnostics": {"enabled": False}},
            lambda _error, _context: None,
        )
        for _core in cores
    )
    for manager, core in zip(managers, cores):
        manager.set_core(core)

    results = await asyncio.gather(
        *(
            manager.execute_tool_async(
                "spawn_sub_agent",
                {
                    "id": "same-child-name",
                    "initial_prompt": "Complete one background turn.",
                    "background": True,
                },
            )
            for manager in managers
        )
    )
    await asyncio.wait_for(
        asyncio.gather(*(core.completed.wait() for core in cores)),
        timeout=1.0,
    )

    payloads = [json.loads(raw_result) for raw_result in results]
    assert [payload["status"] for payload in payloads] == ["ok", "ok"]
    assert all(payload["background"] is True for payload in payloads)


@pytest.mark.asyncio
async def test_sync_api_rejects_async_tools_on_a_running_loop() -> None:
    """The sync API must fail explicitly instead of blocking the event loop."""

    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )

    with pytest.raises(RuntimeError, match="execute_tool_async"):
        manager.execute_tool("spawn_sub_agent", {"id": "child-agent"})


@pytest.mark.asyncio
async def test_disabled_subagents_are_hidden_and_denied_before_mutation() -> None:
    """Subagent policy must govern schemas and execution, not prompt wording."""

    class _Core:
        def __init__(self) -> None:
            self.create_calls = 0

        def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
            del agent_id, kwargs
            self.create_calls += 1

    core = _Core()
    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    manager.set_core(core)
    context = ExecutionContext(
        session_id="session_parent",
        request_id="request_no_subagents",
        subagents_enabled=False,
    )

    with execution_context_scope(context):
        visible_names = {
            tool["name"]
            for tool in manager.get_responses_tools(include_web_search=False)
        }
        raw_result = await manager.execute_tool_async(
            "spawn_sub_agent",
            {"id": "forbidden-child", "background": True},
        )

    assert "spawn_sub_agent" not in visible_names
    result = json.loads(raw_result)
    assert result == {
        "error": "subagents_disabled",
        "tool": "spawn_sub_agent",
        "message": "Subagent tools are disabled for this request",
    }
    assert core.create_calls == 0


@pytest.mark.asyncio
async def test_disabled_subagents_are_denied_for_actionxml() -> None:
    """ActionXML must enforce the same server-side subagent capability."""

    class _Core:
        def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
            raise AssertionError(f"unexpected mutation for {agent_id}: {kwargs}")

    core = _Core()
    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    manager.set_core(core)
    executor = ActionExecutor(
        tool_manager=manager,
        task_manager=SimpleNamespace(),
        conversation_system=SimpleNamespace(core=core),
    )

    with execution_context_scope(ExecutionContext(subagents_enabled=False)):
        raw_result = await executor.execute_action(
            CodeActAction(
                action_type=ActionType.SPAWN_SUB_AGENT,
                params='{"id":"forbidden-actionxml-child"}',
            )
        )

    assert json.loads(raw_result) == {
        "error": "subagents_disabled",
        "tool": "spawn_sub_agent",
        "message": "Subagent tools are disabled for this request",
    }


@pytest.mark.asyncio
async def test_foreground_child_failure_is_returned_as_a_tool_error() -> None:
    """A failed child turn must never be reported as a successful spawn."""

    class _Core:
        def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
            del agent_id, kwargs

        async def publish_sub_agent_session_created(
            self,
            agent_id: str,
            **kwargs: Any,
        ) -> dict[str, Any]:
            del agent_id, kwargs
            return {"id": "session_failed_child"}

        async def run_agent_prompt_in_session(
            self,
            agent_id: str,
            prompt: str,
            **kwargs: Any,
        ) -> dict[str, str]:
            del agent_id, prompt, kwargs
            return {"error": "provider failed before output"}

    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    manager.set_core(_Core())

    raw_result = await manager.execute_tool_async(
        "spawn_sub_agent",
        {
            "id": "failed-child",
            "initial_prompt": "Fail deterministically.",
            "background": False,
        },
    )

    assert json.loads(raw_result) == {
        "error": "child_execution_failed",
        "agent_id": "failed-child",
        "session_id": "session_failed_child",
        "details": "provider failed before output",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("child_result", "expected_error", "expected_details"),
    [
        (
            {"status": "error", "error": "provider rejected request"},
            "child_execution_failed",
            "provider rejected request",
        ),
        (
            {"status": "ok", "aborted": True},
            "child_execution_aborted",
            "Child execution was aborted",
        ),
    ],
)
async def test_foreground_child_terminal_payload_is_not_reported_as_ok(
    child_result: dict[str, Any],
    expected_error: str,
    expected_details: str,
) -> None:
    """Returned terminal state is authoritative even when no exception is raised."""

    class _Core:
        def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
            del agent_id, kwargs

        async def publish_sub_agent_session_created(
            self,
            agent_id: str,
            **kwargs: Any,
        ) -> dict[str, str]:
            del agent_id, kwargs
            return {"id": "session_terminal_child"}

        async def run_agent_prompt_in_session(
            self,
            agent_id: str,
            prompt: str,
            **kwargs: Any,
        ) -> dict[str, Any]:
            del agent_id, prompt, kwargs
            return child_result

    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    manager.set_core(_Core())

    raw_result = await manager.execute_tool_async(
        "spawn_sub_agent",
        {
            "id": "terminal-child",
            "initial_prompt": "Return a terminal payload.",
            "background": False,
        },
    )

    result = json.loads(raw_result)
    assert result["error"] == expected_error
    assert result["details"] == expected_details
    assert result["agent_id"] == "terminal-child"
    assert result["session_id"] == "session_terminal_child"


@pytest.mark.asyncio
async def test_preapproved_async_tool_stays_on_callers_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approval must not redirect coroutine execution through the sync API."""

    caller_loop = asyncio.get_running_loop()
    observed_loop: asyncio.AbstractEventLoop | None = None
    approval_manager = get_approval_manager()
    approval_manager.reset()
    approval_manager.pre_approve(
        "tool.spawn_sub_agent",
        session_id="session_approved",
    )

    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    manager._permission_enabled = True
    monkeypatch.setattr(
        manager,
        "check_tool_permission",
        lambda *_args, **_kwargs: (PermissionResult.ASK, "approval required"),
    )

    async def _spawn(_tool_input: dict[str, Any]) -> str:
        nonlocal observed_loop
        observed_loop = asyncio.get_running_loop()
        return json.dumps({"status": "ok"})

    monkeypatch.setattr(manager, "_execute_spawn_sub_agent", _spawn)

    try:
        raw_result = await manager.execute_tool_async(
            "spawn_sub_agent",
            {"id": "approved-child"},
            {"session_id": "session_approved"},
        )
    finally:
        approval_manager.reset()

    assert json.loads(raw_result)["status"] == "ok"
    assert observed_loop is caller_loop


@pytest.mark.asyncio
async def test_invalid_model_overrides_are_rejected_before_spawn() -> None:
    """Malformed optional configuration must not be silently discarded."""

    class _Core:
        def __init__(self) -> None:
            self.created = False

        def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
            del agent_id, kwargs
            self.created = True

    core = _Core()
    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    manager.set_core(core)

    raw_result = await manager.execute_tool_async(
        "spawn_sub_agent",
        {"id": "invalid-config", "model_overrides": ["not", "a", "mapping"]},
    )

    result = json.loads(raw_result)
    assert result["error"] == "invalid_spawn_request"
    assert "model_overrides must be an object" in result["details"]
    assert core.created is False


@pytest.mark.asyncio
async def test_tool_manager_shutdown_cancels_and_awaits_background_agents() -> None:
    """Server shutdown must leave no child task running on the event loop."""

    started = asyncio.Event()
    cancelled = asyncio.Event()

    class _Core:
        def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
            del agent_id, kwargs

        async def publish_sub_agent_session_created(
            self,
            agent_id: str,
            **kwargs: Any,
        ) -> dict[str, str]:
            del agent_id, kwargs
            return {"id": "session_shutdown_child"}

        async def run_agent_prompt_in_session(
            self,
            agent_id: str,
            prompt: str,
            **kwargs: Any,
        ) -> dict[str, str]:
            del agent_id, prompt, kwargs
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    manager.set_core(_Core())
    await manager.execute_tool_async(
        "spawn_sub_agent",
        {
            "id": "shutdown-child",
            "initial_prompt": "Wait until shutdown.",
            "background": True,
        },
    )
    await asyncio.wait_for(started.wait(), timeout=1.0)

    cancelled_count = await manager.shutdown_background_agents()

    assert cancelled_count == 1
    assert cancelled.is_set()
    raw_status = await manager.execute_tool_async(
        "get_agent_status",
        {"id": "shutdown-child"},
    )
    assert json.loads(raw_status)["agent"]["state"] == "cancelled"
