"""Tests for OpenCode persistence runtime helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import opencode_persistence, opencode_transcript


class _Manager:
    def __init__(self, session: SimpleNamespace, *, fail_save: bool = False) -> None:
        self.session = session
        self.fail_save = fail_save
        self.modified: list[str] = []
        self.saved: list[str] = []

    def mark_session_modified(self, session_id: str) -> None:
        self.modified.append(session_id)

    def save_session(self, session: SimpleNamespace) -> bool:
        if self.fail_save:
            raise RuntimeError("save failed")
        self.saved.append(session.id)
        self.session = session
        return True


def _owner(
    session: SimpleNamespace,
    manager: _Manager,
    *,
    model_config: Any = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        model_config=model_config,
        runtime_config=SimpleNamespace(
            active_root="/tmp/project",
            project_root="/tmp/project",
        ),
        _opencode_session_directories={session.id: "/tmp/session-project"},
        _find_session_store=lambda session_id: (
            (session, manager) if session_id == session.id else (None, None)
        ),
    )


def test_resolve_opencode_model_state_prefers_session_metadata() -> None:
    session = SimpleNamespace(
        id="session_1",
        metadata={
            "_opencode_provider_id_v1": "openrouter",
            "_opencode_model_id_v1": "z-ai/glm-5-turbo",
            "_opencode_variant_v1": "high",
        },
    )
    manager = _Manager(session)
    owner = _owner(
        session,
        manager,
        model_config=SimpleNamespace(model="fallback-model", provider="fallback"),
    )

    state = opencode_persistence.resolve_opencode_model_state(
        owner,
        session_id="session_1",
    )

    assert state == {
        "providerID": "openrouter",
        "modelID": "z-ai/glm-5-turbo",
        "variant": "high",
    }


@pytest.mark.asyncio
async def test_persist_opencode_event_synthesizes_part_first_message_info() -> None:
    session = SimpleNamespace(
        id="session_1",
        metadata={
            "_opencode_provider_id_v1": "openrouter",
            "_opencode_model_id_v1": "z-ai/glm-5-turbo",
            "_opencode_variant_v1": "high",
        },
    )
    manager = _Manager(session)
    owner = _owner(session, manager)

    await opencode_persistence.persist_opencode_event(
        owner,
        "message.part.updated",
        {
            "part": {
                "id": "part_text",
                "sessionID": "session_1",
                "messageID": "msg_1",
                "type": "text",
                "text": "hello",
            }
        },
        logger=SimpleNamespace(warning=lambda *_args, **_kwargs: None),
    )

    transcript = session.metadata[opencode_transcript.TRANSCRIPT_KEY]
    message = transcript["messages"]["msg_1"]
    assert manager.modified == ["session_1"]
    assert manager.saved == []
    assert message["info"]["providerID"] == "openrouter"
    assert message["info"]["modelID"] == "z-ai/glm-5-turbo"
    assert message["info"]["variant"] == "high"
    assert message["info"]["path"] == {
        "cwd": "/tmp/session-project",
        "root": "/tmp/session-project",
    }
    assert message["part_order"] == ["part_text"]


@pytest.mark.asyncio
async def test_persist_opencode_event_logs_save_failures() -> None:
    session = SimpleNamespace(id="session_1", metadata={})
    manager = _Manager(session, fail_save=True)
    owner = _owner(session, manager)
    warnings: list[tuple[str, dict[str, Any]]] = []

    await opencode_persistence.persist_opencode_event(
        owner,
        "message.part.updated",
        {
            "part": {
                "id": "part_tool",
                "sessionID": "session_1",
                "messageID": "msg_1",
                "type": "tool",
                "state": {"status": "completed"},
            }
        },
        logger=SimpleNamespace(
            warning=lambda message, **kwargs: warnings.append((message, kwargs))
        ),
    )

    assert manager.modified == ["session_1"]
    assert manager.saved == []
    assert warnings == [
        ("Unable to persist OpenCode transcript event", {"exc_info": True})
    ]
