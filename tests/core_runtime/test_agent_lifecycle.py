"""Tests for agent lifecycle runtime helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime.agent_lifecycle import (
    publish_sub_agent_session_created,
    resolve_agent_execution_scope,
    run_agent_prompt_in_session,
)
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    get_current_execution_context,
)


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class _Conversation:
    def __init__(self, session: SimpleNamespace) -> None:
        self.session = session
        self._modified = False
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


def test_resolve_agent_execution_scope_uses_session_metadata_and_inherited_roots(
    tmp_path,
) -> None:
    parent_dir = tmp_path / "parent"
    child_dir = tmp_path / "child"
    parent_dir.mkdir()
    child_dir.mkdir()
    session = SimpleNamespace(
        id="session_child",
        metadata={"directory": str(child_dir), "_opencode_agent_mode_v1": "PLAN"},
    )
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            get_agent_conversation=lambda _agent_id: SimpleNamespace(session=session)
        ),
        _opencode_session_directories={},
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="session_parent",
            conversation_id="session_parent",
            agent_id="default",
            directory=str(parent_dir),
            project_root=str(parent_dir),
            workspace_root=str(parent_dir),
        )
    ):
        scope = resolve_agent_execution_scope(core, "child-agent")

    assert scope == {
        "session_id": "session_child",
        "conversation_id": "session_child",
        "directory": str(child_dir),
        "project_root": str(parent_dir),
        "workspace_root": str(parent_dir),
        "agent_mode": "plan",
    }


def test_resolve_agent_execution_scope_uses_session_directory_map(tmp_path) -> None:
    child_dir = tmp_path / "child"
    child_dir.mkdir()
    session = SimpleNamespace(id="session_child", metadata={})
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            get_agent_conversation=lambda _agent_id: SimpleNamespace(session=session)
        ),
        _opencode_session_directories={"session_child": str(child_dir)},
    )

    scope = resolve_agent_execution_scope(core, "child-agent")

    assert scope["session_id"] == "session_child"
    assert scope["directory"] == str(child_dir)
    assert scope["project_root"] == str(child_dir)
    assert scope["workspace_root"] == str(child_dir)


def test_resolve_agent_execution_scope_tolerates_conversation_lookup_failure(
    tmp_path,
) -> None:
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()

    class _BrokenConversationManager:
        def get_agent_conversation(self, _agent_id: str) -> Any:
            raise RuntimeError("conversation store unavailable")

    core = SimpleNamespace(
        conversation_manager=_BrokenConversationManager(),
        _opencode_session_directories={},
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="session_parent",
            conversation_id="session_parent",
            agent_id="default",
            agent_mode="build",
            directory=str(parent_dir),
            project_root=str(parent_dir),
            workspace_root=str(parent_dir),
        )
    ):
        scope = resolve_agent_execution_scope(core, "child-agent")

    assert scope == {
        "session_id": None,
        "conversation_id": None,
        "directory": str(parent_dir),
        "project_root": str(parent_dir),
        "workspace_root": str(parent_dir),
        "agent_mode": "build",
    }


@pytest.mark.asyncio
async def test_run_agent_prompt_in_session_sets_execution_context(tmp_path) -> None:
    child_dir = tmp_path / "child"
    child_dir.mkdir()
    session = SimpleNamespace(
        id="session_child",
        metadata={"directory": str(child_dir), "agent_mode": "build"},
    )
    conversation_manager = SimpleNamespace(
        get_agent_conversation=lambda _agent_id: SimpleNamespace(session=session)
    )
    captured: dict[str, Any] = {}

    async def _process(**kwargs: Any) -> dict[str, str]:
        captured["kwargs"] = kwargs
        captured["context"] = get_current_execution_context()
        return {"assistant_response": "done"}

    core = SimpleNamespace(
        conversation_manager=conversation_manager,
        _opencode_session_directories={},
        process=AsyncMock(side_effect=_process),
    )

    result = await run_agent_prompt_in_session(
        core,
        "child-agent",
        "Child prompt",
        streaming=False,
    )

    assert result == {"assistant_response": "done"}
    assert captured["kwargs"] == {
        "input_data": {"text": "Child prompt"},
        "conversation_id": "session_child",
        "agent_id": "child-agent",
        "streaming": False,
    }
    context = captured["context"]
    assert context is not None
    assert context.session_id == "session_child"
    assert context.conversation_id == "session_child"
    assert context.agent_id == "child-agent"
    assert context.directory == str(child_dir)
    assert context.request_id == "subagent:child-agent:session_child"


@pytest.mark.asyncio
async def test_publish_sub_agent_session_created_inherits_parent_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()
    parent = _Conversation(
        SimpleNamespace(id="session_parent", metadata={"directory": str(parent_dir)})
    )
    child = _Conversation(SimpleNamespace(id="session_child", metadata={}))

    def _get_agent_conversation(agent_id: str) -> _Conversation:
        return parent if agent_id == "default" else child

    event_bus = _EventBus()
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            get_agent_conversation=_get_agent_conversation
        ),
        runtime_config=SimpleNamespace(active_root=str(tmp_path)),
        _opencode_session_directories={},
        event_bus=event_bus,
    )
    info = {
        "id": "session_child",
        "directory": str(parent_dir),
        "parentID": "session_parent",
        "agent_id": "child-agent",
        "parent_agent_id": "default",
    }
    monkeypatch.setattr(
        "penguin.web.services.session_view.get_session_info",
        lambda _core, session_id: info if session_id == "session_child" else None,
    )

    result = await publish_sub_agent_session_created(
        core,
        "child-agent",
        parent_agent_id="default",
    )

    assert result == info
    assert child.session.metadata["directory"] == str(parent_dir)
    assert child._modified is True
    assert child.save_calls == 1
    assert core._opencode_session_directories["session_child"] == str(parent_dir)
    assert event_bus.events == [
        (
            "opencode_event",
            {
                "type": "session.created",
                "properties": {
                    "sessionID": "session_child",
                    "info": info,
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_publish_sub_agent_session_created_uses_parent_directory_map(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    parent_dir = tmp_path / "mapped-parent"
    parent_dir.mkdir()
    parent = _Conversation(SimpleNamespace(id="session_parent", metadata={}))
    child = _Conversation(SimpleNamespace(id="session_child", metadata={}))

    def _get_agent_conversation(agent_id: str) -> _Conversation:
        return parent if agent_id == "default" else child

    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            get_agent_conversation=_get_agent_conversation
        ),
        runtime_config=SimpleNamespace(active_root=str(tmp_path)),
        _opencode_session_directories={"session_parent": str(parent_dir)},
        event_bus=_EventBus(),
    )
    monkeypatch.setattr(
        "penguin.web.services.session_view.get_session_info",
        lambda _core, session_id: {"id": session_id},
    )

    await publish_sub_agent_session_created(
        core,
        "child-agent",
        parent_agent_id="default",
    )

    assert child.session.metadata["directory"] == str(parent_dir)
    assert core._opencode_session_directories["session_parent"] == str(parent_dir)
    assert core._opencode_session_directories["session_child"] == str(parent_dir)


@pytest.mark.asyncio
async def test_publish_sub_agent_session_created_skips_shared_session() -> None:
    class _ConversationManager:
        def get_agent_conversation(self, _agent_id: str) -> Any:
            raise AssertionError("shared sessions should not resolve conversations")

    core = SimpleNamespace(
        conversation_manager=_ConversationManager(),
        event_bus=_EventBus(),
    )

    result = await publish_sub_agent_session_created(
        core,
        "child-agent",
        share_session=True,
    )

    assert result is None
    assert core.event_bus.events == []
