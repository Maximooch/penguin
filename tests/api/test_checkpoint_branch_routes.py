"""Tests for checkpoint branch route session materialization."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.system.state import Session
from penguin.web.routes import CheckpointBranchRequest, branch_from_checkpoint


class _Manager:
    def __init__(self) -> None:
        self.sessions: dict[str, tuple[Session, bool]] = {}
        self.session_index: dict[str, dict[str, Any]] = {}
        self.current_session: Session | None = None

    def create_session(self) -> Session:
        session = Session()
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
        self.current_session = session
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

    async def branch_from_checkpoint(
        self,
        checkpoint_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> str | None:
        del checkpoint_id, description
        session = self.conversation_manager.session_manager.create_session()
        session.metadata["title"] = name or "Checkpoint Branch"
        session.metadata["directory"] = self.runtime_config.active_root
        self.conversation_manager.session_manager.save_session(session)
        return "cp_branch_123"


@pytest.mark.asyncio
async def test_branch_from_checkpoint_returns_session_info_and_emits_created(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)

    result = await branch_from_checkpoint(
        "cp_123",
        CheckpointBranchRequest(name="Experiment Branch", description="try path"),
        core=cast(Any, core),
    )

    assert result["branch_id"] == "cp_branch_123"
    assert result["session"]["title"] == "Experiment Branch"
    assert result["session"]["directory"] == str(tmp_path)
    event_type, payload = core.event_bus.events[-1]
    assert event_type == "opencode_event"
    assert payload["type"] == "session.created"
    assert payload["properties"]["info"]["id"] == result["session"]["id"]
