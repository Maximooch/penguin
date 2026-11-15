"""A session whose save fails is not evicted from the session cache.

Covers SM-80: when the cache was full, the oldest session was saved if
modified and then removed whatever the save returned, so its unsaved
messages were lost when the write failed (disk full, a locked file).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.system import session_manager as session_manager_module
from penguin.system.session_manager import SessionManager
from penguin.system.state import Message, MessageCategory

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_a_session_that_cannot_be_saved_stays_in_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SessionManager(base_path=str(tmp_path), max_sessions_in_memory=1)
    other = writer.create_session()
    assert writer.save_session(other)

    manager = SessionManager(base_path=str(tmp_path), max_sessions_in_memory=1)
    unsaved = manager.create_session()
    unsaved.add_message(
        Message(role="user", content="keep me", category=MessageCategory.DIALOG)
    )
    manager.mark_session_modified(unsaved.id)

    def disk_full(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(session_manager_module, "atomic_write_text", disk_full)

    assert manager.load_session(other.id) is not None

    assert unsaved.id in manager.sessions
    kept, modified = manager.sessions[unsaved.id]
    assert kept is unsaved and modified is True
