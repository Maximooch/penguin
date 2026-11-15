"""Stopping the CLI's streaming display also forgets the stream it showed.

Covers SM-46: ``safely_stop_progress`` stopped the live display but kept the
stream id, so the event manager ignored every chunk of the next stream in the
same turn as belonging to a foreign stream.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from penguin.cli.event_manager import EventManager
from penguin.cli.streaming_manager import StreamingManager


class _Display:
    def __init__(self) -> None:
        self.is_active = False
        self.shown: list[str] = []
        self.content_buffer = ""

    def start_message(self, role: str = "assistant") -> None:
        del role
        self.is_active = True

    def append_text(self, text: str, is_reasoning: bool = False) -> None:
        del is_reasoning
        self.shown.append(text)

    def stop(self, finalize: bool = True) -> None:
        del finalize
        self.is_active = False

    def set_status(self, _status: Any) -> None:
        return None


def _cli() -> SimpleNamespace:
    display = _Display()
    return SimpleNamespace(
        streaming_display=display,
        streaming_manager=StreamingManager(display),
        _streaming_started=False,
        pending_system_messages=[],
        processed_messages=set(),
        message_turn_map={},
        current_conversation_turn=1,
        last_completed_message="",
        last_completed_message_normalized="",
        run_mode_status="",
        _filter_verbose_code_blocks=lambda text: text,
        _normalize_message_content=lambda text: text.strip(),
    )


def _chunk(manager: EventManager, stream_id: str, text: str, **extra: Any) -> None:
    manager.handle_stream_chunk_event(
        "stream_chunk", {"stream_id": stream_id, "chunk": text, **extra}
    )


def test_stopping_the_display_forgets_the_stream() -> None:
    cli = _cli()
    manager = EventManager(cli)
    _chunk(manager, "stream_1", "first ")

    cli.streaming_manager.safely_stop_progress()

    assert cli.streaming_manager._active_stream_id is None
    assert cli.streaming_manager.is_streaming is False


def test_a_new_stream_after_a_stopped_display_is_shown() -> None:
    cli = _cli()
    manager = EventManager(cli)
    _chunk(manager, "stream_1", "first ")
    cli.streaming_manager.safely_stop_progress()

    _chunk(manager, "stream_2", "second")

    assert cli.streaming_display.shown == ["first ", "second"]
    assert cli.streaming_manager._active_stream_id == "stream_2"
