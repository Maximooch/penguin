"""A session loaded from its backup is returned even if the primary rewrite fails.

Covers SM-85: after a good backup load cached the session, a failure writing
it back to the primary file was caught as a backup failure, so the caller got
a new recovery session while the next load of the same id returned the
restored one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.system import session_manager as session_manager_module
from penguin.system.session_manager import SessionManager
from penguin.system.state import Message, MessageCategory

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_a_backup_restore_survives_a_failed_primary_rewrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = SessionManager(base_path=str(tmp_path))
    session = writer.create_session()
    session.add_message(
        Message(role="user", content="from backup", category=MessageCategory.DIALOG)
    )
    assert writer.save_session(session)
    assert writer.save_session(session)  # the second save writes the backup
    primary = tmp_path / f"{session.id}.json"
    primary.write_text("{ not json", encoding="utf-8")

    def read_only(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(session_manager_module, "atomic_write_text", read_only)
    reader = SessionManager(base_path=str(tmp_path))

    loaded = reader.load_session(session.id)

    assert loaded is not None
    assert loaded.id == session.id
    assert [message.content for message in loaded.messages] == ["from backup"]
