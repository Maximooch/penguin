"""Tests for OpenCode-compatible session parity routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from penguin.system.state import Session
from penguin.web.routes import (
    api_session_create,
    api_session_delete,
    api_session_diff,
    api_session_status,
    api_session_update,
    session_create,
    session_delete,
    session_diff,
    session_get,
    session_status,
    session_update,
)
from penguin.web.services.session_view import TRANSCRIPT_KEY


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
        self.runtime_config = SimpleNamespace(
            workspace_root=str(workspace),
            project_root=str(workspace),
            active_root=str(workspace),
        )
        self._opencode_session_directories: dict[str, str] = {}
        self._opencode_stream_states: dict[str, dict[str, Any]] = {}
        self.conversation_manager = SimpleNamespace(
            session_manager=manager,
            current_agent_id="default",
            agent_session_managers={"default": manager},
        )
        self.model_config = SimpleNamespace(model="openai/gpt-5", provider="openai")


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

    updated = await session_update(
        session_id,
        payload={"title": "Alpha Renamed", "time": {"archived": 12345}},
        core=typed_core,
    )
    assert updated["title"] == "Alpha Renamed"
    assert updated["time"]["archived"] == 12345

    status_map = await session_status(core=typed_core)
    assert status_map[session_id]["type"] == "idle"

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

    diffs = await api_session_diff(session_id, core=typed_core, messageID=None)
    assert isinstance(diffs, list)

    deleted = await api_session_delete(session_id, core=typed_core)
    assert deleted is True
