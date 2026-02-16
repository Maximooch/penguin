"""Tests for OpenCode-shaped session view adapters."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from penguin.system.state import Message, MessageCategory, Session
from penguin.web.services.session_view import (
    TRANSCRIPT_KEY,
    get_session_info,
    get_session_messages,
    list_session_infos,
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

    def load_session(self, session_id: str):
        item = self.sessions.get(session_id)
        if item is None:
            return None
        return item[0]


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
