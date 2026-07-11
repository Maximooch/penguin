"""Tests for OpenCode-compatible session parity routes."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from penguin.system.execution_context import get_current_execution_context
from penguin.system.state import Message, MessageCategory, Session
from penguin.web.routes import (
    api_session_abort,
    api_session_create,
    api_session_delete,
    api_session_diff,
    api_session_goal,
    api_session_goal_clear,
    api_session_goal_run,
    api_session_list,
    api_session_status,
    api_session_summarize,
    api_session_todo,
    api_session_update,
    session_abort,
    session_create,
    session_delete,
    session_diff,
    session_get,
    session_goal,
    session_goal_clear,
    session_goal_run,
    session_goal_update,
    session_list,
    session_messages,
    session_status,
    session_summarize,
    session_todo,
    session_update,
)
from penguin.web.services.session_view import (
    TODO_KEY,
    TRANSCRIPT_KEY,
    get_session_title_source,
)


class _Manager:
    def __init__(self) -> None:
        self.sessions: dict[str, tuple[Session, bool]] = {}
        self.session_index: dict[str, dict[str, Any]] = {}
        self.current_session: Session | None = None

    def create_session(self) -> Session:
        session = Session()
        session.metadata["message_count"] = 0
        self.sessions[session.id] = (session, True)
        self.session_index[session.id] = {
            "created_at": session.created_at,
            "last_active": session.last_active,
            "message_count": 0,
            "title": f"Session {session.id[-8:]}",
        }
        self.current_session = session
        return session

    def load_session(self, session_id: str) -> Session | None:
        item = self.sessions.get(session_id)
        if item is None:
            return None
        return item[0]

    def mark_session_modified(self, session_id: str) -> None:
        item = self.sessions.get(session_id)
        if item is not None:
            self.sessions[session_id] = (item[0], True)

    def save_session(self, session: Session) -> bool:
        self.sessions[session.id] = (session, False)
        self.session_index[session.id] = {
            "created_at": session.created_at,
            "last_active": session.last_active,
            "message_count": len(session.messages),
            "title": session.metadata.get("title", f"Session {session.id[-8:]}"),
        }
        return True

    def delete_session(self, session_id: str) -> bool:
        self.sessions.pop(session_id, None)
        self.session_index.pop(session_id, None)
        if self.current_session and self.current_session.id == session_id:
            self.current_session = None
        return True


class _Core:
    def __init__(self, workspace: Path) -> None:
        manager = _Manager()

        class _EventBus:
            def __init__(self) -> None:
                self.events: list[tuple[str, dict[str, Any]]] = []

            async def emit(self, event_type: str, data: dict[str, Any]) -> None:
                self.events.append((event_type, data))

        self.runtime_config = SimpleNamespace(
            workspace_root=str(workspace),
            project_root=str(workspace),
            active_root=str(workspace),
        )
        self.event_bus = _EventBus()
        self._opencode_session_directories: dict[str, str] = {}
        self._opencode_stream_states: dict[str, dict[str, Any]] = {}
        self.conversation_manager = SimpleNamespace(
            session_manager=manager,
            current_agent_id="default",
            agent_session_managers={"default": manager},
        )
        self.model_config = SimpleNamespace(model="openai/gpt-5", provider="openai")
        self.abort_calls: list[str] = []
        self.goal_user_messages: list[dict[str, Any]] = []

    async def abort_session(self, session_id: str) -> bool:
        self.abort_calls.append(session_id)
        return True

    async def _emit_opencode_user_message_with_metadata(
        self,
        content: str,
        *,
        message_id: str | None = None,
        part_id: str | None = None,
        agent_id: str | None = None,
        persist: bool = True,
    ) -> str:
        context = get_current_execution_context()
        event = {
            "content": content,
            "message_id": message_id,
            "agent_id": agent_id,
            "persist": persist,
            "session_id": context.session_id if context else None,
        }
        if part_id is not None:
            event["part_id"] = part_id
        self.goal_user_messages.append(event)
        return message_id or "generated"


@pytest.mark.asyncio
async def test_session_create_update_status_diff_delete_roundtrip(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    created = await session_create(
        payload={"title": "Alpha Session"},
        core=typed_core,
        directory=str(tmp_path),
    )
    session_id = created["id"]
    assert created["title"] == "Alpha Session"
    assert created["directory"] == str(tmp_path.resolve())
    created_event_type, created_event_payload = core.event_bus.events[-1]
    assert created_event_type == "opencode_event"
    assert created_event_payload["type"] == "session.created"
    assert created_event_payload["properties"]["sessionID"] == session_id
    assert created_event_payload["properties"]["info"]["id"] == session_id

    updated = await session_update(
        session_id,
        payload={"title": "Alpha Renamed", "time": {"archived": 12345}},
        core=typed_core,
    )
    assert updated["title"] == "Alpha Renamed"
    assert updated["time"]["archived"] == 12345
    event_type, event_payload = core.event_bus.events[-1]
    assert event_type == "opencode_event"
    assert event_payload["type"] == "session.updated"
    assert event_payload["properties"]["info"]["id"] == session_id

    status_map = await session_status(core=typed_core)
    assert status_map[session_id]["type"] == "idle"

    aborted = await session_abort(session_id, core=typed_core)
    assert aborted is True
    assert core.abort_calls == [session_id]

    todos = await session_todo(session_id, core=typed_core)
    assert todos == []

    session_obj = core.conversation_manager.session_manager.load_session(session_id)
    assert session_obj is not None
    session_obj.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_1"],
        "messages": {
            "msg_1": {
                "info": {
                    "id": "msg_1",
                    "sessionID": session_id,
                    "role": "assistant",
                    "time": {"created": 1, "completed": 2},
                },
                "part_order": ["part_1"],
                "parts": {
                    "part_1": {
                        "id": "part_1",
                        "sessionID": session_id,
                        "messageID": "msg_1",
                        "type": "tool",
                        "tool": "edit",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "src/app.py"},
                            "metadata": {
                                "diff": "--- a/src/app.py\n+++ b/src/app.py\n@@\n-old\n+new\n"
                            },
                        },
                    }
                },
            }
        },
    }

    diffs = await session_diff(session_id, core=typed_core, messageID=None)
    assert len(diffs) == 1
    assert diffs[0]["file"] == "src/app.py"
    assert diffs[0]["additions"] == 1
    assert diffs[0]["deletions"] == 1

    assert await session_delete(session_id, core=typed_core) is True
    deleted_event_type, deleted_event_payload = core.event_bus.events[-1]
    assert deleted_event_type == "opencode_event"
    assert deleted_event_payload["type"] == "session.deleted"
    assert deleted_event_payload["properties"]["sessionID"] == session_id
    assert deleted_event_payload["properties"]["info"]["id"] == session_id

    with pytest.raises(HTTPException) as exc:
        await session_get(session_id, core=typed_core)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_session_alias_endpoints_work(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    created = await api_session_create(payload={"title": "Alias"}, core=typed_core)
    session_id = created["id"]

    statuses = await api_session_status(core=typed_core)
    assert session_id in statuses

    updated = await api_session_update(
        session_id,
        payload={"title": "Alias 2"},
        core=typed_core,
    )
    assert updated["title"] == "Alias 2"
    event_type, event_payload = core.event_bus.events[-1]
    assert event_type == "opencode_event"
    assert event_payload["type"] == "session.updated"
    assert event_payload["properties"]["info"]["id"] == session_id

    manager = core.conversation_manager.session_manager
    session_obj = manager.load_session(session_id)
    assert session_obj is not None
    session_obj.metadata[TODO_KEY] = [
        {
            "id": "todo_1",
            "content": "Verify alias todo endpoint",
            "status": "pending",
            "priority": "medium",
        }
    ]

    todos = await api_session_todo(session_id, core=typed_core)
    assert len(todos) == 1
    assert todos[0]["content"] == "Verify alias todo endpoint"
    diffs = await api_session_diff(session_id, core=typed_core, messageID=None)
    assert isinstance(diffs, list)

    deleted = await api_session_delete(session_id, core=typed_core)
    assert deleted is True


@pytest.mark.asyncio
async def test_session_goal_crud_and_aliases(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created_session = await session_create(payload={"title": "Goal"}, core=typed_core)
    session_id = created_session["id"]

    empty = await session_goal(session_id, core=typed_core)
    assert empty == {"goal": None, "status": "ok"}

    created = await session_goal_update(
        session_id,
        payload={"objective": "Ship /goal"},
        core=typed_core,
    )
    assert created["goal"]["objective"] == "Ship /goal"
    assert created["goal"]["status"] == "active"

    with pytest.raises(HTTPException) as conflict:
        await session_goal_update(
            session_id,
            payload={"objective": "Replace"},
            core=typed_core,
        )
    assert conflict.value.status_code == 409

    paused = await session_goal_update(
        session_id,
        payload={"status": "paused"},
        core=typed_core,
    )
    assert paused["goal"]["status"] == "paused"

    alias = await api_session_goal(session_id, core=typed_core)
    assert alias["goal"]["status"] == "paused"

    stored = core.conversation_manager.session_manager.current_session.metadata[
        "_penguin_goal_v1"
    ]
    stored["active_run_id"] = "goalrun_1"
    with pytest.raises(HTTPException) as running_conflict:
        await session_goal_clear(session_id, core=typed_core)
    assert running_conflict.value.status_code == 409
    stored["active_run_id"] = None

    assert await api_session_goal_clear(session_id, core=typed_core) == {
        "goal": None,
        "status": "ok",
    }

    event_types = [payload["type"] for _, payload in core.event_bus.events]
    assert "session.goal.updated" in event_types
    assert "session.updated" in event_types
    goal_refreshes = [
        payload["properties"]["info"]
        for _, payload in core.event_bus.events
        if payload["type"] == "session.updated"
        and isinstance(payload.get("properties", {}).get("info"), dict)
        and payload["properties"]["info"].get("goal")
    ]
    assert goal_refreshes[-1]["goal"]["status"] == "paused"


@pytest.mark.asyncio
async def test_session_goal_pause_fences_run_without_aborting_session(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created_session = await session_create(payload={"title": "Goal"}, core=typed_core)
    session_id = created_session["id"]
    await session_goal_update(
        session_id,
        payload={"objective": "Pause safely"},
        core=typed_core,
    )
    stored = core.conversation_manager.session_manager.current_session.metadata[
        "_penguin_goal_v1"
    ]
    stored["active_run_id"] = "goalrun_1"

    paused = await session_goal_update(
        session_id,
        payload={"status": "paused"},
        core=typed_core,
    )

    assert paused["goal"]["status"] == "paused"
    assert paused["goal"]["active_run_id"] == "goalrun_1"
    assert core.abort_calls == []


@pytest.mark.asyncio
async def test_session_goal_run_route_and_alias(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created_session = await session_create(payload={"title": "Goal"}, core=typed_core)
    session_id = created_session["id"]
    core.run_session_goal = AsyncMock(
        return_value={"status": "complete", "goal": {"status": "complete"}}
    )

    result = await session_goal_run(
        session_id,
        payload={"max_iterations": 3, "directory": str(tmp_path)},
        core=typed_core,
    )
    assert result["status"] == "complete"
    core.run_session_goal.assert_awaited_once_with(
        session_id,
        max_iterations=3,
        timeout_seconds=None,
        directory=str(tmp_path),
    )

    core.run_session_goal.reset_mock()
    await api_session_goal_run(session_id, payload=None, core=typed_core)
    core.run_session_goal.assert_awaited_once_with(
        session_id,
        max_iterations=None,
        timeout_seconds=None,
        directory=None,
    )


@pytest.mark.asyncio
async def test_session_goal_run_accepts_user_configured_limits_without_local_maximum(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created_session = await session_create(payload={"title": "Goal"}, core=typed_core)
    session_id = created_session["id"]
    core.run_session_goal = AsyncMock(
        return_value={"status": "complete", "goal": {"status": "complete"}}
    )

    await session_goal_run(
        session_id,
        payload={"max_iterations": 1_000_000, "timeout_seconds": 604_800},
        core=typed_core,
    )

    core.run_session_goal.assert_awaited_once_with(
        session_id,
        max_iterations=1_000_000,
        timeout_seconds=604_800,
        directory=None,
    )


@pytest.mark.asyncio
async def test_session_goal_routes_enforce_strict_contracts(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(payload={"title": "Strict Goal"}, core=typed_core)
    session_id = created["id"]

    for payload in (
        {"max_iterations": True},
        {"directory": 123},
        {"unknown": "field"},
    ):
        with pytest.raises(HTTPException) as invalid:
            await session_goal_run(session_id, payload=payload, core=typed_core)
        assert invalid.value.status_code == 422

    with pytest.raises(HTTPException) as missing_pause:
        await session_goal_update(
            session_id,
            payload={"status": "paused"},
            core=typed_core,
        )
    assert missing_pause.value.status_code == 404

    with pytest.raises(HTTPException) as missing_clear:
        await session_goal_clear(session_id, core=typed_core)
    assert missing_clear.value.status_code == 404

    with pytest.raises(HTTPException) as invalid_status:
        await session_goal_update(
            session_id,
            payload={"objective": "Ship it", "status": "complete"},
            core=typed_core,
        )
    assert invalid_status.value.status_code == 422

    for payload in (
        {"objective": 123},
        {"objective": "Ship it", "display_command": 123},
        {
            "objective": "Ship it",
            "display_command": "/goal Ship it",
            "client_message_id": 123,
        },
        {
            "objective": "Ship it",
            "metadata": {"invalid": float("nan")},
            "display_command": "/goal Ship it",
            "client_message_id": "msg_invalid_metadata",
        },
    ):
        with pytest.raises(HTTPException) as invalid_create:
            await session_goal_update(session_id, payload=payload, core=typed_core)
        assert invalid_create.value.status_code == 422


@pytest.mark.asyncio
async def test_session_goal_clear_recovers_corrupt_persisted_state(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(payload={}, core=typed_core)
    session = core.conversation_manager.session_manager.load_session(created["id"])
    assert session is not None
    session.metadata["_penguin_goal_v1"] = {
        "id": "corrupt",
        "status": "not-a-status",
    }

    result = await session_goal_clear(created["id"], core=typed_core)

    assert result == {"goal": None, "status": "ok"}
    assert "_penguin_goal_v1" not in session.metadata


@pytest.mark.asyncio
async def test_session_goal_clear_commits_goal_and_private_state_once(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(payload={}, core=typed_core)
    session_id = created["id"]
    await session_goal_update(
        session_id,
        payload={
            "objective": "Clear atomically",
            "display_command": "/goal Clear atomically",
            "client_message_id": "msg_clear_atomic",
        },
        core=typed_core,
    )
    manager = core.conversation_manager.session_manager
    original_save = manager.save_session
    saves = 0

    def _count_save(session: Session) -> bool:
        nonlocal saves
        saves += 1
        return original_save(session)

    manager.save_session = _count_save

    await session_goal_clear(session_id, core=typed_core)

    session = manager.load_session(session_id)
    assert session is not None
    assert saves == 1
    assert "_penguin_goal_v1" not in session.metadata
    assert "_penguin_goal_create_request_v1" not in session.metadata


@pytest.mark.asyncio
async def test_session_goal_clear_failure_restores_owned_state(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(payload={}, core=typed_core)
    session_id = created["id"]
    created_goal = await session_goal_update(
        session_id,
        payload={
            "objective": "Keep on failure",
            "display_command": "/goal Keep on failure",
            "client_message_id": "msg_clear_failure",
        },
        core=typed_core,
    )
    manager = core.conversation_manager.session_manager
    original_save = manager.save_session
    saves = 0

    def _fail_first_save(session: Session) -> bool:
        nonlocal saves
        saves += 1
        if saves == 1:
            return False
        return original_save(session)

    manager.save_session = _fail_first_save

    with pytest.raises(HTTPException) as failure:
        await session_goal_clear(session_id, core=typed_core)

    assert failure.value.status_code == 500
    session = manager.load_session(session_id)
    assert session is not None
    assert saves == 2
    assert session.metadata["_penguin_goal_v1"] == created_goal["goal"]
    assert session.metadata["_penguin_goal_create_request_v1"]["goal_id"] == (
        created_goal["goal"]["id"]
    )


@pytest.mark.asyncio
async def test_goal_create_persists_correlated_display_command(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(
        payload={"title": "Visible Goal"},
        core=typed_core,
        directory=str(tmp_path),
    )
    session_id = created["id"]

    await session_goal_update(
        session_id,
        payload={
            "objective": "Ship the robust path",
            "display_command": "/goal Ship the robust path",
            "client_message_id": "msg_goal_command",
            "client_part_id": "part_goal_command",
        },
        core=typed_core,
    )

    assert core.goal_user_messages == [
        {
            "content": "/goal Ship the robust path",
            "message_id": "msg_goal_command",
            "part_id": "part_goal_command",
            "agent_id": "default",
            "persist": False,
            "session_id": session_id,
        }
    ]


@pytest.mark.asyncio
async def test_goal_create_does_not_fail_after_event_broadcast_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(payload={}, core=typed_core)
    event_emitter = AsyncMock(side_effect=RuntimeError("event sink failed"))
    monkeypatch.setattr(
        "penguin.web.services.session_goal.emit_session_goal_updated_events",
        event_emitter,
    )

    result = await session_goal_update(
        created["id"],
        payload={"objective": "Commit despite event failure"},
        core=typed_core,
    )

    assert result["goal"]["objective"] == "Commit despite event failure"
    assert (await session_goal(created["id"], core=typed_core))["goal"] == result[
        "goal"
    ]


@pytest.mark.asyncio
async def test_goal_create_reports_correlated_transcript_save_failure(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(
        payload={"title": "Visible Goal"},
        core=typed_core,
        directory=str(tmp_path),
    )
    session_id = created["id"]
    manager = core.conversation_manager.session_manager
    original_save = manager.save_session
    save_calls = 0

    def _fail_checked_transcript_save(session: Session) -> bool:
        nonlocal save_calls
        save_calls += 1
        if save_calls == 1:
            return False
        return original_save(session)

    manager.save_session = _fail_checked_transcript_save

    with pytest.raises(HTTPException) as failure:
        await session_goal_update(
            session_id,
            payload={
                "objective": "Ship the robust path",
                "display_command": "/goal Ship the robust path",
                "client_message_id": "msg_goal_command",
            },
            core=typed_core,
        )

    assert failure.value.status_code == 500
    assert core.goal_user_messages == []
    assert (await session_goal(session_id, core=typed_core))["goal"] is None
    session = manager.load_session(session_id)
    assert session is not None
    transcript = session.metadata.get("_opencode_transcript_v1")
    assert not isinstance(transcript, dict) or "msg_goal_command" not in transcript.get(
        "messages", {}
    )


@pytest.mark.asyncio
async def test_goal_create_commits_complete_transcript_once_before_broadcast(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(
        payload={"title": "Atomic Goal"},
        core=typed_core,
        directory=str(tmp_path),
    )
    session_id = created["id"]
    manager = core.conversation_manager.session_manager
    original_save = manager.save_session
    committed_metadata: list[dict[str, Any]] = []

    def _capture_save(session: Session) -> bool:
        committed_metadata.append(deepcopy(session.metadata))
        return original_save(session)

    async def _assert_committed_before_broadcast(
        *_args: Any,
        **kwargs: Any,
    ) -> str:
        assert kwargs["persist"] is False
        assert len(committed_metadata) == 1
        transcript = committed_metadata[0]["_opencode_transcript_v1"]
        entry = transcript["messages"]["msg_atomic_goal"]
        assert [entry["parts"][part_id]["text"] for part_id in entry["part_order"]] == [
            "/goal Commit atomically"
        ]
        return "msg_atomic_goal"

    manager.save_session = _capture_save
    core._emit_opencode_user_message_with_metadata = _assert_committed_before_broadcast

    await session_goal_update(
        session_id,
        payload={
            "objective": "Commit atomically",
            "display_command": "/goal Commit atomically",
            "client_message_id": "msg_atomic_goal",
            "client_part_id": "part_atomic_goal",
        },
        core=typed_core,
    )

    assert len(committed_metadata) == 1
    assert committed_metadata[0]["_penguin_goal_v1"]["objective"] == (
        "Commit atomically"
    )


@pytest.mark.asyncio
async def test_goal_projection_failure_does_not_fail_committed_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(
        payload={"title": "Projection Failure"},
        core=typed_core,
        directory=str(tmp_path),
    )
    failed_projection = AsyncMock(side_effect=RuntimeError("projection failed"))
    monkeypatch.setattr(
        "penguin.web.services.session_goal.emit_session_goal_updated_events",
        failed_projection,
    )

    result = await session_goal_update(
        created["id"],
        payload={"objective": "Remain committed"},
        core=typed_core,
    )

    assert result["goal"]["objective"] == "Remain committed"
    assert (await session_goal(created["id"], core=typed_core))["goal"][
        "objective"
    ] == "Remain committed"


@pytest.mark.asyncio
async def test_goal_create_failure_rolls_back_only_owned_metadata(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(
        payload={},
        core=typed_core,
        directory=str(tmp_path),
    )
    session_id = created["id"]
    manager = core.conversation_manager.session_manager
    original_save = manager.save_session
    save_calls = 0

    def _fail_after_unrelated_update(session: Session) -> bool:
        nonlocal save_calls
        save_calls += 1
        if save_calls != 1:
            return original_save(session)
        session.metadata["title"] = "Concurrent manual title"
        session.metadata["_penguin_title_source_v1"] = "manual"
        transcript = session.metadata.setdefault(
            "_opencode_transcript_v1",
            {"messages": {}, "order": []},
        )
        transcript["messages"]["msg_concurrent"] = {
            "info": {
                "id": "msg_concurrent",
                "sessionID": session_id,
                "role": "user",
                "time": {"created": 1, "completed": 1},
            },
            "parts": {
                "part_concurrent": {
                    "id": "part_concurrent",
                    "messageID": "msg_concurrent",
                    "sessionID": session_id,
                    "type": "text",
                    "text": "Concurrent chat",
                }
            },
            "part_order": ["part_concurrent"],
        }
        transcript["order"].append("msg_concurrent")
        return False

    manager.save_session = _fail_after_unrelated_update

    with pytest.raises(HTTPException) as failure:
        await session_goal_update(
            session_id,
            payload={
                "objective": "Owned goal mutation",
                "display_command": "/goal Owned goal mutation",
                "client_message_id": "msg_owned_goal",
                "client_part_id": "part_owned_goal",
            },
            core=typed_core,
        )

    assert failure.value.status_code == 500
    assert save_calls == 2
    session = manager.load_session(session_id)
    assert session is not None
    assert "_penguin_goal_v1" not in session.metadata
    assert "_penguin_goal_create_request_v1" not in session.metadata
    assert session.metadata["title"] == "Concurrent manual title"
    assert session.metadata["_penguin_title_source_v1"] == "manual"
    transcript = session.metadata["_opencode_transcript_v1"]
    assert "msg_owned_goal" not in transcript["messages"]
    assert (
        transcript["messages"]["msg_concurrent"]["parts"]["part_concurrent"]["text"]
        == "Concurrent chat"
    )


@pytest.mark.asyncio
async def test_cancelled_goal_command_broadcast_is_best_effort(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(
        payload={},
        core=typed_core,
        directory=str(tmp_path),
    )
    session_id = created["id"]
    emitter_started = asyncio.Event()

    async def _blocked_emitter(*_args: Any, **_kwargs: Any) -> str:
        emitter_started.set()
        await asyncio.Event().wait()
        return "unreachable"

    core._emit_opencode_user_message_with_metadata = _blocked_emitter
    task = asyncio.create_task(
        session_goal_update(
            session_id,
            payload={
                "objective": "Rollback on cancellation",
                "display_command": "/goal Rollback on cancellation",
                "client_message_id": "msg_goal_cancelled",
            },
            core=typed_core,
        )
    )
    await asyncio.wait_for(emitter_started.wait(), timeout=1)
    task.cancel()

    result = await task
    assert result["goal"]["status"] == "active"
    assert (await session_goal(session_id, core=typed_core))["goal"][
        "status"
    ] == "active"
    session = core.conversation_manager.session_manager.load_session(session_id)
    assert session is not None
    transcript = session.metadata["_opencode_transcript_v1"]
    entry = transcript["messages"]["msg_goal_cancelled"]
    assert [entry["parts"][part_id]["text"] for part_id in entry["part_order"]] == [
        "/goal Rollback on cancellation"
    ]


@pytest.mark.asyncio
async def test_goal_create_exact_correlated_retry_is_idempotent(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(
        payload={"title": "Retryable Goal"},
        core=typed_core,
        directory=str(tmp_path),
    )
    session_id = created["id"]
    payload = {
        "objective": "Retry safely",
        "token_budget": 1000,
        "metadata": {"source": "test"},
        "display_command": "/goal Retry safely",
        "client_message_id": "msg_goal_first",
    }

    first = await session_goal_update(session_id, payload=payload, core=typed_core)
    retried = await session_goal_update(
        session_id,
        payload=payload,
        core=typed_core,
    )

    assert retried["goal"]["id"] == first["goal"]["id"]
    assert retried["goal"]["metadata"] == {"source": "test"}
    with pytest.raises(HTTPException) as new_request:
        await session_goal_update(
            session_id,
            payload={**payload, "client_message_id": "msg_goal_retry"},
            core=typed_core,
        )
    assert new_request.value.status_code == 409
    with pytest.raises(HTTPException) as changed_budget:
        await session_goal_update(
            session_id,
            payload={
                **payload,
                "token_budget": 2000,
                "client_message_id": "msg_goal_changed",
            },
            core=typed_core,
        )
    assert changed_budget.value.status_code == 409

    await session_goal_clear(session_id, core=typed_core)
    round_tripped = await session_goal_update(
        session_id,
        payload={
            "objective": "Round-trip public metadata",
            "metadata": retried["goal"]["metadata"],
        },
        core=typed_core,
    )
    assert round_tripped["goal"]["metadata"] == {"source": "test"}


@pytest.mark.asyncio
async def test_goal_display_command_matches_effective_mutation(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    created = await session_create(
        payload={"title": "Display Contract"},
        core=typed_core,
        directory=str(tmp_path),
    )
    session_id = created["id"]

    for payload in (
        {
            "objective": "Actual objective",
            "display_command": "/goal harmless objective",
            "client_message_id": "msg_mismatch",
        },
        {
            "objective": "Actual objective",
            "replace": True,
            "display_command": "/goal Actual objective",
            "client_message_id": "msg_hidden_replace",
        },
    ):
        with pytest.raises(HTTPException) as invalid:
            await session_goal_update(session_id, payload=payload, core=typed_core)
        assert invalid.value.status_code == 422

    created_goal = await session_goal_update(
        session_id,
        payload={
            "objective": "Whitespace works",
            "display_command": "/goal\tWhitespace\nworks",
            "client_message_id": "msg_tab_goal",
        },
        core=typed_core,
    )
    assert created_goal["goal"]["objective"] == "Whitespace works"


@pytest.mark.asyncio
async def test_goal_create_updates_only_a_fallback_session_title(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    fallback = await session_create(payload={}, core=typed_core)

    await session_goal_update(
        fallback["id"],
        payload={"objective": "A durable goal title"},
        core=typed_core,
    )

    refreshed = await session_get(fallback["id"], core=typed_core)
    assert refreshed["title"] == "A durable goal title"

    manual = await session_create(payload={"title": "Keep me"}, core=typed_core)
    await session_goal_update(
        manual["id"],
        payload={"objective": "Do not overwrite"},
        core=typed_core,
    )
    refreshed_manual = await session_get(manual["id"], core=typed_core)
    assert refreshed_manual["title"] == "Keep me"


@pytest.mark.asyncio
async def test_session_messages_prefer_transcript_over_legacy_rows(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    created = await session_create(
        payload={"title": "Transcript Wins"},
        core=typed_core,
        directory=str(tmp_path),
    )
    session_id = created["id"]

    manager = core.conversation_manager.session_manager
    session_obj = manager.load_session(session_id)
    assert session_obj is not None

    session_obj.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_transcript"],
        "messages": {
            "msg_transcript": {
                "info": {
                    "id": "msg_transcript",
                    "sessionID": session_id,
                    "role": "assistant",
                    "time": {"created": 1, "completed": 2},
                },
                "part_order": ["part_transcript"],
                "parts": {
                    "part_transcript": {
                        "id": "part_transcript",
                        "sessionID": session_id,
                        "messageID": "msg_transcript",
                        "type": "text",
                        "text": "authoritative transcript response",
                    }
                },
            }
        },
    }

    session_obj.messages.append(
        Message(
            role="assistant",
            content="polluted legacy response",
            category=MessageCategory.DIALOG,
        )
    )

    messages = await session_messages(session_id, core=typed_core, limit=None)

    assert messages is not None
    assert len(messages) == 1
    assert messages[0]["info"]["id"] == "msg_transcript"
    assert messages[0]["parts"][0]["text"] == "authoritative transcript response"


@pytest.mark.asyncio
async def test_session_update_same_title_does_not_mark_manual(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    created = await session_create(payload={}, core=typed_core)
    session_id = created["id"]

    updated = await session_update(
        session_id,
        payload={"title": created["title"]},
        core=typed_core,
    )

    assert updated["title"] == created["title"]
    assert get_session_title_source(core, session_id) == ""


@pytest.mark.asyncio
async def test_session_list_rejects_invalid_directory(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    missing = tmp_path / "does_not_exist"

    with pytest.raises(HTTPException) as exc:
        await session_list(core=typed_core, directory=str(missing))
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc_alias:
        await api_session_list(core=typed_core, directory=str(missing))
    assert exc_alias.value.status_code == 400


@pytest.mark.asyncio
async def test_session_abort_alias_and_missing_session(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    created = await api_session_create(
        payload={"title": "Abort Alias"}, core=typed_core
    )
    session_id = created["id"]

    aborted = await api_session_abort(session_id, core=typed_core)
    assert aborted is True
    assert core.abort_calls == [session_id]

    with pytest.raises(HTTPException) as exc:
        await session_abort("session_missing", core=typed_core)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_session_create_and_update_agent_mode(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    created = await session_create(
        payload={"title": "Mode Session", "agent_mode": "plan"},
        core=typed_core,
    )
    session_id = created["id"]
    assert created["agent_mode"] == "plan"

    updated = await session_update(
        session_id,
        payload={"agent_mode": "build"},
        core=typed_core,
    )
    assert updated["agent_mode"] == "build"


@pytest.mark.asyncio
async def test_session_rejects_invalid_agent_mode(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    with pytest.raises(HTTPException) as exc_create:
        await session_create(payload={"agent_mode": "invalid"}, core=typed_core)
    assert exc_create.value.status_code == 400

    created = await session_create(payload={"title": "Mode Session"}, core=typed_core)
    session_id = created["id"]

    with pytest.raises(HTTPException) as exc_update:
        await session_update(
            session_id,
            payload={"agent_mode": "invalid"},
            core=typed_core,
        )
    assert exc_update.value.status_code == 400


@pytest.mark.asyncio
async def test_session_summarize_emits_session_updated_when_title_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    created = await session_create(payload={"title": "Session"}, core=typed_core)
    session_id = created["id"]
    core.event_bus.events.clear()

    async def _fake_summarize(*_args: Any, **_kwargs: Any) -> Optional[dict[str, Any]]:
        return {
            "changed": True,
            "title": "Generated title",
            "source": "generated",
            "info": {
                "id": session_id,
                "title": "Generated title",
                "directory": str(tmp_path.resolve()),
            },
        }

    monkeypatch.setattr("penguin.web.routes.summarize_session_title", _fake_summarize)

    result = await session_summarize(
        session_id,
        payload={"providerID": "openai", "modelID": "gpt-5", "auto": False},
        core=typed_core,
    )
    assert result is True

    assert core.event_bus.events
    event_type, payload = core.event_bus.events[-1]
    assert event_type == "opencode_event"
    assert payload["type"] == "session.updated"
    assert payload["properties"]["info"]["id"] == session_id


@pytest.mark.asyncio
async def test_session_summarize_alias_and_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    created = await session_create(payload={"title": "Session"}, core=typed_core)
    session_id = created["id"]
    core.event_bus.events.clear()

    async def _fake_summarize(*_args: Any, **_kwargs: Any) -> Optional[dict[str, Any]]:
        if _args[1] == "session_missing":
            return None
        return {
            "changed": False,
            "title": "Session",
            "source": "existing",
            "info": created,
        }

    monkeypatch.setattr("penguin.web.routes.summarize_session_title", _fake_summarize)
    assert (
        await api_session_summarize(
            session_id,
            payload={"providerID": "openai", "modelID": "gpt-5"},
            core=typed_core,
        )
        is True
    )
    assert core.event_bus.events == []

    with pytest.raises(HTTPException) as exc:
        await session_summarize(
            session_id,
            payload={"providerID": 123},
            core=typed_core,
        )
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as missing:
        await session_summarize(
            "session_missing",
            payload={"providerID": "openai", "modelID": "gpt-5"},
            core=typed_core,
        )
    assert missing.value.status_code == 404
