"""A session changed while it is being saved stays marked as modified (SM-07)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.system.session_manager import SessionManager
from penguin.system.state import MessageCategory, Session, create_message

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _message(content: str):
    return create_message(role="user", content=content, category=MessageCategory.DIALOG)


def _manager_with_session(tmp_path: Path) -> tuple[SessionManager, Session]:
    manager = SessionManager(base_path=str(tmp_path), auto_save_interval=0)
    session = manager.create_session()
    session.add_message(_message("first"))
    manager.mark_session_modified(session.id)
    return manager, session


def _append_during_serialisation(
    monkeypatch: pytest.MonkeyPatch, manager: SessionManager, session: Session
) -> None:
    """Make ``to_json`` behave as if another thread appended right after it."""
    real_to_json = Session.to_json

    def to_json_then_append(self: Session) -> str:
        serialized = real_to_json(self)
        if self is session and len(self.messages) == 1:
            self.add_message(_message("arrived during save"))
            manager.mark_session_modified(self.id)
        return serialized

    monkeypatch.setattr(Session, "to_json", to_json_then_append)


def test_change_during_save_keeps_session_modified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, session = _manager_with_session(tmp_path)
    _append_during_serialisation(monkeypatch, manager, session)

    assert manager.save_session(session) is True

    assert manager.sessions[session.id][1] is True
    # SessionManager.__del__ saves modified sessions; leave nothing for it to
    # do while the patched serialiser is being torn down.
    monkeypatch.undo()
    assert manager.save_session(session) is True
    assert manager.sessions[session.id][1] is False


def test_auto_save_persists_a_change_made_during_the_previous_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, session = _manager_with_session(tmp_path)
    _append_during_serialisation(monkeypatch, manager, session)

    manager._auto_save_sessions()
    manager._auto_save_sessions()

    reloaded = SessionManager(base_path=str(tmp_path), auto_save_interval=0)
    loaded = reloaded.load_session(session.id)
    assert loaded is not None
    assert [message.content for message in loaded.messages] == [
        "first",
        "arrived during save",
    ]


def test_unchanged_session_is_clean_after_save(tmp_path: Path) -> None:
    manager, session = _manager_with_session(tmp_path)

    assert manager.save_session(session) is True

    assert manager.sessions[session.id][1] is False
