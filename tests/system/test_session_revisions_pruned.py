"""Revision counters are dropped with the sessions they track.

Covers SM-106: ``SessionManager._revisions`` kept one counter for every
session id ever modified, including deleted and evicted ones, for the life
of the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.system.session_manager import SessionManager

if TYPE_CHECKING:
    from pathlib import Path


def test_deleting_and_evicting_drop_revision_counters(tmp_path: Path) -> None:
    manager = SessionManager(base_path=str(tmp_path), max_sessions_in_memory=1)
    deleted = manager.create_session()
    manager.mark_session_modified(deleted.id)
    assert manager.save_session(deleted)

    manager.delete_session(deleted.id)
    assert deleted.id not in manager._revisions

    evicted = manager.create_session()
    manager.mark_session_modified(evicted.id)
    assert manager.save_session(evicted)
    other = SessionManager(base_path=str(tmp_path)).create_session()
    SessionManager(base_path=str(tmp_path)).save_session(other)
    manager.load_session(other.id)

    assert evicted.id not in manager.sessions
    assert evicted.id not in manager._revisions
