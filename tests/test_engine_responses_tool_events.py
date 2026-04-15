from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.engine import Engine


@pytest.mark.asyncio
async def test_responses_tool_call_emits_live_action_start_and_result_events() -> None:
    engine = Engine.__new__(Engine)
    cast(Any, engine)._default_run_state = SimpleNamespace(current_agent_id="default")
    engine.current_agent_id = "default"
    engine.default_agent_id = "default"

    emitted: list[tuple[str, dict[str, Any]]] = []

    async def emit_ui_event(event_type: str, data: dict[str, Any]) -> None:
        emitted.append((event_type, dict(data)))

    cm = SimpleNamespace(
        core=SimpleNamespace(emit_ui_event=emit_ui_event),
        add_action_result=lambda **kwargs: None,
    )
    api_client = SimpleNamespace(
        model_config=SimpleNamespace(provider="openai", model="gpt-5.4"),
        client_handler=SimpleNamespace(
            get_and_clear_last_tool_call=lambda: {
                "call_id": "call_123",
                "name": "write_file",
                "arguments": '{"path":"x.txt","content":"hello"}',
            }
        ),
    )

    executed: list[tuple[str, dict[str, Any]]] = []
    tool_manager = SimpleNamespace(
        execute_tool=lambda name, args: executed.append((name, dict(args))) or "ok"
    )

    async def _emit_tool_event(_cm: Any, action_result: dict[str, Any]) -> None:
        emitted.append(("tool", dict(action_result)))

    engine._emit_tool_event = _emit_tool_event  # type: ignore[method-assign]

    result = await engine._handle_responses_tool_call(api_client, tool_manager, cm)

    assert result == {"action": "write_file", "result": "ok", "status": "completed"}
    assert executed == [("write_file", {"path": "x.txt", "content": "hello"})]
    assert emitted[0][0] == "action"
    assert emitted[0][1]["id"] == "call_123"
    assert emitted[0][1]["action"] == "write_file"
    assert emitted[1][0] == "action_result"
    assert emitted[1][1]["id"] == "call_123"
    assert emitted[1][1]["status"] == "completed"
