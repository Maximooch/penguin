from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.engine import Engine


def _make_engine() -> Engine:
    engine = Engine.__new__(Engine)
    cast(Any, engine)._default_run_state = SimpleNamespace(current_agent_id="default")
    engine.current_agent_id = "default"
    engine.default_agent_id = "default"
    engine._trace_request_fields = lambda: ("req-1", "session-1")  # type: ignore[method-assign]
    engine._extract_usage_from_api_client = lambda _api_client: {
        "reasoning_tokens": 134
    }  # type: ignore[method-assign]
    return engine


def test_build_reasoning_fallback_note_when_tokens_exist_without_visible_summary() -> (
    None
):
    engine = _make_engine()
    api_client = SimpleNamespace(
        model_config=SimpleNamespace(get_reasoning_config=lambda: {"effort": "xhigh"}),
        client_handler=SimpleNamespace(get_last_reasoning=lambda: ""),
    )

    note = engine._build_reasoning_fallback_note(api_client)

    assert note is None


@pytest.mark.asyncio
async def test_inject_reasoning_fallback_note_routes_into_streaming_reasoning_channel() -> (
    None
):
    engine = _make_engine()
    seen: list[dict[str, object]] = []

    async def _handle_stream_chunk(chunk: str, **kwargs: object) -> None:
        seen.append({"chunk": chunk, **kwargs})

    cm = cast(
        Any,
        SimpleNamespace(
            core=SimpleNamespace(_handle_stream_chunk=_handle_stream_chunk)
        ),
    )
    api_client = SimpleNamespace(
        model_config=SimpleNamespace(get_reasoning_config=lambda: {"effort": "xhigh"}),
        client_handler=SimpleNamespace(get_last_reasoning=lambda: ""),
    )

    await engine._inject_reasoning_fallback_note(
        cm,
        api_client,
        agent_id="default",
        session_id="session-1",
    )

    assert seen == []
