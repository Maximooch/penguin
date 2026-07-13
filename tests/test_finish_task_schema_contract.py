from __future__ import annotations

from penguin.tools.tool_manager import ToolManager


def test_finish_task_native_schema_requires_validated_status() -> None:
    manager = ToolManager(
        config={},
        log_error_func=lambda *_args, **_kwargs: None,
        fast_startup=True,
    )

    schema = manager.get_available_tool_schemas()["finish_task"]["input_schema"]

    assert schema["required"] == ["status"]
    assert schema["properties"]["status"]["enum"] == [
        "done",
        "partial",
        "blocked",
    ]
