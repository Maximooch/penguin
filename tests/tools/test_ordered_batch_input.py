"""Ordered batches preserve serialized provider arguments at dispatch boundaries."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from penguin.tools.tool_manager import ToolManager


@pytest.mark.parametrize("serialized", [False, True])
def test_batch_dispatch_preserves_payload(tmp_path: Path, serialized: bool) -> None:
    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    manager._permission_enabled = False
    payload = {"tool_uses": [{"tool": "read_file", "arguments": {"path": "a.txt"}}]}
    execute_batch = Mock(return_value="batch-result")
    manager._execute_ordered_tool_batch = execute_batch

    result = manager.execute_tool(
        "ordered_tool_batch",
        json.dumps(payload) if serialized else payload,
        {"directory": str(tmp_path)},
    )

    assert result == "batch-result"
    received = execute_batch.call_args.args[0]
    assert len(received["tool_uses"]) == 1
    assert received["tool_uses"][0]["arguments"]["path"] == str(tmp_path / "a.txt")


@pytest.mark.parametrize("payload", ['{"tool_uses":', '"not an object"', "[]"])
def test_batch_dispatch_rejects_invalid_serialized_input(
    tmp_path: Path, payload: str
) -> None:
    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    execute_batch = Mock()
    manager._execute_ordered_tool_batch = execute_batch

    result = json.loads(
        manager.execute_tool(
            "ordered_tool_batch", payload, {"directory": str(tmp_path)}
        )
    )

    assert result["status"] == "error"
    assert "JSON object" in result["error"]
    execute_batch.assert_not_called()


@pytest.mark.asyncio
async def test_async_batch_dispatch_preserves_payload(tmp_path: Path) -> None:
    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    manager._permission_enabled = False
    payload = {"tool_uses": [{"tool": "read_file", "arguments": {"path": "a.txt"}}]}
    execute_batch = Mock(return_value="batch-result")
    manager._execute_ordered_tool_batch = execute_batch

    result = await manager.execute_tool_async(
        "ordered_tool_batch", json.dumps(payload), {"directory": str(tmp_path)}
    )

    assert result == "batch-result"
    received = execute_batch.call_args.args[0]
    assert received["tool_uses"][0]["arguments"]["path"] == str(tmp_path / "a.txt")


@pytest.mark.asyncio
async def test_async_batch_rejects_invalid_input_before_permissions(
    tmp_path: Path,
) -> None:
    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    manager._permission_response = Mock(
        side_effect=AssertionError("must not authorize malformed input")
    )
    result = await manager.execute_tool_async(
        "ordered_tool_batch", "[]", {"directory": str(tmp_path)}
    )
    assert json.loads(result)["status"] == "error"
    manager._permission_response.assert_not_called()


def test_serialized_batch_executes_children_in_order(tmp_path: Path) -> None:
    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    manager._permission_enabled = False
    payload = {
        "tool_uses": [
            {"tool": "create_file", "arguments": {"path": "a.txt", "content": "first"}},
            {"tool": "write_file", "arguments": {"path": "a.txt", "content": "second"}},
        ]
    }
    result = json.loads(
        manager.execute_tool(
            "ordered_tool_batch", json.dumps(payload), {"directory": str(tmp_path)}
        )
    )
    assert result["status"] == "completed"
    assert (tmp_path / "a.txt").read_text() == "second"


def test_invalid_later_child_prevents_all_mutations(tmp_path: Path) -> None:
    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    manager._permission_enabled = False
    payload = {
        "tool_uses": [
            {"tool": "create_file", "arguments": {"path": "a.txt", "content": "first"}},
            {"tool": "no_such_tool", "arguments": {}},
        ]
    }
    result = json.loads(
        manager.execute_tool(
            "ordered_tool_batch", json.dumps(payload), {"directory": str(tmp_path)}
        )
    )
    assert result["status"] == "error"
    assert not (tmp_path / "a.txt").exists()


def test_serialized_batch_preserves_child_permission_checks(tmp_path: Path) -> None:
    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    payload = {
        "tool_uses": [
            {"tool": "create_file", "arguments": {"path": "a.txt", "content": "first"}},
        ]
    }
    checked = []

    def check(name, args, context):
        checked.append(name)
        if name == "create_file":
            return json.dumps({"status": "error", "error": "permission_denied"})
        return None

    manager._permission_response = check
    result = json.loads(
        manager.execute_tool(
            "ordered_tool_batch", json.dumps(payload), {"directory": str(tmp_path)}
        )
    )
    assert result["status"] == "error"
    assert checked == ["ordered_tool_batch", "create_file"]
    assert not (tmp_path / "a.txt").exists()
