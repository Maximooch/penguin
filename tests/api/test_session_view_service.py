"""Tests for OpenCode-shaped session view adapters."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.system.session_manager import SessionManager
from penguin.system.state import Message, MessageCategory, Session
from penguin.web.services.session_summary import summarize_session_title
from penguin.web.services.session_view import (
    MODEL_ID_KEY,
    PROVIDER_ID_KEY,
    REVERT_KEY,
    SUMMARY_KEY,
    TITLE_SOURCE_AUTO,
    TITLE_SOURCE_KEY,
    TITLE_SOURCE_MANUAL,
    TODO_KEY,
    TRANSCRIPT_KEY,
    USAGE_KEY,
    VARIANT_KEY,
    create_session_info,
    get_session_diff,
    get_session_info,
    get_session_messages,
    get_session_title_source,
    get_session_todo,
    list_session_infos,
    list_session_statuses,
    remove_session_info,
    update_session_info,
    update_session_todo,
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


def test_session_info_marks_blank_fallback_title_sessions():
    blank = _session("session_20260608_185439", "", "2026-02-01T00:00:00")
    blank.metadata.pop("title", None)
    active = _session("session_20260608_190001", "", "2026-02-02T00:00:00")
    active.metadata.pop("title", None)
    manual = _session("session_manual_suffix", "", "2026-02-03T00:00:00")
    manual.metadata["title"] = f"Session {manual.id[-8:]}"
    active.messages.append(
        Message(
            id="msg_user_active",
            role="user",
            content="Assess PM system gaps",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-02T00:00:00",
        )
    )
    core = _core([blank, active, manual])

    result = {item["id"]: item for item in list_session_infos(core)}

    assert result[blank.id]["title"] == f"Session {blank.id[-8:]}"
    assert result[blank.id]["fallback_title"] is True
    assert result[blank.id]["message_count"] == 0
    assert result[blank.id]["display_message_count"] == 0
    assert result[active.id]["title"] == "Assess PM system gaps"
    assert result[active.id]["fallback_title"] is False
    assert result[active.id]["message_count"] == 1
    assert result[active.id]["display_message_count"] == 1
    assert result[manual.id]["title"] == f"Session {manual.id[-8:]}"
    assert result[manual.id]["fallback_title"] is False
    assert result[manual.id]["display_message_count"] == 0


def test_list_session_infos_directory_filter_matches_exact_directory_only(
    tmp_path: Path,
):
    project_root = tmp_path / "project"
    project_root.mkdir()
    subprocess.run(
        ["git", "init"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=True,
    )

    alpha_dir = project_root / "alpha"
    beta_dir = project_root / "beta"
    alpha_dir.mkdir()
    beta_dir.mkdir()

    external_root = tmp_path / "external"
    external_root.mkdir()
    subprocess.run(
        ["git", "init"],
        cwd=external_root,
        capture_output=True,
        text=True,
        check=True,
    )
    external_dir = external_root / "gamma"
    external_dir.mkdir()

    alpha = _session("session_alpha", "Alpha", "2026-02-01T00:00:00")
    alpha.metadata["directory"] = str(alpha_dir)

    beta = _session("session_beta", "Beta", "2026-02-02T00:00:00")
    beta.metadata["directory"] = str(beta_dir)

    gamma = _session("session_gamma", "Gamma", "2026-02-03T00:00:00")
    gamma.metadata["directory"] = str(external_dir)

    core = _core([alpha, beta, gamma])

    result = list_session_infos(core, directory=str(alpha_dir))

    assert [item["id"] for item in result] == ["session_alpha"]


def test_list_session_infos_directory_filter_falls_back_to_exact_directory(
    tmp_path: Path,
):
    alpha_dir = tmp_path / "alpha"
    beta_dir = tmp_path / "beta"
    alpha_dir.mkdir()
    beta_dir.mkdir()

    alpha = _session("session_alpha", "Alpha", "2026-02-01T00:00:00")
    alpha.metadata["directory"] = str(alpha_dir)

    beta = _session("session_beta", "Beta", "2026-02-02T00:00:00")
    beta.metadata["directory"] = str(beta_dir)

    core = _core([alpha, beta])

    result = list_session_infos(core, directory=str(alpha_dir))

    assert [item["id"] for item in result] == ["session_alpha"]


def test_list_session_infos_directory_filter_excludes_unknown_directory(
    tmp_path: Path,
):
    alpha_dir = tmp_path / "alpha"
    alpha_dir.mkdir()

    alpha = _session("session_alpha", "Alpha", "2026-02-01T00:00:00")
    alpha.metadata["directory"] = str(alpha_dir)

    unknown = _session("session_unknown", "Unknown", "2026-02-02T00:00:00")
    unknown.metadata.pop("directory", None)

    core = _core([alpha, unknown])
    core.runtime_config.active_root = str(alpha_dir)
    core.runtime_config.project_root = str(alpha_dir)

    result = list_session_infos(core, directory=str(alpha_dir))

    assert [item["id"] for item in result] == ["session_alpha"]


def test_list_session_infos_uses_index_to_bound_directory_limit(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    other_dir = tmp_path / "other"
    project_dir.mkdir()
    other_dir.mkdir()

    class _IndexedOnlyManager:
        def __init__(self, sessions: list[Session]) -> None:
            self.sessions: dict[str, tuple[Session, bool]] = {}
            self._sessions = {session.id: session for session in sessions}
            self.session_index = {
                session.id: {
                    "created_at": session.created_at,
                    "last_active": session.last_active,
                    "message_count": len(session.messages),
                    "title": session.metadata.get("title", ""),
                    "directory": session.metadata.get("directory", ""),
                }
                for session in sessions
            }
            self.current_session: Session | None = None
            self.base_path = tmp_path / "missing-conversations"
            self.format = "json"
            self.load_calls: list[str] = []

        def load_session(self, session_id: str) -> Session | None:
            self.load_calls.append(session_id)
            return self._sessions.get(session_id)

    def make_indexed_session(
        session_id: str,
        title: str,
        ts: str,
        directory: Path,
    ) -> Session:
        session = _session(session_id, title, ts)
        session.metadata["directory"] = str(directory)
        return session

    alpha_old = make_indexed_session(
        "session_alpha_old",
        "Alpha Old",
        "2026-02-01T00:00:00",
        project_dir,
    )
    beta_new = make_indexed_session(
        "session_beta_new",
        "Beta New",
        "2026-02-04T00:00:00",
        other_dir,
    )
    alpha_new = make_indexed_session(
        "session_alpha_new",
        "Alpha New",
        "2026-02-03T00:00:00",
        project_dir,
    )
    alpha_latest = make_indexed_session(
        "session_alpha_latest",
        "Alpha Latest",
        "2026-02-05T00:00:00",
        project_dir,
    )
    manager = _IndexedOnlyManager([alpha_old, beta_new, alpha_new, alpha_latest])
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            agent_session_managers={},
        ),
        runtime_config=SimpleNamespace(
            active_root=str(project_dir),
            project_root=str(project_dir),
        ),
        model_config=SimpleNamespace(model="test-model", provider="test-provider"),
    )

    result = list_session_infos(cast(Any, core), directory=str(project_dir), limit=2)

    assert [item["id"] for item in result] == [
        "session_alpha_latest",
        "session_alpha_new",
    ]
    assert manager.load_calls == []


def test_list_session_infos_bounds_missing_index_directory_loads(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    other_dir = tmp_path / "other"
    project_dir.mkdir()
    other_dir.mkdir()

    class _LegacyIndexManager:
        def __init__(self, sessions: list[Session]) -> None:
            self.sessions: dict[str, tuple[Session, bool]] = {}
            self._sessions = {session.id: session for session in sessions}
            self.session_index = {
                session.id: {
                    "created_at": session.created_at,
                    "last_active": session.last_active,
                    "message_count": len(session.messages),
                    "title": session.metadata.get("title", ""),
                }
                for session in sessions
            }
            self.current_session: Session | None = None
            self.base_path = tmp_path / "missing-conversations"
            self.format = "json"
            self.load_calls: list[str] = []
            self.saved_index: dict[str, dict[str, Any]] | None = None

        def load_session(self, session_id: str) -> Session | None:
            self.load_calls.append(session_id)
            session = self._sessions.get(session_id)
            if session is not None:
                self.sessions[session_id] = (session, False)
            return session

        def _save_index(self, index: dict[str, dict[str, Any]]) -> None:
            self.saved_index = {key: dict(value) for key, value in index.items()}

    def make_session(
        session_id: str,
        title: str,
        ts: str,
        directory: Path,
    ) -> Session:
        session = _session(session_id, title, ts)
        session.metadata["directory"] = str(directory)
        return session

    sessions = [
        make_session(
            "session_other_newest",
            "Other Newest",
            "2026-02-05T00:00:00",
            other_dir,
        ),
        make_session(
            "session_project_latest",
            "Project Latest",
            "2026-02-04T00:00:00",
            project_dir,
        ),
        make_session(
            "session_project_older",
            "Project Older",
            "2026-02-03T00:00:00",
            project_dir,
        ),
        make_session(
            "session_other_oldest",
            "Other Oldest",
            "2026-02-02T00:00:00",
            other_dir,
        ),
    ]
    manager = _LegacyIndexManager(sessions)
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            agent_session_managers={},
        ),
        runtime_config=SimpleNamespace(
            active_root=str(project_dir),
            project_root=str(project_dir),
        ),
        model_config=SimpleNamespace(model="test-model", provider="test-provider"),
    )

    result = list_session_infos(cast(Any, core), directory=str(project_dir), limit=1)

    assert [item["id"] for item in result] == ["session_project_latest"]
    assert manager.load_calls == ["session_other_newest", "session_project_latest"]
    assert manager.saved_index is not None
    assert manager.saved_index["session_project_latest"]["directory"] == str(
        project_dir
    )


def test_list_session_infos_caches_missing_directory_index_rows(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    class _LegacyIndexManager:
        def __init__(self, sessions: list[Session]) -> None:
            self.sessions: dict[str, tuple[Session, bool]] = {}
            self._sessions = {session.id: session for session in sessions}
            self.session_index = {
                session.id: {
                    "created_at": session.created_at,
                    "last_active": session.last_active,
                    "message_count": len(session.messages),
                    "title": session.metadata.get("title", ""),
                }
                for session in sessions
            }
            self.current_session: Session | None = None
            self.base_path = tmp_path / "missing-conversations"
            self.format = "json"
            self.load_calls: list[str] = []

        def load_session(self, session_id: str) -> Session | None:
            self.load_calls.append(session_id)
            session = self._sessions.get(session_id)
            if session is not None:
                self.sessions[session_id] = (session, False)
            return session

        def _save_index(self, _index: dict[str, dict[str, Any]]) -> None:
            return None

    no_directory = _session(
        "session_no_directory",
        "No Directory",
        "2026-02-05T00:00:00",
    )
    project_session = _session(
        "session_project_latest",
        "Project Latest",
        "2026-02-04T00:00:00",
    )
    project_session.metadata["directory"] = str(project_dir)
    manager = _LegacyIndexManager([no_directory, project_session])
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            agent_session_managers={},
        ),
        runtime_config=SimpleNamespace(
            active_root=str(project_dir),
            project_root=str(project_dir),
        ),
        model_config=SimpleNamespace(model="test-model", provider="test-provider"),
    )

    first = list_session_infos(cast(Any, core), directory=str(project_dir), limit=2)
    assert [item["id"] for item in first] == ["session_project_latest"]
    assert manager.load_calls == ["session_no_directory", "session_project_latest"]

    manager.load_calls.clear()
    second = list_session_infos(cast(Any, core), directory=str(project_dir), limit=2)
    assert [item["id"] for item in second] == ["session_project_latest"]
    assert manager.load_calls == []


def test_list_session_infos_loads_project_session_missing_from_index(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    manager = SessionManager(
        base_path=str(tmp_path / "conversations"),
        auto_save_interval=0,
    )
    session = _session(
        "session_missing_index",
        "PM System Roadmap",
        "2026-06-08T19:47:18",
    )
    session.metadata["directory"] = str(project_dir)
    session_path = manager.base_path / f"{session.id}.json"
    session_path.write_text(json.dumps(session.to_dict()), encoding="utf-8")

    conversation_manager = SimpleNamespace(
        session_manager=manager,
        agent_session_managers={},
    )
    core = SimpleNamespace(
        conversation_manager=conversation_manager,
        runtime_config=SimpleNamespace(
            active_root=str(project_dir),
            project_root=str(project_dir),
        ),
        model_config=SimpleNamespace(model="test-model", provider="test-provider"),
    )

    result = list_session_infos(core, directory=str(project_dir))
    info = get_session_info(core, session.id)

    assert [item["id"] for item in result] == [session.id]
    assert info is not None
    assert info["title"] == "PM System Roadmap"


def test_session_info_includes_usage_snapshot():
    session = _session("session_usage", "Usage Session", "2026-02-03T00:00:00")
    session.metadata[USAGE_KEY] = {
        "current_total_tokens": 1200,
        "max_context_window_tokens": 128000,
        "available_tokens": 126800,
        "percentage": 0.9375,
        "truncations": {
            "total_truncations": 2,
            "messages_removed": 4,
            "tokens_freed": 800,
        },
    }
    core = _core([session])

    info = get_session_info(core, session.id)

    assert info is not None
    assert info["usage"]["current_total_tokens"] == 1200
    assert info["usage"]["truncations"]["total_truncations"] == 2


def test_session_info_includes_revert_and_summary_payloads():
    session = _session("session_revert", "Revert Session", "2026-02-03T00:00:00")
    session.metadata[REVERT_KEY] = {
        "messageID": "msg_user_1",
        "partID": "part_1",
        "snapshot": "revert_123",
        "diff": "--- a/src/app.py\n+++ b/src/app.py\n",
        "hiddenMessageIDs": ["msg_user_1", "msg_assistant_1"],
    }
    session.metadata[SUMMARY_KEY] = {
        "additions": 2,
        "deletions": 1,
        "files": 1,
        "diffs": [{"file": "src/app.py", "additions": 2, "deletions": 1}],
    }
    core = _core([session])

    info = get_session_info(core, session.id)

    assert info is not None
    assert info["revert"]["messageID"] == "msg_user_1"
    assert info["revert"]["snapshot"] == "revert_123"
    assert info["revert"]["hiddenMessageIDs"] == ["msg_user_1", "msg_assistant_1"]
    assert info["summary"]["files"] == 1
    assert info["summary"]["diffs"][0]["file"] == "src/app.py"


def test_session_info_includes_subagent_lineage_fields():
    session = _session("session_child", "Child Session", "2026-02-03T00:00:00")
    session.metadata["parentID"] = "session_parent"
    session.metadata["agent_id"] = "sub_agent_alpha"
    session.metadata["parent_agent_id"] = "default"
    core = _core([session])

    info = get_session_info(core, session.id)

    assert info is not None
    assert info["parentID"] == "session_parent"
    assert info["agent_id"] == "sub_agent_alpha"
    assert info["parent_agent_id"] == "default"


def test_list_session_infos_keeps_child_sessions_visible_until_roots_filter_is_used():
    parent = _session("session_parent", "Parent Session", "2026-02-01T00:00:00")
    child_a = _session("session_child_a", "Child A", "2026-02-02T00:00:00")
    child_b = _session("session_child_b", "Child B", "2026-02-03T00:00:00")
    child_a.metadata["parentID"] = parent.id
    child_a.metadata["agent_id"] = "child-a"
    child_a.metadata["parent_agent_id"] = "default"
    child_b.metadata["parentID"] = parent.id
    child_b.metadata["agent_id"] = "child-b"
    child_b.metadata["parent_agent_id"] = "default"
    core = _core([parent, child_a, child_b])

    visible = list_session_infos(core)
    roots_only = list_session_infos(core, roots=True)

    assert [item["id"] for item in visible] == [
        "session_child_b",
        "session_child_a",
        "session_parent",
    ]
    assert visible[0]["parentID"] == parent.id
    assert visible[1]["parentID"] == parent.id
    assert [item["id"] for item in roots_only] == ["session_parent"]


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


def test_get_session_messages_legacy_assistant_preserves_agent_id():
    now = datetime.now().isoformat()
    session = _session("session_agent_legacy", "Legacy Agent Session", now)
    session.metadata["agent_id"] = "child-agent"
    session.messages.append(
        Message(
            id="msg_assistant",
            role="assistant",
            content="Child agent response",
            category=MessageCategory.DIALOG,
            timestamp=now,
            agent_id="child-agent",
        )
    )
    core = _core([session])

    messages = get_session_messages(core, session.id)

    assert messages is not None
    assert len(messages) == 1
    assert messages[0]["info"]["agent"] == "child-agent"


def test_get_session_messages_legacy_assistant_uses_session_agent_fallback():
    now = datetime.now().isoformat()
    session = _session("session_agent_fallback", "Fallback Agent Session", now)
    session.metadata["agent_id"] = "child-fallback"
    session.messages.append(
        Message(
            id="msg_assistant",
            role="assistant",
            content="Fallback agent response",
            category=MessageCategory.DIALOG,
            timestamp=now,
        )
    )
    core = _core([session])

    messages = get_session_messages(core, session.id)

    assert messages is not None
    assert len(messages) == 1
    assert messages[0]["info"]["agent"] == "child-fallback"


def test_get_session_messages_prefers_transcript_over_legacy_rows():
    now = datetime.now().isoformat()
    session = _session("session_merge", "Merged Session", now)
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="hello",
            category=MessageCategory.DIALOG,
            timestamp=now,
        )
    )
    session.messages.append(
        Message(
            id="msg_assistant",
            role="assistant",
            content="assistant from legacy",
            category=MessageCategory.DIALOG,
            timestamp=now,
        )
    )
    session.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_assistant"],
        "messages": {
            "msg_assistant": {
                "info": {
                    "id": "msg_assistant",
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
                "part_order": ["part_transcript"],
                "parts": {
                    "part_transcript": {
                        "id": "part_transcript",
                        "sessionID": session.id,
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "assistant from transcript",
                    }
                },
            }
        },
    }
    core = _core([session])

    messages = get_session_messages(core, session.id)

    assert messages is not None
    assert [item["info"]["id"] for item in messages] == ["msg_assistant", "msg_user"]
    assert messages[0]["parts"][0]["text"] == "assistant from transcript"


def test_get_session_messages_merges_legacy_user_rows_when_transcript_omits_them():
    now = datetime.now().isoformat()
    user_created = int(datetime.fromisoformat(now).timestamp() * 1000)
    session = _session("session_transcript_users", "Transcript Users", now)
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="please update the port",
            category=MessageCategory.DIALOG,
            timestamp=now,
        )
    )
    session.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_assistant"],
        "messages": {
            "msg_assistant": {
                "info": {
                    "id": "msg_assistant",
                    "sessionID": session.id,
                    "role": "assistant",
                    "time": {
                        "created": user_created + 1,
                        "completed": user_created + 2,
                    },
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
                "part_order": ["part_assistant"],
                "parts": {
                    "part_assistant": {
                        "id": "part_assistant",
                        "sessionID": session.id,
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "done",
                    }
                },
            }
        },
    }
    core = _core([session])

    messages = get_session_messages(core, session.id)

    assert messages is not None
    assert [item["info"]["role"] for item in messages] == ["user", "assistant"]
    assert messages[0]["info"]["id"] == "msg_user"
    assert messages[1]["info"]["id"] == "msg_assistant"


def test_get_session_messages_dedupes_equivalent_transcript_and_legacy_users():
    transcript_created = int(
        datetime.fromisoformat("2026-02-03T00:00:10").timestamp() * 1000
    )
    session = _session(
        "session_transcript_user_dedupe",
        "Transcript User Dedupe",
        "2026-02-03T00:00:00",
    )
    session.messages.append(
        Message(
            id="msg_user_legacy",
            role="user",
            content="Please update the port",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:00:10",
        )
    )
    session.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_user_transcript", "msg_assistant"],
        "messages": {
            "msg_user_transcript": {
                "info": {
                    "id": "msg_user_transcript",
                    "sessionID": session.id,
                    "role": "user",
                    "time": {"created": transcript_created},
                    "agent": "default",
                    "model": {"providerID": "p", "modelID": "m"},
                },
                "part_order": ["part_user"],
                "parts": {
                    "part_user": {
                        "id": "part_user",
                        "sessionID": session.id,
                        "messageID": "msg_user_transcript",
                        "type": "text",
                        "text": "please   update the   port",
                    }
                },
            },
            "msg_assistant": {
                "info": {
                    "id": "msg_assistant",
                    "sessionID": session.id,
                    "role": "assistant",
                    "time": {
                        "created": transcript_created + 1000,
                        "completed": transcript_created + 2000,
                    },
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
                "part_order": ["part_assistant"],
                "parts": {
                    "part_assistant": {
                        "id": "part_assistant",
                        "sessionID": session.id,
                        "messageID": "msg_assistant",
                        "type": "text",
                        "text": "done",
                    }
                },
            },
        },
    }
    core = _core([session])

    messages = get_session_messages(core, session.id)

    assert messages is not None
    assert [item["info"]["id"] for item in messages] == [
        "msg_user_transcript",
        "msg_assistant",
    ]


def test_session_todo_round_trip():
    session = _session("session_todo", "Todo Session", "2026-02-03T00:00:00")
    core = _core([session])

    persisted = update_session_todo(
        core,
        session.id,
        [
            {
                "id": "todo_1",
                "content": "Implement session.todo endpoint",
                "status": "in_progress",
                "priority": "high",
            },
            {
                "id": "todo_2",
                "content": "Emit todo.updated events",
                "status": "pending",
                "priority": "medium",
            },
        ],
    )

    assert persisted is not None
    assert len(persisted) == 2
    assert session.metadata[TODO_KEY] == persisted

    todos = get_session_todo(core, session.id)
    assert todos == persisted


def test_session_todo_returns_none_for_missing_session():
    core = _core([])
    assert get_session_todo(core, "session_missing") is None
    assert update_session_todo(core, "session_missing", []) is None


@pytest.mark.asyncio
async def test_summarize_session_title_prefers_model_generation(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session("session_summary", "Session 1234", "2026-02-03T00:00:00")
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="Implement OpenCode session summarize endpoint parity",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:00:00",
        )
    )
    core = _core([session])
    core.model_config.service_tier = "priority"
    captured: dict[str, object] = {}

    class _FakeAPIClient:
        def __init__(self, model_config):
            self.model_config = model_config
            captured["service_tier"] = getattr(model_config, "service_tier", None)

        async def get_response(self, messages, **kwargs):
            del messages, kwargs
            return "Session summarize parity"

    monkeypatch.setattr(
        "penguin.web.services.session_summary.APIClient", _FakeAPIClient
    )

    result = await summarize_session_title(
        core,
        session.id,
        provider_id="openai",
        model_id="gpt-5",
    )

    assert result is not None
    assert result["changed"] is True
    assert result["source"] == "generated"
    assert result["title"] == "Session summarize parity"
    assert captured["service_tier"] == "priority"

    info = get_session_info(core, session.id)
    assert info is not None
    assert info["title"] == "Session summarize parity"
    assert session.metadata[TITLE_SOURCE_KEY] == TITLE_SOURCE_AUTO


@pytest.mark.asyncio
async def test_summarize_session_title_preserves_manual_title(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session("session_manual_title", "Manual Title", "2026-02-03T00:00:00")
    session.metadata[TITLE_SOURCE_KEY] = TITLE_SOURCE_MANUAL
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="Implement OpenCode session summarize endpoint parity",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:00:00",
        )
    )
    core = _core([session])

    class _FakeAPIClient:
        def __init__(self, model_config):
            self.model_config = model_config

        async def get_response(self, messages, **kwargs):
            del messages, kwargs
            return "Generated Title"

    monkeypatch.setattr(
        "penguin.web.services.session_summary.APIClient", _FakeAPIClient
    )

    result = await summarize_session_title(core, session.id)

    assert result is not None
    assert result["changed"] is False
    assert result["source"] == "manual"
    assert result["title"] == "Manual Title"
    assert session.metadata["title"] == "Manual Title"
    assert session.metadata[TITLE_SOURCE_KEY] == TITLE_SOURCE_MANUAL


@pytest.mark.asyncio
async def test_summarize_session_title_ignores_low_signal_greeting(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session("session_greeting", "Session greet", "2026-02-03T00:00:00")
    session.metadata.pop("title", None)
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="howdy",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:00:00",
        )
    )
    core = _core([session])

    class _UnexpectedAPIClient:
        def __init__(self, model_config):
            del model_config
            raise AssertionError("low-signal greeting should not title the session")

    monkeypatch.setattr(
        "penguin.web.services.session_summary.APIClient", _UnexpectedAPIClient
    )

    result = await summarize_session_title(
        core,
        session.id,
        fallback_text="howdy",
    )

    assert result is not None
    assert result["changed"] is False
    assert result["source"] == "insufficient_context"
    assert result["snippet_count"] == 0
    assert "title" not in session.metadata
    assert TITLE_SOURCE_KEY not in session.metadata


@pytest.mark.asyncio
async def test_summarize_session_title_prefers_session_model_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session("session_summary_meta", "Session 1234", "2026-02-03T00:00:00")
    session.metadata["_opencode_provider_id_v1"] = "openrouter"
    session.metadata["_opencode_model_id_v1"] = "z-ai/glm-5-turbo"
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="Implement session restore parity",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:00:00",
        )
    )
    core = _core([session])
    core.model_config = SimpleNamespace(model="z-ai/glm-4.7", provider="openrouter")
    seen_model_config: dict[str, str | None] = {}

    class _FakeAPIClient:
        def __init__(self, model_config):
            seen_model_config["model"] = getattr(model_config, "model", None)
            seen_model_config["provider"] = getattr(model_config, "provider", None)

        async def get_response(self, messages, **kwargs):
            del messages, kwargs
            return "Session restore parity"

    monkeypatch.setattr(
        "penguin.web.services.session_summary.APIClient", _FakeAPIClient
    )

    result = await summarize_session_title(core, session.id)

    assert result is not None
    assert result["changed"] is True
    assert seen_model_config == {
        "model": "z-ai/glm-5-turbo",
        "provider": "openrouter",
    }


@pytest.mark.asyncio
async def test_summarize_session_title_falls_back_to_heuristic(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session("session_heuristic", "Session heur", "2026-02-03T00:00:00")
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="Investigate queued cancel behavior under heavy streaming",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:00:00",
        )
    )
    core = _core([session])

    class _FailingAPIClient:
        def __init__(self, model_config):
            del model_config
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "penguin.web.services.session_summary.APIClient", _FailingAPIClient
    )

    result = await summarize_session_title(core, session.id)

    assert result is not None
    assert result["changed"] is True
    assert result["source"] == "heuristic"
    assert result["title"].startswith("Investigate queued cancel behavior")


@pytest.mark.asyncio
async def test_summarize_session_title_rejects_provider_empty_content_note(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session("session_note", "Session note", "2026-02-03T00:00:00")
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="Start a fresh coding session and inspect workspace",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:00:00",
        )
    )
    core = _core([session])

    class _FakeAPIClient:
        def __init__(self, model_config):
            self.model_config = model_config

        async def get_response(self, messages, **kwargs):
            del messages, kwargs
            return (
                "[Note: Model processed the request but returned empty content. "
                "Try rephrasing...]"
            )

    monkeypatch.setattr(
        "penguin.web.services.session_summary.APIClient", _FakeAPIClient
    )

    result = await summarize_session_title(core, session.id)

    assert result is not None
    assert result["changed"] is True
    assert result["source"] == "heuristic"
    assert result["title"] == "Start a fresh coding session and inspect workspace"


@pytest.mark.asyncio
async def test_summarize_session_title_returns_none_for_missing_session():
    core = _core([])
    assert await summarize_session_title(core, "session_missing") is None


@pytest.mark.asyncio
async def test_summarize_session_title_uses_fallback_text_when_no_user_messages(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session("session_fallback", "Session back", "2026-02-03T00:00:00")
    core = _core([session])

    class _FailingAPIClient:
        def __init__(self, model_config):
            del model_config
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "penguin.web.services.session_summary.APIClient", _FailingAPIClient
    )

    result = await summarize_session_title(
        core,
        session.id,
        fallback_text="Investigate flaky title update behavior",
    )

    assert result is not None
    assert result["changed"] is True
    assert result["source"] == "heuristic"
    assert result["used_fallback_text"] is True
    assert result["snippet_count"] == 1
    assert result["title"].startswith("Investigate flaky title update behavior")


@pytest.mark.asyncio
async def test_summarize_session_title_persists_when_only_inferred_title_exists(
    monkeypatch: pytest.MonkeyPatch,
):
    session = _session("session_inferred", "placeholder", "2026-02-03T00:00:00")
    session.metadata.pop("title", None)
    session.messages.append(
        Message(
            id="msg_user",
            role="user",
            content="What is the Jesus prayer?",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:00:00",
        )
    )
    core = _core([session])

    class _FailingAPIClient:
        def __init__(self, model_config):
            del model_config
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "penguin.web.services.session_summary.APIClient", _FailingAPIClient
    )

    result = await summarize_session_title(core, session.id)

    assert result is not None
    assert result["source"] == "heuristic"
    assert result["changed"] is True
    assert result["title"] == "What is the Jesus prayer?"

    info = get_session_info(core, session.id)
    assert info is not None
    assert info["title"] == "What is the Jesus prayer?"


def test_list_session_infos_handles_mutating_index():
    now = "2026-02-03T00:00:00"
    session = _session("session_primary", "Primary", now)

    class _MutatingManager(_Manager):
        def load_session(self, session_id: str):
            if "session_secondary" not in self.session_index:
                self.session_index["session_secondary"] = {
                    "created_at": now,
                    "last_active": now,
                    "title": "Secondary",
                }
            return super().load_session(session_id)

    mutating = _MutatingManager([session])
    conversation_manager = SimpleNamespace(
        session_manager=mutating,
        agent_session_managers={"default": mutating},
    )
    runtime_config = SimpleNamespace(
        active_root="/tmp/workspace", project_root="/tmp/workspace"
    )
    model_config = SimpleNamespace(model="test-model", provider="test-provider")
    core = SimpleNamespace(
        conversation_manager=conversation_manager,
        runtime_config=runtime_config,
        model_config=model_config,
    )

    result = list_session_infos(core)

    assert any(item["id"] == "session_primary" for item in result)


def test_session_view_reads_do_not_mutate_current_session() -> None:
    current = _session("session_current", "Current", "2026-02-01T00:00:00")
    target = _session("session_target", "Target", "2026-02-02T00:00:00")
    target.metadata[TODO_KEY] = [
        {"id": "todo_1", "content": "Investigate bleed", "status": "pending"}
    ]
    target.metadata["directory"] = "/tmp/workspace/target"
    target.messages.append(
        Message(
            id="msg_target_user",
            role="user",
            content="hello",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-02T00:00:00",
        )
    )

    class _LoadingManager(_Manager):
        def __init__(self, sessions: list[Session]):
            super().__init__(sessions)
            self._store = {session.id: session for session in sessions}

        def load_session(self, session_id: str):
            session = self._store.get(session_id)
            if session is None:
                return None
            self.current_session = session
            self.sessions[session_id] = (session, False)
            return session

    manager = _LoadingManager([current, target])
    manager.sessions.pop(target.id, None)
    manager.current_session = current
    conversation_manager = SimpleNamespace(
        session_manager=manager,
        agent_session_managers={"default": manager},
    )
    runtime_config = SimpleNamespace(
        active_root="/tmp/workspace", project_root="/tmp/workspace"
    )
    model_config = SimpleNamespace(model="test-model", provider="test-provider")
    core = SimpleNamespace(
        conversation_manager=conversation_manager,
        runtime_config=runtime_config,
        model_config=model_config,
    )

    info = get_session_info(core, target.id)
    messages = get_session_messages(core, target.id)
    todos = get_session_todo(core, target.id)
    diffs = get_session_diff(core, target.id)

    assert info is not None
    assert messages is not None
    assert todos is not None
    assert diffs == []
    assert manager.current_session is current


def test_list_session_infos_does_not_mutate_current_session() -> None:
    current = _session("session_current", "Current", "2026-02-01T00:00:00")
    target = _session("session_target", "Target", "2026-02-02T00:00:00")

    class _LoadingManager(_Manager):
        def __init__(self, sessions: list[Session]):
            super().__init__(sessions)
            self._store = {session.id: session for session in sessions}

        def load_session(self, session_id: str):
            session = self._store.get(session_id)
            if session is None:
                return None
            self.current_session = session
            self.sessions[session_id] = (session, False)
            return session

    manager = _LoadingManager([current, target])
    manager.sessions.pop(target.id, None)
    manager.current_session = current
    conversation_manager = SimpleNamespace(
        session_manager=manager,
        agent_session_managers={"default": manager},
    )
    runtime_config = SimpleNamespace(
        active_root="/tmp/workspace", project_root="/tmp/workspace"
    )
    model_config = SimpleNamespace(model="test-model", provider="test-provider")
    core = SimpleNamespace(
        conversation_manager=conversation_manager,
        runtime_config=runtime_config,
        model_config=model_config,
    )

    result = list_session_infos(core)

    assert [item["id"] for item in result] == ["session_target", "session_current"]
    assert manager.current_session is current


def test_session_view_skips_recovery_substitute_from_view_load() -> None:
    corrupt = _session("session_corrupt", "Corrupt", "2026-02-01T00:00:00")
    recovery = _session("recovery_20260608_185439", "Recovery", "2026-02-02T00:00:00")

    class _RecoverySubstituteManager(_Manager):
        def __init__(self) -> None:
            super().__init__([corrupt])
            self.sessions.clear()
            self.current_session = None

        def load_session(self, session_id: str) -> Session | None:
            if session_id == corrupt.id:
                self.current_session = recovery
                return recovery
            return None

    manager = _RecoverySubstituteManager()
    conversation_manager = SimpleNamespace(
        session_manager=manager,
        agent_session_managers={"default": manager},
    )
    runtime_config = SimpleNamespace(
        active_root="/tmp/workspace", project_root="/tmp/workspace"
    )
    model_config = SimpleNamespace(model="test-model", provider="test-provider")
    core = SimpleNamespace(
        conversation_manager=conversation_manager,
        runtime_config=runtime_config,
        model_config=model_config,
    )

    assert list_session_infos(core) == []
    assert get_session_info(core, corrupt.id) is None
    assert manager.current_session is None


def test_get_session_info_returns_none_for_missing_session():
    core = _core([])
    assert get_session_info(core, "session_missing") is None


def test_get_session_info_canonicalizes_openai_model_metadata():
    session = _session("session_model_case", "Model Case", "2026-02-03T00:00:00")
    session.metadata[PROVIDER_ID_KEY] = "OpenAI"
    session.metadata[MODEL_ID_KEY] = "openai/GPT-5.5"
    core = _core([session])

    info = get_session_info(core, session.id)

    assert info is not None
    assert info["providerID"] == "openai"
    assert info["modelID"] == "gpt-5.5"
    assert info["modelSelection"] == {
        "ready": True,
        "sessionScoped": True,
        "source": "session",
        "providerID": "openai",
        "modelID": "gpt-5.5",
        "qualifiedID": "openai/gpt-5.5",
        "providerSource": "session",
        "modelSource": "session",
    }


def test_get_session_info_canonicalizes_global_model_fallback():
    session = _session("session_global_model", "Global Model", "2026-02-03T00:00:00")
    core = _core([session])
    core.model_config = SimpleNamespace(provider="OpenAI", model="openai/GPT-5.5")

    info = get_session_info(core, session.id)

    assert info is not None
    assert info["providerID"] == "openai"
    assert info["modelID"] == "gpt-5.5"
    assert info["modelSelection"] == {
        "ready": True,
        "sessionScoped": False,
        "source": "global",
        "providerID": "openai",
        "modelID": "gpt-5.5",
        "qualifiedID": "openai/gpt-5.5",
        "providerSource": "global",
        "modelSource": "global",
    }


def test_list_session_infos_exposes_index_model_selection_metadata() -> None:
    session = _session("session_index_model", "Index Model", "2026-02-03T00:00:00")
    core = _core([session])
    manager = core.conversation_manager.session_manager
    manager.session_index[session.id][PROVIDER_ID_KEY] = "OpenRouter"
    manager.session_index[session.id][MODEL_ID_KEY] = "Z-AI/GLM-5.2"

    infos = list_session_infos(core, limit=10)

    info = next(item for item in infos if item["id"] == session.id)
    assert info["providerID"] == "openrouter"
    assert info["modelID"] == "z-ai/glm-5.2"
    assert info["modelSelection"] == {
        "ready": True,
        "sessionScoped": True,
        "source": "session",
        "providerID": "openrouter",
        "modelID": "z-ai/glm-5.2",
        "qualifiedID": "openrouter/z-ai/glm-5.2",
        "providerSource": "session",
        "modelSource": "session",
    }


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
        provider_id="openrouter",
        model_id="z-ai/glm-5-turbo",
        variant="high",
    )

    session_id = created["id"]
    assert created["title"] == "Created Session"
    assert get_session_title_source(core, session_id) == TITLE_SOURCE_MANUAL
    assert created["directory"] == "/tmp/workspace/project"
    assert created["parentID"] == "parent_1"
    assert created["providerID"] == "openrouter"
    assert created["modelID"] == "z-ai/glm-5-turbo"
    assert created["variant"] == "high"
    assert isinstance(created["time"]["created"], int)

    updated = update_session_info(
        core,
        session_id,
        title="Renamed Session",
        archived=123456789,
        provider_id="openrouter",
        model_id="qwen/qwen3.5-plus-02-15",
        variant="max",
    )
    assert updated is not None
    assert updated["title"] == "Renamed Session"
    assert get_session_title_source(core, session_id) == TITLE_SOURCE_MANUAL
    assert updated["time"]["archived"] == 123456789
    assert updated["providerID"] == "openrouter"
    assert updated["modelID"] == "qwen/qwen3.5-plus-02-15"
    assert updated["variant"] == "max"

    assert remove_session_info(core, session_id) is True
    assert get_session_info(core, session_id) is None


def test_legacy_message_projection_prefers_session_model_metadata() -> None:
    session = _session("session_model_meta", "Model Metadata", "2026-02-03T00:00:00")
    session.metadata[PROVIDER_ID_KEY] = "openrouter"
    session.metadata[MODEL_ID_KEY] = "z-ai/glm-5-turbo"
    session.metadata[VARIANT_KEY] = "high"
    session.messages.append(
        Message(
            id="msg_user_model_meta",
            role="user",
            content="hello",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:00:00",
        )
    )
    session.messages.append(
        Message(
            id="msg_assistant_model_meta",
            role="assistant",
            content="hi",
            category=MessageCategory.DIALOG,
            timestamp="2026-02-03T00:01:00",
        )
    )
    core = _core([session])
    core.model_config = SimpleNamespace(
        model="global-model", provider="global-provider"
    )

    messages = get_session_messages(core, session.id)

    assert messages is not None
    user = messages[0]["info"]
    assistant = messages[1]["info"]
    assert user["model"]["providerID"] == "openrouter"
    assert user["model"]["modelID"] == "z-ai/glm-5-turbo"
    assert user["variant"] == "high"
    assert assistant["providerID"] == "openrouter"
    assert assistant["modelID"] == "z-ai/glm-5-turbo"
    assert assistant["variant"] == "high"


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


def test_list_session_statuses_marks_active_requests_busy():
    now = datetime.now().isoformat()
    session = _session("session_active", "Active Session", now)
    core = _core([session])
    core._opencode_active_requests = {"session_active": 1}

    statuses = list_session_statuses(core)
    assert statuses["session_active"]["type"] == "busy"


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
                                "diff": (
                                    "--- a/src/main.py\n"
                                    "+++ b/src/main.py\n"
                                    "@@\n"
                                    "-print('x')\n"
                                    "+print('y')\n"
                                )
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
