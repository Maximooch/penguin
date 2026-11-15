"""Removing the current agent moves every "current" binding to the default agent.

Covers SM-53: ``remove_agent`` reset ``current_agent_id`` and ``conversation``
but left ``session_manager``, ``checkpoint_manager``, ``context_window`` and
the context loader pointing at the removed agent's objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.system.conversation_manager import ConversationManager

if TYPE_CHECKING:
    from pathlib import Path


def test_removing_the_current_agent_rebinds_everything_to_default(
    tmp_path: Path,
) -> None:
    manager = ConversationManager(workspace_path=tmp_path)
    manager.set_current_agent("helper")
    assert manager.session_manager is manager.agent_session_managers["helper"]

    assert manager.remove_agent("helper") is True

    assert manager.current_agent_id == "default"
    assert manager.conversation is manager.agent_sessions["default"]
    assert manager.session_manager is manager.agent_session_managers["default"]
    assert manager.checkpoint_manager is manager.agent_checkpoint_managers.get(
        "default"
    )
    assert manager.context_window is manager.agent_context_windows["default"]
    loader = getattr(manager, "context_loader", None)
    if loader is not None:
        assert loader.context_manager is manager.conversation
