"""After a rollback, the pre-rollback history is never written back (SM-08)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from penguin.system.conversation_manager import ConversationManager
from penguin.system.session_manager import SessionManager
from penguin.system.state import MessageCategory, Session, create_message

if TYPE_CHECKING:
    from pathlib import Path


def _message(content: str):
    return create_message(role="user", content=content, category=MessageCategory.DIALOG)


class _Checkpoints:
    """Stands in for CheckpointManager: swaps in a restored session object."""

    def __init__(self, sessions: SessionManager, restored: Session) -> None:
        self._sessions = sessions
        self._restored = restored

    async def rollback_to_checkpoint(self, checkpoint_id: str) -> bool:
        self._sessions.current_session = self._restored
        return True


@pytest.mark.asyncio
async def test_auto_save_after_rollback_keeps_the_restored_history(
    tmp_path: Path,
) -> None:
    sessions = SessionManager(base_path=str(tmp_path), auto_save_interval=0)
    live = sessions.create_session()
    live.add_message(_message("kept"))
    live.add_message(_message("rolled back"))
    sessions.mark_session_modified(live.id)

    restored = Session(id=live.id)
    restored.add_message(_message("kept"))

    manager = ConversationManager.__new__(ConversationManager)
    manager.session_manager = sessions
    manager.checkpoint_manager = _Checkpoints(sessions, restored)
    manager.conversation = SimpleNamespace(session=live, _modified=False)

    assert await manager.rollback_to_checkpoint("cp_1") is True
    sessions._auto_save_sessions()

    assert manager.conversation.session is restored
    reloaded = SessionManager(base_path=str(tmp_path), auto_save_interval=0)
    loaded = reloaded.load_session(live.id)
    assert loaded is not None
    assert [message.content for message in loaded.messages] == ["kept"]
