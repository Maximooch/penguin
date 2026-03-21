"""Tests for OpenCode-compatible session fork routes and service."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from penguin.system.state import Message, MessageCategory, Session
from penguin.web.routes import SessionForkRequest, api_session_fork, session_fork
from penguin.web.services.session_fork import fork_session
from penguin.web.services.session_view import TRANSCRIPT_KEY, get_session_messages


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
        self.conversation_manager = SimpleNamespace(
            session_manager=manager,
            current_agent_id="default",
            agent_session_managers={"default": manager},
        )
        self.model_config = SimpleNamespace(model="openai/gpt-5", provider="openai")


def _seed_session(core: _Core, directory: Path) -> Session:
    manager = core.conversation_manager.session_manager
    session = manager.create_session()
    session.metadata["title"] = "Alpha Session"
    session.metadata["directory"] = str(directory)

    user_1 = Message(
        id="msg_user_1",
        role="user",
        content="first prompt",
        category=MessageCategory.DIALOG,
    )
    assistant_1 = Message(
        id="msg_assistant_1",
        role="assistant",
        content="first answer",
        category=MessageCategory.DIALOG,
    )
    user_2 = Message(
        id="msg_user_2",
        role="user",
        content="second prompt",
        category=MessageCategory.DIALOG,
    )
    session.messages = [user_1, assistant_1, user_2]
    session.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_user_1", "msg_assistant_1", "msg_user_2"],
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
                        "text": "first prompt",
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
                "part_order": ["part_assistant_1"],
                "parts": {
                    "part_assistant_1": {
                        "id": "part_assistant_1",
                        "sessionID": session.id,
                        "messageID": "msg_assistant_1",
                        "type": "text",
                        "text": "first answer",
                    }
                },
            },
            "msg_user_2": {
                "info": {
                    "id": "msg_user_2",
                    "sessionID": session.id,
                    "role": "user",
                    "time": {"created": 3, "completed": 3},
                },
                "part_order": ["part_user_2"],
                "parts": {
                    "part_user_2": {
                        "id": "part_user_2",
                        "sessionID": session.id,
                        "messageID": "msg_user_2",
                        "type": "text",
                        "text": "second prompt",
                    }
                },
            },
        },
    }
    manager.save_session(session)
    core._opencode_session_directories[session.id] = str(directory)
    return session


def test_fork_session_clones_history_before_requested_message(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    source = _seed_session(core, tmp_path)

    info = fork_session(cast(Any, core), source.id, message_id="msg_user_2")

    assert info is not None
    assert info["id"] != source.id
    assert info["title"] == "Alpha Session (fork #1)"
    assert info["directory"] == str(tmp_path)

    forked = core.conversation_manager.session_manager.load_session(info["id"])
    assert forked is not None
    assert forked.metadata["forked_from_session_id"] == source.id
    assert forked.metadata["forked_from_message_id"] == "msg_user_2"

    rows = get_session_messages(cast(Any, core), info["id"])
    assert rows is not None
    assert len(rows) == 2
    assert [row["info"]["role"] for row in rows] == ["user", "assistant"]
    assert rows[0]["info"]["id"] != "msg_user_1"
    assert rows[1]["info"]["id"] != "msg_assistant_1"
    assert rows[1]["info"]["parentID"] == rows[0]["info"]["id"]


@pytest.mark.asyncio
async def test_session_fork_route_emits_created_event(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    source = _seed_session(core, tmp_path)

    info = await session_fork(
        source.id,
        payload=SessionForkRequest(messageID="msg_user_2"),
        core=cast(Any, core),
        directory=None,
    )

    assert info["title"] == "Alpha Session (fork #1)"
    event_type, payload = core.event_bus.events[-1]
    assert event_type == "opencode_event"
    assert payload["type"] == "session.created"
    assert payload["properties"]["sessionID"] == info["id"]


@pytest.mark.asyncio
async def test_session_fork_alias_and_missing_session(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    source = _seed_session(core, tmp_path)

    info = await api_session_fork(
        source.id,
        payload=SessionForkRequest(messageID="msg_user_2"),
        core=cast(Any, core),
        directory=None,
    )
    assert info["id"] != source.id

    with pytest.raises(HTTPException) as exc:
        await session_fork(
            "session_missing",
            payload=SessionForkRequest(messageID="msg_user_2"),
            core=cast(Any, core),
            directory=None,
        )
    assert exc.value.status_code == 404
