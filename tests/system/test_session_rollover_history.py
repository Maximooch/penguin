"""A session that reaches its message limit keeps working under its own id.

Covers SM-111: at the limit, the conversation moved to a continuation session
with a new id that held only the system prompt and a "Continuing from" note.
Clients address a session by id, so the next prompt loaded the original
again, crossed the limit again, and sent a request with no input: the session
stopped answering. The live session now keeps its id and carries its recent
history; the full older history is archived under a new id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from penguin.system.conversation import ConversationSystem
from penguin.system.session_manager import SessionManager
from penguin.system.state import MessageCategory

if TYPE_CHECKING:
    from pathlib import Path


def _conversation(tmp_path: Path) -> tuple[ConversationSystem, SessionManager]:
    store = SessionManager(
        base_path=str(tmp_path), max_messages_per_session=20, auto_save_interval=0
    )
    conversation = ConversationSystem(session_manager=store, system_prompt="")
    conversation.session = store.create_session()
    conversation.add_message("system", "You are Penguin.", MessageCategory.SYSTEM)
    return conversation, store


def test_rollover_keeps_the_id_and_recent_history(tmp_path: Path) -> None:
    conversation, store = _conversation(tmp_path)
    session_id = conversation.session.id
    for index in range(1, 30):
        role = "user" if index % 2 else "assistant"
        conversation.add_message(role, f"message {index}", MessageCategory.DIALOG)

    live = conversation.session
    assert live.id == session_id
    assert len(live.messages) < 20
    dialog = [m.content for m in live.messages if m.category is MessageCategory.DIALOG]
    assert dialog[-1] == "message 29"
    assert len(dialog) >= 2 and dialog[0].startswith("message ")
    assert live.messages[0].content == "You are Penguin."

    archive_id = live.metadata["continued_from"]
    assert archive_id != session_id
    archive = store.load_session(archive_id)
    assert archive is not None
    assert archive.metadata["continued_to"] == session_id
    assert [m.content for m in archive.messages][1] == "message 1"


def test_a_client_reloading_the_session_gets_the_live_history(tmp_path: Path) -> None:
    conversation, _store = _conversation(tmp_path)
    session_id = conversation.session.id
    for index in range(1, 30):
        role = "user" if index % 2 else "assistant"
        conversation.add_message(role, f"message {index}", MessageCategory.DIALOG)
    conversation.save()

    # The next prompt: a fresh manager loads the session by the client's id.
    again = ConversationSystem(
        session_manager=SessionManager(
            base_path=str(tmp_path), max_messages_per_session=20, auto_save_interval=0
        ),
        system_prompt="",
    )
    assert again.load(session_id)
    again.add_message("user", "continue", MessageCategory.DIALOG)

    request = again.get_formatted_messages()
    contents = [str(message["content"]) for message in request]
    assert again.session.id == session_id
    assert "continue" in contents and "message 29" in contents


@pytest.mark.parametrize("lead_in", [0, 1, 2, 3])
def test_rollover_in_a_long_tool_run_keeps_calls_with_their_results(
    tmp_path: Path, lead_in: int
) -> None:
    """SM-23: a rollover between a tool call and its result must not split them.

    A long autonomous run has no user message in the carried window, so the
    window must not open on a tool result whose call was left in the archive.
    """
    conversation, _store = _conversation(tmp_path)
    conversation.add_message("user", "do the work", MessageCategory.DIALOG)
    for index in range(lead_in):  # shift where the limit falls in a call group
        conversation.add_message("assistant", f"note {index}", MessageCategory.DIALOG)
    for index in range(40):
        conversation.add_message("assistant", f"step {index}", MessageCategory.DIALOG)
        conversation.add_action_result(
            "execute", f"output {index}", tool_call_id=f"call_{index}"
        )

    live = conversation.session
    history = [m for m in live.messages if m.category is not MessageCategory.SYSTEM]
    assert history and history[0].role != "tool"
    assert history[-1].content == "output 39"

    declared: set[str] = set()
    recorded = {record["call_id"] for record in live.tool_call_records}
    for message in history:
        for call in (message.metadata or {}).get("tool_calls", []):
            declared.add(call["id"])
        if message.role == "tool":
            call_id = message.metadata["tool_call_id"]
            assert call_id in declared, f"{call_id} has no call before it"
            assert call_id in recorded

    request = conversation.get_formatted_messages()
    tool_ids = [m["tool_call_id"] for m in request if m.get("role") == "tool"]
    assert tool_ids and tool_ids[-1] == "call_39"
