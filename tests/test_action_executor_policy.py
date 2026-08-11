"""Request-scoped permission contracts for model-emitted ActionXML."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from PIL import Image

from penguin.security.action_policy import (
    DIRECT_ACTION_POLICY_KEYS,
    SAFE_ACTION_NAMES,
    TOOL_MANAGED_ACTION_NAMES,
    authorize_direct_action,
)
from penguin.security.approval import ApprovalScope, get_approval_manager
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import (
    ActionExecutor,
    ActionType,
    CodeActAction,
)

if TYPE_CHECKING:
    from pathlib import Path


async def _wait_for_pending_approval(session_id: str) -> str:
    manager = get_approval_manager()
    for _ in range(200):
        pending = manager.get_pending(session_id=session_id)
        if pending:
            return pending[0].id
        await asyncio.sleep(0.005)
    raise AssertionError("Approval request was never created")


def test_every_actionxml_action_has_an_explicit_policy_classification() -> None:
    """New ActionTypes must be consciously classified before they can ship."""
    direct = set(DIRECT_ACTION_POLICY_KEYS)
    safe = set(SAFE_ACTION_NAMES)
    tool_managed = set(TOOL_MANAGED_ACTION_NAMES)

    assert direct.isdisjoint(safe)
    assert direct.isdisjoint(tool_managed)
    assert safe.isdisjoint(tool_managed)
    assert direct | safe | tool_managed == {item.value for item in ActionType}
    assert DIRECT_ACTION_POLICY_KEYS[ActionType.PROCESS_LIST.value] == "shell"
    assert DIRECT_ACTION_POLICY_KEYS[ActionType.PROCESS_ENTER.value] == "shell"
    assert DIRECT_ACTION_POLICY_KEYS[ActionType.PROCESS_EXIT.value] == "fileWrite"
    assert DIRECT_ACTION_POLICY_KEYS[ActionType.FINISH_TASK.value] == "fileWrite"
    assert DIRECT_ACTION_POLICY_KEYS[ActionType.TASK_COMPLETED.value] == "fileWrite"
    assert DIRECT_ACTION_POLICY_KEYS[ActionType.SPAWN_SUB_AGENT.value] == "shell"
    assert DIRECT_ACTION_POLICY_KEYS[ActionType.RESUME_SUB_AGENT.value] == "shell"
    assert DIRECT_ACTION_POLICY_KEYS[ActionType.STOP_SUB_AGENT.value] == "shell"
    assert ActionType.READ_IMAGE.value in tool_managed
    assert ActionType.PUBLISH_ARTIFACT.value in tool_managed


@pytest.mark.asyncio
async def test_actionxml_publish_artifact_preserves_explicit_descriptor() -> None:
    class _ToolManager:
        def execute_tool(self, name: str, payload: dict[str, str]) -> dict[str, object]:
            assert name == "publish_artifact"
            assert payload == {"path": "reports/result.pdf"}
            return {
                "result": "Artifact ready for delivery: result.pdf",
                "artifact": {
                    "type": "file",
                    "path": "/workspace/reports/result.pdf",
                },
            }

    executor = ActionExecutor(
        tool_manager=_ToolManager(),
        task_manager=SimpleNamespace(),
    )

    result = await executor.execute_action(
        CodeActAction(
            ActionType.PUBLISH_ARTIFACT,
            '{"path":"reports/result.pdf"}',
        )
    )

    assert result["artifact"] == {
        "type": "file",
        "path": "/workspace/reports/result.pdf",
    }


@pytest.mark.asyncio
async def test_unclassified_future_action_uses_default_deny_policy() -> None:
    """A future manual ActionXML handler must fail closed until classified."""

    with execution_context_scope(
        ExecutionContext(
            session_id="telegram-future-action",
            permission_mode="workspace",
            approval_policy={"default": "deny"},
        )
    ):
        raw_result = await authorize_direct_action("future_mutation", "payload")

    result = json.loads(raw_result)
    assert result["error"] == "permission_denied"
    assert result["action"] == "future_mutation"


@pytest.mark.asyncio
async def test_read_only_actionxml_cannot_start_process() -> None:
    """Direct ActionXML mutations must honor the request permission ceiling."""

    class _ProcessManager:
        def __init__(self) -> None:
            self.start_calls = 0

        async def start_process(self, name: str, command: str) -> str:
            del name, command
            self.start_calls += 1
            return "started"

    process_manager = _ProcessManager()
    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    executor.process_manager = process_manager

    with execution_context_scope(
        ExecutionContext(
            session_id="telegram-read-only",
            permission_mode="read_only",
            approval_policy={"shell": "allow", "default": "allow"},
        )
    ):
        raw_result = await executor.execute_action(
            CodeActAction(ActionType.PROCESS_START, "server: python -m http.server")
        )

    result = json.loads(raw_result)
    assert result["error"] == "permission_denied"
    assert result["action"] == "process_start"
    assert process_manager.start_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action_type", "params"),
    [
        (ActionType.PROCESS_LIST, ""),
        (ActionType.PROCESS_ENTER, "server"),
        (ActionType.FINISH_TASK, "done"),
        (ActionType.TASK_COMPLETED, "done"),
    ],
)
async def test_read_only_blocks_sensitive_legacy_actionxml_handlers(
    action_type: ActionType,
    params: str,
) -> None:
    """Remote reads and completion transitions cannot bypass read-only mode."""

    class _ProcessManager:
        async def list_processes(self) -> dict[str, str]:
            raise AssertionError("process list must not run")

        async def enter_process(self, _name: str) -> object:
            raise AssertionError("process enter must not run")

    class _TaskTools:
        def finish_task(self, _summary: str) -> str:
            raise AssertionError("finish task must not run")

    executor = ActionExecutor(
        tool_manager=SimpleNamespace(task_tools=_TaskTools()),
        task_manager=SimpleNamespace(),
    )
    executor.process_manager = _ProcessManager()

    with execution_context_scope(
        ExecutionContext(
            session_id="telegram-read-only-sensitive-action",
            permission_mode="read_only",
        )
    ):
        raw_result = await executor.execute_action(CodeActAction(action_type, params))

    result = json.loads(raw_result)
    assert result["error"] == "permission_denied"
    assert result["action"] == action_type.value


@pytest.mark.asyncio
async def test_deny_policy_actionxml_cannot_start_process() -> None:
    """A remote deny decision must not create or start a process."""

    class _ProcessManager:
        async def start_process(self, name: str, command: str) -> str:
            raise AssertionError(f"unexpected process start: {name}={command}")

    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    executor.process_manager = _ProcessManager()

    with execution_context_scope(
        ExecutionContext(
            session_id="telegram-deny",
            permission_mode="workspace",
            approval_policy={"shell": "deny", "default": "deny"},
        )
    ):
        raw_result = await executor.execute_action(
            CodeActAction(ActionType.PROCESS_START, "server: python -m http.server")
        )

    result = json.loads(raw_result)
    assert result["error"] == "permission_denied"
    assert result["action"] == "process_start"


@pytest.mark.asyncio
async def test_secret_policy_caps_allowed_actionxml_shell() -> None:
    """Allowing shell must not implicitly allow access to environment secrets."""

    class _ProcessManager:
        async def start_process(self, name: str, command: str) -> str:
            raise AssertionError(f"unexpected process start: {name}={command}")

    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    executor.process_manager = _ProcessManager()

    with execution_context_scope(
        ExecutionContext(
            session_id="telegram-secret-deny",
            permission_mode="workspace",
            approval_policy={
                "shell": "allow",
                "secrets": "deny",
                "default": "allow",
            },
        )
    ):
        raw_result = await executor.execute_action(
            CodeActAction(ActionType.PROCESS_START, "inspect: printenv API_TOKEN")
        )

    result = json.loads(raw_result)
    assert result["error"] == "permission_denied"
    assert result["action"] == "process_start"


@pytest.mark.asyncio
async def test_granular_prompt_resumes_actionxml_process_once() -> None:
    """An explicit category ASK overrides only a DENY fallback."""
    approval_manager = get_approval_manager()
    approval_manager.reset()

    class _ProcessManager:
        def __init__(self) -> None:
            self.start_calls = 0

        async def start_process(self, name: str, command: str) -> str:
            assert name == "server"
            assert command == "python -m http.server"
            self.start_calls += 1
            return "started"

    process_manager = _ProcessManager()
    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    executor.process_manager = process_manager
    session_id = "telegram-prompt"

    with execution_context_scope(
        ExecutionContext(
            session_id=session_id,
            permission_mode="workspace",
            approval_policy={
                "shell": "ask",
                "default": "deny",
                "wait_for_resolution": True,
                "timeout_seconds": 1.0,
            },
        )
    ):
        execution = asyncio.create_task(
            executor.execute_action(
                CodeActAction(
                    ActionType.PROCESS_START,
                    "server: python -m http.server",
                )
            )
        )
        request_id = await _wait_for_pending_approval(session_id)
        assert execution.done() is False
        assert approval_manager.approve(request_id) is not None
        assert approval_manager.approve(request_id) is None
        result = await asyncio.wait_for(execution, timeout=1.0)

    assert result == "started"
    assert process_manager.start_calls == 1
    approval_manager.reset()


@pytest.mark.asyncio
async def test_non_waiting_prompt_returns_pending_without_process_start() -> None:
    """Non-channel callers keep the callback-style pending response contract."""
    approval_manager = get_approval_manager()
    approval_manager.reset()

    class _ProcessManager:
        async def start_process(self, name: str, command: str) -> str:
            raise AssertionError(f"unexpected process start: {name}={command}")

    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    executor.process_manager = _ProcessManager()
    session_id = "http-style-prompt"

    with execution_context_scope(
        ExecutionContext(
            session_id=session_id,
            permission_mode="workspace",
            approval_policy={"shell": "ask", "default": "ask"},
        )
    ):
        raw_result = await executor.execute_action(
            CodeActAction(ActionType.PROCESS_START, "server: python app.py")
        )

    result = json.loads(raw_result)
    assert result["status"] == "pending_approval"
    assert result["action"] == "process_start"
    pending = approval_manager.get_pending(session_id=session_id)
    assert [request.id for request in pending] == [result["approval_id"]]
    approval_manager.deny(result["approval_id"])
    approval_manager.reset()


@pytest.mark.asyncio
async def test_actionxml_session_approval_does_not_bypass_new_ask_category() -> None:
    """A direct-action shell grant must not silently include secret access."""
    approval_manager = get_approval_manager()
    approval_manager.reset()
    session_id = "action-category-escalation"
    context = ExecutionContext(
        session_id=session_id,
        permission_mode="workspace",
        approval_policy={
            "default": "deny",
            "shell": "ask",
            "secrets": "ask",
        },
    )

    with execution_context_scope(context):
        first_result = json.loads(
            await authorize_direct_action("process_start", "server: pwd")
        )
    first_request = approval_manager.get_request(first_result["approval_id"])
    assert first_request is not None
    assert (
        approval_manager.approve(
            first_request.id,
            scope=ApprovalScope.SESSION,
        )
        is not None
    )

    with execution_context_scope(context):
        assert await authorize_direct_action("process_start", "server: whoami") is None
        escalated_result = json.loads(
            await authorize_direct_action("process_start", "inspect: cat .env")
        )

    escalated_request = approval_manager.get_request(escalated_result["approval_id"])
    assert escalated_request is not None
    assert escalated_request.operation != first_request.operation
    approval_manager.deny(escalated_request.id)
    approval_manager.reset()


@pytest.mark.asyncio
async def test_denied_prompt_never_resumes_actionxml_process() -> None:
    """A resolved denial must terminate the suspended direct action."""
    approval_manager = get_approval_manager()
    approval_manager.reset()

    class _ProcessManager:
        async def start_process(self, name: str, command: str) -> str:
            raise AssertionError(f"unexpected process start: {name}={command}")

    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
    )
    executor.process_manager = _ProcessManager()
    session_id = "telegram-prompt-denied"

    with execution_context_scope(
        ExecutionContext(
            session_id=session_id,
            permission_mode="workspace",
            approval_policy={
                "shell": "ask",
                "default": "ask",
                "wait_for_resolution": True,
                "timeout_seconds": 1.0,
            },
        )
    ):
        execution = asyncio.create_task(
            executor.execute_action(
                CodeActAction(ActionType.PROCESS_START, "server: python app.py")
            )
        )
        request_id = await _wait_for_pending_approval(session_id)
        assert approval_manager.deny(request_id) is not None
        result = json.loads(await asyncio.wait_for(execution, timeout=1.0))

    assert result["error"] == "approval_denied"
    assert approval_manager.approve(request_id) is None
    approval_manager.reset()


@pytest.mark.asyncio
async def test_prompt_policy_resumes_tool_backed_actionxml_write_once(
    tmp_path: Path,
) -> None:
    """Synchronous ToolManager ActionXML handlers resume after approval."""
    approval_manager = get_approval_manager()
    approval_manager.reset()
    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    executor = ActionExecutor(
        tool_manager=manager,
        task_manager=SimpleNamespace(),
    )
    target = tmp_path / "approved.txt"
    session_id = "telegram-tool-backed-prompt"
    payload = json.dumps({"path": str(target), "content": "approved once"})

    with execution_context_scope(
        ExecutionContext(
            session_id=session_id,
            directory=str(tmp_path),
            permission_mode="workspace",
            approval_policy={
                "fileWrite": "ask",
                "default": "ask",
                "wait_for_resolution": True,
                "timeout_seconds": 1.0,
            },
        )
    ):
        execution = asyncio.create_task(
            executor.execute_action(CodeActAction(ActionType.WRITE_FILE, payload))
        )
        request_id = await _wait_for_pending_approval(session_id)
        assert execution.done() is False
        assert target.exists() is False
        assert approval_manager.approve(request_id) is not None
        assert approval_manager.approve(request_id) is None
        await asyncio.wait_for(execution, timeout=1.0)

    assert target.read_text(encoding="utf-8") == "approved once"
    approval_manager.reset()


@pytest.mark.asyncio
async def test_cancelled_tool_backed_actionxml_denies_late_write(
    tmp_path: Path,
) -> None:
    """Cancelling the outer action closes its worker-thread approval."""
    approval_manager = get_approval_manager()
    approval_manager.reset()
    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    executor = ActionExecutor(
        tool_manager=manager,
        task_manager=SimpleNamespace(),
    )
    target = tmp_path / "cancelled.txt"
    session_id = "telegram-tool-backed-cancel"
    request_id = "telegram-turn-cancel"
    payload = json.dumps({"path": str(target), "content": "must not exist"})

    with execution_context_scope(
        ExecutionContext(
            session_id=session_id,
            request_id=request_id,
            directory=str(tmp_path),
            permission_mode="workspace",
            approval_policy={
                "fileWrite": "ask",
                "default": "ask",
                "wait_for_resolution": True,
                "timeout_seconds": 1.0,
            },
        )
    ):
        execution = asyncio.create_task(
            executor.execute_action(CodeActAction(ActionType.WRITE_FILE, payload))
        )
        approval_id = await _wait_for_pending_approval(session_id)
        pending = approval_manager.get_request(approval_id)
        assert pending is not None
        assert pending.context["request_id"] == request_id
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution

    assert approval_manager.approve(approval_id) is None
    await asyncio.sleep(0.01)
    assert target.exists() is False
    approval_manager.reset()


@pytest.mark.asyncio
async def test_actionxml_read_image_cannot_escape_request_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote workspace mode must not expose arbitrary host image paths."""
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    outside_image = outside / "private.png"
    Image.new("RGB", (1, 1), color="red").save(outside_image)
    monkeypatch.setenv("PENGUIN_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("PENGUIN_CWD", str(tmp_path))

    class _Conversation:
        def add_message(self, **_kwargs: object) -> None:
            raise AssertionError("denied image must not enter conversation context")

    manager = ToolManager(
        {"diagnostics": {"enabled": False}},
        lambda _error, _context: None,
    )
    executor = ActionExecutor(
        tool_manager=manager,
        task_manager=SimpleNamespace(),
        conversation_system=_Conversation(),
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="telegram-read-image-escape",
            request_id="telegram-image-turn",
            directory=str(workspace),
            project_root=str(workspace),
            workspace_root=str(workspace),
            permission_mode="workspace",
            approval_policy={"default": "deny"},
        )
    ):
        raw_result = await executor.execute_action(
            CodeActAction(
                ActionType.READ_IMAGE,
                json.dumps({"path": str(outside_image)}),
            )
        )

    result = json.loads(raw_result)
    assert result["error"] == "permission_denied"
    assert result["tool"] == "read_image"
    assert "outside request workspace" in result["reason"]
