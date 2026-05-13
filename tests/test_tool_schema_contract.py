from __future__ import annotations

from penguin.tools.schema_contract import (
    normalize_model_visible_tool_schema,
    render_tool_usage_guidance,
    runtime_metadata_from_tool_schema,
    validate_model_visible_tool_schema,
)
from penguin.tools.tool_manager import ToolManager


def test_schema_contract_adds_minimum_model_visible_usage_guidance() -> None:
    schema = normalize_model_visible_tool_schema(
        {
            "name": "read_file",
            "description": "Read a file.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        }
    )

    assert schema["usage"] == render_tool_usage_guidance(schema)
    assert "Call `read_file`" in schema["usage"]
    assert "Required fields: path." in schema["usage"]
    assert validate_model_visible_tool_schema(schema) == []


def test_runtime_metadata_defaults_are_conservative_before_safe_parallelism() -> None:
    metadata = runtime_metadata_from_tool_schema({}).to_dict()

    assert metadata["mutates_state"] is True
    assert metadata["requires_approval"] is True
    assert metadata["parallel_safe"] is False
    assert metadata["long_running"] is False
    assert metadata["streams_output"] is False
    assert metadata["retry_safe"] is False


def test_tool_manager_exposes_minimum_schema_contract_for_registered_tools() -> None:
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)
    tools = manager.get_model_visible_tools()

    assert tools
    assert all(validate_model_visible_tool_schema(tool) == [] for tool in tools)
    assert all(isinstance(tool.get("usage"), str) and tool["usage"] for tool in tools)


def test_tool_manager_runtime_metadata_uses_schema_without_enabling_parallelism() -> None:
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)

    unknown = manager.get_tool_runtime_metadata("missing_tool")
    read_image = manager.get_tool_runtime_metadata("read_image")

    assert unknown["parallel_safe"] is False
    assert unknown["requires_approval"] is True
    assert read_image["mutates_state"] is False
    assert "parallel_safe" in read_image
