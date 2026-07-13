"""Validation contracts for explicit delegate-exploration iteration limits."""

from __future__ import annotations

import json

import pytest

from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionExecutor


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1.5, float("inf"), float("nan")])
async def test_delegate_explore_rejects_non_integral_or_non_finite_limits(
    limit: float,
) -> None:
    """Both delegate entry points reject malformed explicit limits before work."""

    payload = json.dumps({"task": "Inspect the repository", "max_iterations": limit})
    parser_executor = ActionExecutor.__new__(ActionExecutor)
    tool_manager = ToolManager.__new__(ToolManager)

    assert (
        await parser_executor._delegate_explore_task(payload)
        == "max_iterations must be a positive integer when provided"
    )
    assert await tool_manager._execute_delegate_explore_task(
        {"task": "Inspect the repository", "max_iterations": limit}
    ) == json.dumps(
        {"error": "max_iterations must be a positive integer when provided"}
    )
