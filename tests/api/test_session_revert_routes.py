"""Tests for OpenCode-compatible session revert routes and service."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from penguin.system.state import Message, MessageCategory, Session
from penguin.web.routes import (
    SessionRevertRequest,
    api_session_revert,
    api_session_unrevert,
    session_revert,
    session_unrevert,
)
from penguin.web.services.session_view import REVERT_KEY, SUMMARY_KEY, TRANSCRIPT_KEY


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
        return item[0] if item else None

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
        self._opencode_active_requests: dict[str, int] = {}
        self._tui_adapters: dict[str, Any] = {}
        self.conversation_manager = SimpleNamespace(
            session_manager=manager,
            current_agent_id="default",
            agent_session_managers={"default": manager},
        )
        self.model_config = SimpleNamespace(model="openai/gpt-5", provider="openai")


def _seed_session(core: _Core, directory: Path) -> Session:
    manager = core.conversation_manager.session_manager
    session = manager.create_session()
    session.metadata["title"] = "Revert Session"
    session.metadata["directory"] = str(directory)

    diff = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    session.messages = [
        Message(
            id="msg_user_1",
            role="user",
            content="change app",
            category=MessageCategory.DIALOG,
        ),
        Message(
            id="msg_assistant_1",
            role="assistant",
            content="updated file",
            category=MessageCategory.DIALOG,
        ),
    ]
    session.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_user_1", "msg_assistant_1"],
        "messages": {
            "msg_user_1": {
                "info": {
                    "id": "msg_user_1",
                    "sessionID": session.id,
                    "role": "user",
                    "time": {"created": 1, "completed": 1},
                },
                "part_order": ["part_user_1"],
                "parts": {
                    "part_user_1": {
                        "id": "part_user_1",
                        "sessionID": session.id,
                        "messageID": "msg_user_1",
                        "type": "text",
                        "text": "change app",
                    }
                },
            },
            "msg_assistant_1": {
                "info": {
                    "id": "msg_assistant_1",
                    "sessionID": session.id,
                    "role": "assistant",
                    "parentID": "msg_user_1",
                    "time": {"created": 2, "completed": 2},
                },
                "part_order": ["part_tool_1"],
                "parts": {
                    "part_tool_1": {
                        "id": "part_tool_1",
                        "sessionID": session.id,
                        "messageID": "msg_assistant_1",
                        "type": "tool",
                        "tool": "edit",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "src/app.py"},
                            "metadata": {"diff": diff},
                        },
                    }
                },
            },
        },
    }
    manager.save_session(session)
    core._opencode_session_directories[session.id] = str(directory)
    target = directory / "src" / "app.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("new\n", encoding="utf-8")
    return session


@pytest.mark.asyncio
async def test_session_revert_and_unrevert_roundtrip(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    session = _seed_session(core, tmp_path)

    reverted = await session_revert(
        session.id,
        payload=SessionRevertRequest(messageID="msg_user_1"),
        core=cast(Any, core),
    )

    target = tmp_path / "src" / "app.py"
    assert target.read_text(encoding="utf-8") == "old\n"
    assert reverted["revert"]["messageID"] == "msg_user_1"
    assert reverted["revert"]["hiddenMessageIDs"] == ["msg_user_1", "msg_assistant_1"]
    assert reverted["summary"]["files"] == 1

    stored = core.conversation_manager.session_manager.load_session(session.id)
    assert stored is not None
    assert stored.metadata[REVERT_KEY]["snapshot"]
    assert stored.metadata[SUMMARY_KEY]["files"] == 1

    updated_event = core.event_bus.events[-2]
    diff_event = core.event_bus.events[-1]
    assert updated_event[1]["type"] == "session.updated"
    assert diff_event[1]["type"] == "session.diff"
    assert diff_event[1]["properties"]["sessionID"] == session.id

    restored = await session_unrevert(session.id, core=cast(Any, core))
    assert target.read_text(encoding="utf-8") == "new\n"
    assert "revert" not in restored
    stored = core.conversation_manager.session_manager.load_session(session.id)
    assert stored is not None
    assert REVERT_KEY not in stored.metadata
    assert SUMMARY_KEY not in stored.metadata


@pytest.mark.asyncio
async def test_session_revert_alias_and_validation(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    session = _seed_session(core, tmp_path)

    reverted = await api_session_revert(
        session.id,
        payload=SessionRevertRequest(messageID="msg_user_1"),
        core=cast(Any, core),
    )
    assert reverted["revert"]["messageID"] == "msg_user_1"

    restored = await api_session_unrevert(session.id, core=cast(Any, core))
    assert "revert" not in restored

    with pytest.raises(HTTPException) as exc:
        await session_revert(
            session.id,
            payload=SessionRevertRequest(messageID=None),
            core=cast(Any, core),
        )
    assert exc.value.status_code == 400

    core._opencode_active_requests[session.id] = 1
    with pytest.raises(HTTPException) as busy_exc:
        await session_revert(
            session.id,
            payload=SessionRevertRequest(messageID="msg_user_1"),
            core=cast(Any, core),
        )
    assert busy_exc.value.status_code == 409
