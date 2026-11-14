"""CLI event dedup tells apart events that carry no ``content`` (SM-47)."""

from __future__ import annotations

from penguin.cli.events import EventBus


def _bus() -> EventBus:
    bus = EventBus.__new__(EventBus)
    bus._recent_events = []
    bus._dedup_window = 60.0
    return bus


def test_tool_start_and_end_are_not_duplicates() -> None:
    bus = _bus()

    first = bus._is_duplicate("tool", {"phase": "start", "id": "t1"})
    second = bus._is_duplicate("tool", {"phase": "end", "id": "t1"})

    assert (first, second) == (False, False)


def test_two_different_errors_are_not_duplicates() -> None:
    bus = _bus()

    first = bus._is_duplicate("error", {"message": "disk full"})
    second = bus._is_duplicate("error", {"message": "permission denied"})

    assert (first, second) == (False, False)


def test_identical_events_are_still_duplicates() -> None:
    bus = _bus()

    first = bus._is_duplicate("message", {"content": "hello", "role": "assistant"})
    second = bus._is_duplicate("message", {"content": "hello", "role": "assistant"})

    assert (first, second) == (False, True)
