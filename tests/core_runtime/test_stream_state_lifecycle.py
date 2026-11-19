"""A session's stream state names a message only once that message exists.

Covers SM-39: a new stream was marked active before its message was created,
so across that await the state paired ``active`` with the previous message;
and every streamed message left an entry in the message-adapter map.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime.stream_events import (
    handle_tui_stream_chunk,
    stream_state_for,
)

SESSION = "session_a"


class _Adapter:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.created = 0
        self.state_at_start: list[dict[str, Any]] = []
        self.ended: list[str] = []

    async def on_stream_start(self, **_kwargs: Any) -> tuple[str, str]:
        self.state_at_start.append(dict(stream_state_for(self.owner, SESSION)))
        self.created += 1
        return f"msg_{self.created}", f"part_{self.created}"

    async def on_stream_chunk(self, *_args: Any) -> None:
        return None

    async def on_stream_end(self, message_id: str, _part_id: str) -> None:
        self.ended.append(message_id)


def _owner() -> SimpleNamespace:
    owner = SimpleNamespace(
        _opencode_stream_states={},
        _opencode_message_adapters={},
        _resolve_opencode_model_state=lambda **_kwargs: {},
    )
    owner.adapter = _Adapter(owner)
    owner._get_tui_adapter = lambda _session_id: owner.adapter
    return owner


async def _chunk(owner: Any, stream_id: str, text: str, *, final: bool = False) -> None:
    await handle_tui_stream_chunk(
        owner,
        "stream_chunk",
        {
            "chunk": text,
            "stream_id": stream_id,
            "session_id": SESSION,
            "is_final": final,
        },
        logger=logging.getLogger(__name__),
    )


@pytest.mark.asyncio
async def test_a_starting_stream_never_names_the_previous_message() -> None:
    owner = _owner()
    await _chunk(owner, "stream_1", "first")
    await _chunk(owner, "stream_1", "", final=True)

    await _chunk(owner, "stream_2", "second")

    during_second_start = owner.adapter.state_at_start[1]
    assert not (
        during_second_start["active"] and during_second_start["message_id"] == "msg_1"
    )
    state = stream_state_for(owner, SESSION)
    assert (state["active"], state["message_id"]) == (True, "msg_2")


@pytest.mark.asyncio
async def test_an_ended_stream_leaves_no_adapter_entry() -> None:
    owner = _owner()
    await _chunk(owner, "stream_1", "first")
    await _chunk(owner, "stream_2", "switched")  # ends stream_1 implicitly
    await _chunk(owner, "stream_2", "", final=True)

    assert owner.adapter.ended == ["msg_1", "msg_2"]
    assert owner._opencode_message_adapters == {}
