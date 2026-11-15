"""Action tags are hidden from streamed text without hiding anything else.

Covers SM-44: an action tag that never closed (including a tag named in prose)
hid all the text after it, and reasoning and assistant text shared one parser
state, so a tag opened in one hid the other.
"""

from __future__ import annotations

from typing import Any

import pytest

from penguin.tui_adapter.part_events import PartEventAdapter


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    async def emit(self, event_name: str, payload: Any) -> None:
        self.events.append((event_name, payload))


def _shown(bus: _EventBus, part_type: str) -> str:
    """The text the client received for parts of ``part_type``."""
    text = ""
    for event_name, payload in bus.events:
        if event_name != "opencode_event" or payload.get("type") != (
            "message.part.updated"
        ):
            continue
        properties = payload["properties"]
        if properties["part"].get("type") == part_type and properties.get("delta"):
            text += properties["delta"]
    return text


async def _stream(chunks: list[tuple[str, str]]) -> _EventBus:
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_a")
    message_id, part_id = await adapter.on_stream_start(agent_id="build")
    for text, kind in chunks:
        await adapter.on_stream_chunk(message_id, part_id, text, kind)
    await adapter.on_stream_end(message_id, part_id)
    return bus


@pytest.mark.asyncio
async def test_text_after_a_tag_that_never_closes_is_still_shown() -> None:
    bus = await _stream(
        [
            ("Wrap code in an <execute> tag", "assistant"),
            (" and the rest of this answer stays visible.", "assistant"),
        ]
    )

    assert _shown(bus, "text") == (
        "Wrap code in an <execute> tag and the rest of this answer stays visible."
    )


@pytest.mark.asyncio
async def test_a_tag_opened_in_reasoning_does_not_hide_the_answer() -> None:
    bus = await _stream(
        [
            ("Maybe I should <execute>", "reasoning"),
            ("Here is the answer.", "assistant"),
        ]
    )

    assert _shown(bus, "text") == "Here is the answer."


@pytest.mark.asyncio
async def test_a_closed_action_is_hidden_across_chunks() -> None:
    bus = await _stream(
        [
            ("Running it now. <exe", "assistant"),
            ("cute>print(1)</exec", "assistant"),
            ("ute> Done.", "assistant"),
        ]
    )

    assert _shown(bus, "text") == "Running it now.  Done."
