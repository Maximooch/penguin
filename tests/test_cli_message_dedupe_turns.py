"""CLI message dedupe does not hide a later turn's reply (SM-70)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from penguin.cli.event_manager import EventManager

PREFIX = "I'll start by reading the configuration file and then "


def _manager() -> tuple[EventManager, list[tuple[str, str]]]:
    shown: list[tuple[str, str]] = []
    cli = SimpleNamespace(
        processed_messages=set(),
        message_turn_map={},
        current_conversation_turn=0,
        last_completed_message="",
        last_completed_message_normalized="",
        pending_system_messages=[],
        FILE_READ_ACTIONS=set(),
        streaming_manager=MagicMock(is_streaming=False, _active_stream_id=None),
        display_manager=SimpleNamespace(
            display_message=lambda content, role: shown.append((role, content))
        ),
        _normalize_message_content=lambda content: content.strip(),
    )
    return EventManager(cli), shown


def _send(manager: EventManager, role: str, content: str) -> None:
    manager.handle_message_event("message", {"role": role, "content": content})


def test_reply_in_a_later_turn_with_the_same_opening_is_shown() -> None:
    manager, shown = _manager()

    _send(manager, "user", "check the config")
    _send(manager, "assistant", PREFIX + "report back.")
    _send(manager, "user", "now check the tests")
    _send(manager, "assistant", PREFIX + "run the tests.")

    assert [content for role, content in shown if role == "assistant"] == [
        PREFIX + "report back.",
        PREFIX + "run the tests.",
    ]


def test_same_message_delivered_twice_in_one_turn_is_shown_once() -> None:
    manager, shown = _manager()

    _send(manager, "user", "check the config")
    _send(manager, "tool", "tool output that is long enough to matter here")
    _send(manager, "tool", "tool output that is long enough to matter here")

    assert [role for role, _ in shown].count("tool") == 1
