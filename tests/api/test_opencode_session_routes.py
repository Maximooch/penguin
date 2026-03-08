"""Tests for OpenCode-compatible session parity routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, cast

import pytest
from fastapi import HTTPException

from penguin.system.state import Session
from penguin.web.routes import (
    api_session_abort,
    api_session_create,
    api_session_delete,
    api_session_diff,
    api_session_list,
    api_session_summarize,
    api_session_todo,
    api_session_status,
    api_session_update,
    session_create,
    session_abort,
    session_delete,
    session_diff,
    session_get,
    session_list,
    session_summarize,
    session_todo,
    session_status,
    session_update,
)
from penguin.web.services.session_view import TODO_KEY, TRANSCRIPT_KEY


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

    async def abort_session(self, session_id: str) -> bool:
        self.abort_calls.append(session_id)
        return True


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
