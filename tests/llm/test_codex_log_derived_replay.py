"""Synthetic replay regressions motivated by dropped-history workspace logs."""

from copy import deepcopy

import pytest

from penguin.llm.adapters.openai import OpenAIAdapter


def tool_call(call_id):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"path":"empty.txt"}'},
    }


@pytest.mark.parametrize("output", ["", "nonempty control"])
def test_completed_tool_result_survives_replay_even_when_empty(output):
    adapter = object.__new__(OpenAIAdapter)
    messages = [
        {"role": "assistant", "content": "", "tool_calls": [tool_call("done")]},
        {"role": "tool", "tool_call_id": "done", "content": output},
    ]
    original = deepcopy(messages)
    items = adapter._build_codex_input_items(messages)
    assert messages == original
    assert [item["type"] for item in items] == ["function_call", "function_call_output"]
    assert items[1]["output"] == output


def test_incomplete_legacy_history_keeps_complete_pairs_and_source():
    """Match the observed 72-call/30-output shape without copying user data."""
    adapter = object.__new__(OpenAIAdapter)
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [tool_call(f"call-{i}") for i in range(72)],
        }
    ]
    messages.extend(
        {"role": "tool", "tool_call_id": f"call-{i}", "content": f"result-{i}"}
        for i in range(30)
    )
    original = deepcopy(messages)
    items = adapter._build_codex_input_items(messages)
    calls = {x["call_id"] for x in items if x["type"] == "function_call"}
    outputs = {x["call_id"] for x in items if x["type"] == "function_call_output"}
    assert calls == outputs == {f"call-{i}" for i in range(30)}
    assert messages == original


def test_missing_tool_content_is_not_invented_as_a_completed_result():
    adapter = object.__new__(OpenAIAdapter)
    assert (
        adapter._build_codex_input_items(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [tool_call("missing")],
                },
                {"role": "tool", "tool_call_id": "missing"},
            ]
        )
        == []
    )
