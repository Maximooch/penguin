"""Core shim coverage for extracted OpenCode bridge helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core import PenguinCore


@pytest.mark.asyncio
async def test_core_usage_update_shim_uses_extracted_bridge_state() -> None:
    updates: list[tuple[str, dict[str, Any], float]] = []

    class _Adapter:
        async def update_assistant_usage(
            self,
            message_id: str,
            *,
            tokens: dict[str, Any],
            cost: float,
        ) -> None:
            updates.append((message_id, tokens, cost))

    core = PenguinCore.__new__(PenguinCore)
    adapter = _Adapter()
    setattr(core, "_opencode_stream_states", {"session_1": {"message_id": "msg_1"}})
    setattr(core, "_opencode_message_adapters", {"msg_1": adapter})
    setattr(core, "_get_tui_adapter", lambda _session_id: SimpleNamespace())

    await core._apply_opencode_usage_to_latest_message(
        "session_1",
        {
            "input_tokens": 2,
            "output_tokens": 5,
            "reasoning_tokens": 1,
            "cache_read_tokens": 3,
            "total_tokens": 11,
            "cost": "0.21",
        },
    )

    assert updates == [
        (
            "msg_1",
            {
                "input": 2,
                "output": 5,
                "reasoning": 1,
                "cache": {"read": 3, "write": 0},
            },
            0.21,
        )
    ]
