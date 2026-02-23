"""Tests for OpenCode-shaped session view adapters."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from penguin.system.state import Message, MessageCategory, Session
from penguin.web.services.session_view import (
    TRANSCRIPT_KEY,
    create_session_info,
    get_session_diff,
    get_session_info,
    get_session_messages,
    list_session_infos,
    list_session_statuses,
    remove_session_info,
    update_session_info,
)


class _Manager:
    def __init__(self, sessions: list[Session]):
        self.sessions = {session.id: (session, False) for session in sessions}
        self.session_index = {
            session.id: {
                "created_at": session.created_at,
                "last_active": session.last_active,
                "title": session.metadata.get("title", ""),
            }
            for session in sessions
        }
        self.current_session = sessions[-1] if sessions else None

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

    def load_session(self, session_id: str):
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


def _session(session_id: str, title: str, ts: str) -> Session:
    session = Session(
        id=session_id, created_at=ts, last_active=ts, metadata={"title": title}
    )
    return session


def _core(sessions: list[Session]):
    manager = _Manager(sessions)
    conversation_manager = SimpleNamespace(
        session_manager=manager,
        agent_session_managers={"default": manager},
    )
    runtime_config = SimpleNamespace(
        active_root="/tmp/workspace", project_root="/tmp/workspace"
    )
    model_config = SimpleNamespace(model="test-model", provider="test-provider")
    return SimpleNamespace(
        conversation_manager=conversation_manager,
        runtime_config=runtime_config,
        model_config=model_config,
    )


def test_list_session_infos_sorted_and_filtered():
    a = _session("session_a", "Alpha Session", "2026-02-01T00:00:00")
    b = _session("session_b", "Beta Session", "2026-02-02T00:00:00")
    core = _core([a, b])

    result = list_session_infos(core)
    assert [item["id"] for item in result] == ["session_b", "session_a"]

    filtered = list_session_infos(core, search="alpha")
    assert [item["id"] for item in filtered] == ["session_a"]


def test_get_session_messages_prefers_persisted_transcript():
    session = _session(
        "session_transcript", "Transcript Session", "2026-02-03T00:00:00"
    )
    session.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_1"],
        "messages": {
            "msg_1": {
                "info": {
                    "id": "msg_1",
                    "sessionID": session.id,
                    "role": "assistant",
                    "time": {"created": 1, "completed": 2},
                    "parentID": "root",
                    "modelID": "m",
                    "providerID": "p",
                    "mode": "chat",
                    "agent": "default",
                    "path": {"cwd": "/tmp", "root": "/tmp"},
                    "cost": 0,
                    "tokens": {
                        "input": 0,
                        "output": 0,
                        "reasoning": 0,
                        "cache": {"read": 0, "write": 0},
                    },
                },
                "part_order": ["part_1", "part_2"],
                "parts": {
                    "part_1": {
                        "id": "part_1",
                        "sessionID": session.id,
                        "messageID": "msg_1",
                        "type": "text",
                        "text": "hello",
                    },
                    "part_2": {
                        "id": "part_2",
                        "sessionID": session.id,
                        "messageID": "msg_1",
                        "type": "tool",
                        "tool": "bash",
                        "callID": "call_1",
                        "state": {
                            "status": "completed",
                            "input": {"command": "pwd"},
                            "output": "/tmp",
                            "title": "pwd",
                            "metadata": {},
                            "time": {"start": 1, "end": 2},
                        },
                    },
                },
            }
        },
    }
    core = _core([session])

    messages = get_session_messages(core, session.id)
    assert messages is not None
    assert len(messages) == 1
    assert messages[0]["info"]["id"] == "msg_1"
    assert [item["id"] for item in messages[0]["parts"]] == ["part_1", "part_2"]


def test_get_session_messages_falls_back_to_legacy_messages():
    now = datetime.now().isoformat()
    session = _session("session_legacy", "Legacy Session", now)
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="what changed?",
            category=MessageCategory.DIALOG,
            timestamp=now,
        )
    )
    session.messages.append(
        Message(
            id="msg_assistant",
            role="assistant",
            content="I updated routing.",
            category=MessageCategory.DIALOG,
            timestamp=now,
        )
    )
    core = _core([session])

    messages = get_session_messages(core, session.id)
    assert messages is not None
    assert [item["info"]["role"] for item in messages] == ["user", "assistant"]
    assert all(item["parts"][0]["type"] == "text" for item in messages)


def test_get_session_info_returns_none_for_missing_session():
    core = _core([])
    assert get_session_info(core, "session_missing") is None


def test_create_update_remove_session_info_round_trip():
    core = _core([])

    created = create_session_info(
        core,
        title="Created Session",
        parent_id="parent_1",
        directory="/tmp/workspace/project",
        permission=[
            {
                "permission": "edit",
                "pattern": "**/*.py",
                "action": "allow",
            }
        ],
    )

    session_id = created["id"]
    assert created["title"] == "Created Session"
    assert created["directory"] == "/tmp/workspace/project"
    assert created["parentID"] == "parent_1"
    assert isinstance(created["time"]["created"], int)

    updated = update_session_info(
        core,
        session_id,
        title="Renamed Session",
        archived=123456789,
    )
    assert updated is not None
    assert updated["title"] == "Renamed Session"
    assert updated["time"]["archived"] == 123456789

    assert remove_session_info(core, session_id) is True
    assert get_session_info(core, session_id) is None


def test_list_session_statuses_prefers_busy_signals():
    now = datetime.now().isoformat()
    session = _session("session_status", "Status Session", now)
    session.messages.append(
        Message(
            id="msg_user_pending",
            role="user",
            content="still waiting",
            category=MessageCategory.DIALOG,
            timestamp=now,
        )
    )
    core = _core([session])
    core._opencode_stream_states = {"session_status": {"active": True}}

    statuses = list_session_statuses(core)
    assert statuses["session_status"]["type"] == "busy"


def test_get_session_diff_prefers_transcript_tool_parts():
    session = _session("session_diff", "Diff Session", "2026-02-03T00:00:00")
    session.metadata["directory"] = "/tmp/workspace/diff-project"
    session.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_1"],
        "messages": {
            "msg_1": {
                "info": {
                    "id": "msg_1",
                    "sessionID": session.id,
                    "role": "assistant",
                    "time": {"created": 1, "completed": 2},
                },
                "part_order": ["part_tool"],
                "parts": {
                    "part_tool": {
                        "id": "part_tool",
                        "sessionID": session.id,
                        "messageID": "msg_1",
                        "type": "tool",
                        "tool": "edit",
                        "state": {
                            "status": "completed",
                            "input": {"filePath": "src/main.py"},
                            "metadata": {
                                "diff": "--- a/src/main.py\n+++ b/src/main.py\n@@\n-print('x')\n+print('y')\n"
                            },
                        },
                    }
                },
            }
        },
    }
    core = _core([session])

    diffs = get_session_diff(core, session.id)
    assert diffs is not None
    assert len(diffs) == 1
    assert diffs[0]["file"] == "src/main.py"
    assert diffs[0]["additions"] == 1
    assert diffs[0]["deletions"] == 1
