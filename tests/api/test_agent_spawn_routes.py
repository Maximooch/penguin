"""HTTP boundary tests for sub-agent runtime selection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from penguin.web.routes import AgentSpawnRequest, create_agent


@pytest.mark.asyncio
async def test_create_agent_forwards_sub_agent_runtime_selection() -> None:
    core = MagicMock()
    core.publish_sub_agent_session_created = AsyncMock(
        return_value={"id": "session_child"}
    )
    core.get_agent_profile.return_value = {
        "id": "flash-worker",
        "model": {"model": "deepseek/deepseek-v4-flash"},
    }
    request = AgentSpawnRequest(
        id="flash-worker",
        parent="default",
        persona="researcher",
        system_prompt="Investigate carefully.",
        model_config_id="subagent-fast",
        model_overrides={"temperature": 0.1},
        model_output_max_tokens=4096,
        default_tools=["read_file", "grep_search"],
    )

    result = await create_agent(request, core)

    assert result["model"]["model"] == "deepseek/deepseek-v4-flash"
    core.create_sub_agent.assert_called_once_with(
        "flash-worker",
        parent_agent_id="default",
        persona="researcher",
        system_prompt="Investigate carefully.",
        share_session=False,
        share_context_window=False,
        shared_context_window_max_tokens=None,
        model_config_id="subagent-fast",
        model_overrides={"temperature": 0.1},
        model_output_max_tokens=4096,
        default_tools=["read_file", "grep_search"],
    )


@pytest.mark.asyncio
async def test_create_agent_reports_invalid_runtime_selection_as_bad_request() -> None:
    core = SimpleNamespace(
        create_sub_agent=MagicMock(
            side_effect=ValueError("Unknown model_config_id 'missing'")
        )
    )
    request = AgentSpawnRequest(
        id="invalid-worker",
        parent="default",
        model_config_id="missing",
    )

    with pytest.raises(HTTPException) as raised:
        await create_agent(request, core)

    assert raised.value.status_code == 400
    assert raised.value.detail == "Unknown model_config_id 'missing'"
