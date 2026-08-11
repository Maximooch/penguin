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


async def _wait_for_pending_approval(session_id: str) -> str:
    """Return the first approval ID created for a test session."""
    manager = get_approval_manager()
    for _ in range(200):
        pending = manager.get_pending(session_id=session_id)
        if pending:
            return pending[0].id
        await asyncio.sleep(0.005)
    raise AssertionError("Approval request was never created")


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
async def test_default_async_approval_still_returns_pending_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing HTTP-style contexts must not start waiting implicitly."""
    approval_manager = get_approval_manager()
    approval_manager.reset()
    calls = 0
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

    async def _memory_search(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"status": "executed"}

    monkeypatch.setattr(manager, "perform_memory_search", _memory_search)
    raw_result = await manager.execute_tool_async(
        "memory_search",
        {"query": "penguin"},
        {"session_id": "session_default_pending"},
    )

    result = json.loads(raw_result)
    assert result["status"] == "pending_approval"
    assert calls == 0
    approval_manager.reset()


def test_request_scoped_read_only_mode_blocks_mutating_tools() -> None:
    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )

    result, reason = manager.check_tool_permission(
        "write_file",
        {"path": "notes.txt", "content": "mutate"},
        {"permission_mode": "read_only"},
    )

    assert result == PermissionResult.DENY
    assert "read-only" in reason


@pytest.mark.parametrize(
    ("decision", "expected"),
    [("ask", PermissionResult.ASK), ("deny", PermissionResult.DENY)],
)
def test_request_approval_policy_governs_shell_tools(
    decision: str,
    expected: PermissionResult,
) -> None:
    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )

    result, _reason = manager.check_tool_permission(
        "execute_command",
        {"command": "pwd"},
        {"approval_policy": {"default": decision, "shell": decision}},
    )

    assert result == expected


@pytest.mark.asyncio
async def test_remote_deny_policy_never_creates_approval_or_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approval_manager = get_approval_manager()
    approval_manager.reset()
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

    async def _unexpected_execution(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("deny policy executed the tool")

    monkeypatch.setattr(manager, "perform_memory_search", _unexpected_execution)
    result = json.loads(
        await manager.execute_tool_async(
            "memory_search",
            {"query": "penguin"},
            {
                "session_id": "session_remote_deny",
                "approval_policy": {"default": "deny"},
            },
        )
    )

    assert result["error"] == "permission_denied"
    assert approval_manager.get_pending(session_id="session_remote_deny") == []
    approval_manager.reset()


@pytest.mark.asyncio
async def test_async_tool_resumes_once_after_opt_in_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An opted-in async call continues once after the matching approval."""
    approval_manager = get_approval_manager()
    approval_manager.reset()
    calls = 0
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
    monkeypatch.setattr(manager, "add_message_to_search", lambda _message: None)

    async def _memory_search(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"status": "executed"}

    monkeypatch.setattr(manager, "perform_memory_search", _memory_search)
    session_id = "session_async_resume"
    execution = asyncio.create_task(
        manager.execute_tool_async(
            "memory_search",
            {"query": "penguin"},
            {
                "session_id": session_id,
                "approval_policy": {
                    "wait_for_resolution": True,
                    "timeout_seconds": 1.0,
                },
            },
        )
    )

    request_id = await _wait_for_pending_approval(session_id)
    await asyncio.sleep(0)
    assert execution.done() is False
    assert approval_manager.approve(request_id) is not None
    assert approval_manager.approve(request_id) is None
    result = await asyncio.wait_for(execution, timeout=1.0)

    assert result == {"status": "executed"}
    assert calls == 1
    approval_manager.reset()


@pytest.mark.asyncio
@pytest.mark.parametrize("resolution", ["deny", "expire"])
async def test_denied_or_expired_approval_never_executes_async_tool(
    monkeypatch: pytest.MonkeyPatch,
    resolution: str,
) -> None:
    """Terminal non-approval outcomes must never mutate through the tool."""
    approval_manager = get_approval_manager()
    approval_manager.reset()
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

    async def _unexpected_execution(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("denied or expired tool executed")

    monkeypatch.setattr(manager, "perform_memory_search", _unexpected_execution)
    session_id = f"session_async_{resolution}"
    timeout_seconds = 1.0 if resolution == "deny" else 0.01
    execution = asyncio.create_task(
        manager.execute_tool_async(
            "memory_search",
            {"query": "penguin"},
            {
                "session_id": session_id,
                "approval_policy": {
                    "wait_for_resolution": True,
                    "timeout_seconds": timeout_seconds,
                },
            },
        )
    )

    request_id = await _wait_for_pending_approval(session_id)
    if resolution == "deny":
        assert approval_manager.deny(request_id) is not None
    result = json.loads(await asyncio.wait_for(execution, timeout=1.0))

    expected_error = "approval_denied" if resolution == "deny" else "approval_expired"
    assert result["error"] == expected_error
    assert approval_manager.approve(request_id) is None
    approval_manager.reset()


@pytest.mark.asyncio
async def test_sync_tool_resumes_once_without_blocking_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synchronous tool waits and runs in worker threads, exactly once."""
    approval_manager = get_approval_manager()
    approval_manager.reset()
    calls = 0
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
    monkeypatch.setattr(manager, "add_message_to_search", lambda _message: None)

    def _grep_search(*_args: Any, **_kwargs: Any) -> str:
        nonlocal calls
        calls += 1
        return "executed"

    monkeypatch.setattr(manager, "perform_grep_search", _grep_search)
    session_id = "session_sync_resume"
    execution = asyncio.create_task(
        manager.execute_tool_async(
            "grep_search",
            {"pattern": "penguin"},
            {
                "session_id": session_id,
                "approval_policy": {
                    "wait_for_resolution": True,
                    "timeout_seconds": 1.0,
                },
            },
        )
    )

    request_id = await _wait_for_pending_approval(session_id)
    heartbeat_ran = False

    async def _heartbeat() -> None:
        nonlocal heartbeat_ran
        await asyncio.sleep(0)
        heartbeat_ran = True

    await _heartbeat()
    assert heartbeat_ran is True
    assert approval_manager.approve(request_id) is not None
    result = await asyncio.wait_for(execution, timeout=1.0)

    assert result == "executed"
    assert calls == 1
    approval_manager.reset()


@pytest.mark.asyncio
async def test_cancelled_approval_wait_denies_request_and_never_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling channel work must wake its approval worker and close state."""
    approval_manager = get_approval_manager()
    approval_manager.reset()
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

    async def _unexpected_execution(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("cancelled tool executed")

    monkeypatch.setattr(manager, "perform_memory_search", _unexpected_execution)
    session_id = "session_async_cancel"
    execution = asyncio.create_task(
        manager.execute_tool_async(
            "memory_search",
            {"query": "penguin"},
            {
                "session_id": session_id,
                "approval_policy": {
                    "wait_for_resolution": True,
                    "timeout_seconds": 10.0,
                },
            },
        )
    )

    request_id = await _wait_for_pending_approval(session_id)
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution

    resolved = approval_manager.get_request(request_id)
    assert resolved is not None
    assert resolved.status.value == "denied"
    assert approval_manager.get_pending(session_id=session_id) == []
    approval_manager.reset()


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
