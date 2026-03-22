"""Tests for sub-agent lifecycle event emission in ActionExecutor."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.core import PenguinCore
from penguin.utils.parser import ActionExecutor, ActionType, CodeActAction, parse_action


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class _ConversationManager:
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._child = SimpleNamespace(
            session=SimpleNamespace(id=session_id, metadata={}), _modified=False
        )
        self._parent = SimpleNamespace(
            session=SimpleNamespace(
                id="session_parent", metadata={"directory": "/tmp/workspace"}
            ),
            _modified=False,
        )

    def get_agent_conversation(self, agent_id: str) -> Any:
        if agent_id == "default":
            return self._parent
        return self._child


class _Core:
    def __init__(self, session_id: str) -> None:
        self.event_bus = _EventBus()
        self.conversation_manager = _ConversationManager(session_id)
        self.created: list[dict[str, Any]] = []
        self.runtime_config = SimpleNamespace(active_root="/tmp/workspace")
        self._opencode_session_directories: dict[str, str] = {}
        self.run_agent_prompt_in_session = AsyncMock(
            return_value={"assistant_response": "done"}
        )
        helper = getattr(PenguinCore, "publish_sub_agent_session_created")
        self.publish_sub_agent_session_created = helper.__get__(self)

    def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
        self.created.append({"agent_id": agent_id, **kwargs})


class _ToolManager:
    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._result = result or {"status": "ok"}

    def execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        self.calls.append((tool_name, tool_input))
        return json.dumps(self._result)


class _WaitToolManager:
    def __init__(self) -> None:
        self.wait_calls: list[dict[str, Any]] = []
        self.execute_calls: list[tuple[str, dict[str, Any]]] = []

    async def _execute_wait_for_agents(self, tool_input: dict[str, Any]) -> str:
        self.wait_calls.append(tool_input)
        return json.dumps(
            {
                "status": "ok",
                "results": {"child-a": "done"},
            }
        )

    def execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        self.execute_calls.append((tool_name, tool_input))
        return json.dumps({"status": "fallback"})


@pytest.mark.asyncio
async def test_spawn_sub_agent_emits_session_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _Core("session_child_1")
    conversation = SimpleNamespace(core=core, current_agent_id="default")
    executor = ActionExecutor(
        tool_manager=cast(Any, SimpleNamespace()),
        task_manager=cast(Any, SimpleNamespace()),
        conversation_system=conversation,
    )

    def _fake_session_info(_core: Any, session_id: str) -> dict[str, Any]:
        return {
            "id": session_id,
            "title": "Child Session",
            "directory": "/tmp/workspace",
            "parentID": "session_parent",
            "agent_id": "child-agent",
            "parent_agent_id": "default",
            "projectID": "penguin",
            "slug": session_id,
            "version": "test",
            "time": {"created": 1, "updated": 1},
        }

    monkeypatch.setattr(
        "penguin.web.services.session_view.get_session_info",
        _fake_session_info,
    )

    payload = json.dumps(
        {
            "id": "child-agent",
            "share_session": False,
            "share_context_window": False,
        }
    )
    result = await executor._spawn_sub_agent(payload)

    assert "Spawned sub-agent 'child-agent'" in result
    assert core.created
    assert core.created[0]["agent_id"] == "child-agent"

    assert core.event_bus.events
    event_type, payload = core.event_bus.events[-1]
    assert event_type == "opencode_event"
    assert payload["type"] == "session.created"
    assert payload["properties"]["sessionID"] == "session_child_1"
    assert payload["properties"]["info"]["id"] == "session_child_1"
    assert payload["properties"]["info"]["parentID"] == "session_parent"
    assert payload["properties"]["info"]["agent_id"] == "child-agent"
    assert payload["properties"]["info"]["parent_agent_id"] == "default"
    assert core._opencode_session_directories["session_child_1"] == "/tmp/workspace"


@pytest.mark.asyncio
async def test_spawn_sub_agent_action_result_emits_task_card_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _Core("session_child_1")
    conversation = SimpleNamespace(core=core, current_agent_id="default")
    events: list[tuple[str, dict[str, Any]]] = []

    async def _ui_event(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    executor = ActionExecutor(
        tool_manager=cast(Any, SimpleNamespace()),
        task_manager=cast(Any, SimpleNamespace()),
        conversation_system=conversation,
        ui_event_callback=_ui_event,
    )

    def _fake_session_info(_core: Any, session_id: str) -> dict[str, Any]:
        return {
            "id": session_id,
            "title": "Child Session",
            "directory": "/tmp/workspace",
            "parentID": "session_parent",
            "agent_id": "child-agent",
            "parent_agent_id": "default",
            "projectID": "penguin",
            "slug": session_id,
            "version": "test",
            "time": {"created": 1, "updated": 1},
        }

    monkeypatch.setattr(
        "penguin.web.services.session_view.get_session_info",
        _fake_session_info,
    )

    action = CodeActAction(
        ActionType.SPAWN_SUB_AGENT,
        json.dumps(
            {
                "id": "child-agent",
                "share_session": False,
                "share_context_window": False,
                "background": True,
                "initial_prompt": "Smoke test only.",
            }
        ),
    )

    result = await executor.execute_action(action)

    assert "Spawned sub-agent 'child-agent'" in result
    action_result = [
        payload for event_type, payload in events if event_type == "action_result"
    ]
    assert action_result
    metadata = action_result[-1]["metadata"]
    assert metadata["sessionId"] == "session_child_1"
    assert metadata["title"] == "Child Session"
    assert metadata["summary"][0]["tool"] == "subagent"
    assert metadata["summary"][0]["state"]["status"] == "completed"


@pytest.mark.asyncio
async def test_spawn_sub_agent_runs_foreground_prompt_in_child_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _Core("session_child_1")
    conversation = SimpleNamespace(core=core, current_agent_id="default")
    executor = ActionExecutor(
        tool_manager=cast(Any, SimpleNamespace()),
        task_manager=cast(Any, SimpleNamespace()),
        conversation_system=conversation,
    )

    def _fake_session_info(_core: Any, session_id: str) -> dict[str, Any]:
        return {
            "id": session_id,
            "title": "Child Session",
            "directory": "/tmp/workspace",
            "parentID": "session_parent",
            "agent_id": "child-agent",
            "parent_agent_id": "default",
            "projectID": "penguin",
            "slug": session_id,
            "version": "test",
            "time": {"created": 1, "updated": 1},
        }

    monkeypatch.setattr(
        "penguin.web.services.session_view.get_session_info",
        _fake_session_info,
    )

    payload = json.dumps(
        {
            "id": "child-agent",
            "share_session": False,
            "share_context_window": False,
            "background": False,
            "initial_prompt": "Run in the child session.",
        }
    )
    result = await executor._spawn_sub_agent(payload)

    assert "Spawned sub-agent 'child-agent'" in result
    core.run_agent_prompt_in_session.assert_awaited_once_with(
        "child-agent",
        "Run in the child session.",
        session_id="session_child_1",
        directory="/tmp/workspace",
        agent_mode=None,
    )


def test_parse_action_detects_subagent_status_tags() -> None:
    content = """
    <get_agent_status>{"agent_id":"child-a"}</get_agent_status>
    <wait_for_agents>{"agent_ids":["child-a","child-b"],"timeout":20}</wait_for_agents>
    <get_context_info>{"agent_id":"child-a","include_stats":true}</get_context_info>
    <sync_context>{"parent_agent_id":"default","child_agent_id":"child-a"}</sync_context>
    """.strip()

    actions = parse_action(content)
    assert [action.action_type.value for action in actions] == [
        "get_agent_status",
        "wait_for_agents",
        "get_context_info",
        "sync_context",
    ]


@pytest.mark.asyncio
async def test_get_agent_status_accepts_agent_id_alias() -> None:
    tool_manager = _ToolManager()
    executor = ActionExecutor(
        tool_manager=tool_manager,  # type: ignore[arg-type]
        task_manager=cast(Any, SimpleNamespace()),
    )
    executor_any: Any = executor

    result = await executor_any._get_agent_status(
        json.dumps({"agent_id": "child-a", "include_result": True})
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls
    tool_name, tool_input = tool_manager.calls[-1]
    assert tool_name == "get_agent_status"
    assert tool_input["id"] == "child-a"
    assert tool_input["include_result"] is True


@pytest.mark.asyncio
async def test_wait_for_agents_accepts_agent_ids_alias() -> None:
    tool_manager = _ToolManager()
    executor = ActionExecutor(
        tool_manager=tool_manager,  # type: ignore[arg-type]
        task_manager=cast(Any, SimpleNamespace()),
    )
    executor_any: Any = executor

    result = await executor_any._wait_for_agents(
        json.dumps({"agent_ids": ["child-a", "child-b"], "timeout": 15})
    )

    assert json.loads(result)["status"] == "ok"
    assert tool_manager.calls
    tool_name, tool_input = tool_manager.calls[-1]
    assert tool_name == "wait_for_agents"
    assert tool_input["ids"] == ["child-a", "child-b"]
    assert tool_input["timeout"] == 15.0


@pytest.mark.asyncio
async def test_context_info_and_sync_context_aliases() -> None:
    tool_manager = _ToolManager()
    executor = ActionExecutor(
        tool_manager=tool_manager,  # type: ignore[arg-type]
        task_manager=cast(Any, SimpleNamespace()),
    )
    executor_any: Any = executor

    context_result = await executor_any._get_context_info(
        json.dumps({"agent_id": "child-a", "include_stats": True})
    )
    sync_result = await executor_any._sync_context(
        json.dumps(
            {
                "parent_agent_id": "default",
                "child_agent_id": "child-a",
                "replace": True,
            }
        )
    )

    assert json.loads(context_result)["status"] == "ok"
    assert json.loads(sync_result)["status"] == "ok"
    assert len(tool_manager.calls) == 2

    context_name, context_input = tool_manager.calls[0]
    sync_name, sync_input = tool_manager.calls[1]
    assert context_name == "get_context_info"
    assert context_input == {"id": "child-a", "include_stats": True}
    assert sync_name == "sync_context"
    assert sync_input == {"parent": "default", "child": "child-a", "replace": True}


@pytest.mark.asyncio
async def test_wait_for_agents_uses_async_tool_handler() -> None:
    tool_manager = _WaitToolManager()
    executor = ActionExecutor(
        tool_manager=tool_manager,  # type: ignore[arg-type]
        task_manager=cast(Any, SimpleNamespace()),
    )
    executor_any: Any = executor

    result = await executor_any._wait_for_agents(
        json.dumps({"agent_ids": ["child-a"], "timeout": 5})
    )

    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert tool_manager.wait_calls
    assert tool_manager.wait_calls[-1]["ids"] == ["child-a"]
    assert tool_manager.wait_calls[-1]["timeout"] == 5.0
    assert not tool_manager.execute_calls


@pytest.mark.asyncio
async def test_wait_for_agents_action_path_completes_background_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from penguin.multi.executor import AgentExecutor
    from penguin.tools.tool_manager import ToolManager

    core = MagicMock()

    async def _mock_process(
        input_data: dict[str, Any], agent_id: str = ""
    ) -> dict[str, Any]:
        await __import__("asyncio").sleep(0.02)
        return {"assistant_response": f"done {agent_id}", "agent_id": agent_id}

    core.process = AsyncMock(side_effect=_mock_process)
    executor_runner = AgentExecutor(core, max_concurrent=1)
    monkeypatch.setattr(
        "penguin.multi.executor.get_executor",
        lambda _core=None: executor_runner,
    )

    tool_manager = ToolManager(
        config={"diagnostics": {"enabled": False}},
        log_error_func=lambda *_args, **_kwargs: None,
    )
    action_executor = ActionExecutor(
        tool_manager=tool_manager,
        task_manager=cast(Any, SimpleNamespace()),
    )

    await executor_runner.spawn_agent("wait-action-agent", "quick")
    result = await action_executor._wait_for_agents(
        json.dumps({"ids": ["wait-action-agent"], "timeout": 1.0})
    )

    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert payload["results"]["wait-action-agent"] is not None


def test_build_lsp_diagnostics_extracts_line_and_source() -> None:
    tool_manager = _ToolManager()
    executor = ActionExecutor(
        tool_manager=tool_manager,  # type: ignore[arg-type]
        task_manager=cast(Any, SimpleNamespace()),
    )

    payload = {
        "error": "SyntaxError: invalid syntax at line 7, column 3",
        "returncode": 1,
    }
    diagnostics = executor._build_lsp_diagnostics(["src/example.py"], payload)

    assert "src/example.py" in diagnostics
    entries = diagnostics["src/example.py"]
    assert entries
    assert entries[0]["source"] == "penguin"
    assert entries[0]["range"]["start"]["line"] == 6
    assert entries[0]["range"]["start"]["character"] == 2


@pytest.mark.asyncio
async def test_execute_action_emits_enriched_lsp_diagnostics_payload() -> None:
    tool_manager = _ToolManager(
        result={
            "error": "TypeError at line 4, column 9",
            "returncode": 1,
        }
    )
    emitted: list[tuple[str, dict[str, Any]]] = []

    async def _capture(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    executor = ActionExecutor(
        tool_manager=tool_manager,  # type: ignore[arg-type]
        task_manager=cast(Any, SimpleNamespace()),
        ui_event_callback=_capture,
    )

    result = await executor.execute_action(
        CodeActAction(ActionType.ENHANCED_WRITE, "src/example.py:print('x')")
    )
    assert json.loads(result)["returncode"] == 1

    diagnostics_events = [
        item for item in emitted if item[0] == "lsp.client.diagnostics"
    ]
    assert diagnostics_events
    payload = diagnostics_events[-1][1]
    assert payload["serverID"] == "penguin"
    assert payload["path"] == "src/example.py"
    assert payload["count"] == 1
    assert "src/example.py" in payload["diagnostics"]
