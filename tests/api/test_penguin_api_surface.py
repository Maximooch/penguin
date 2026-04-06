from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from penguin.web.app import PenguinAPI


@pytest.mark.asyncio
async def test_penguin_api_run_task_uses_runmode_and_preserves_waiting_input():
    core = SimpleNamespace(
        engine=SimpleNamespace(),
        project_manager=SimpleNamespace(),
    )
    api = PenguinAPI(core=core)

    run_mode_instance = SimpleNamespace(
        start=AsyncMock(
            return_value={
                "status": "waiting_input",
                "message": "Need schema decision",
                "completion_type": "clarification_needed",
                "task_id": "task-1",
            }
        )
    )

    from unittest.mock import patch

    with patch("penguin.web.app.RunMode", return_value=run_mode_instance):
        result = await api.run_task(
            "Implement auth flow",
            project_id="project-1",
        )

    run_mode_instance.start.assert_awaited_once_with(
        name="Implement auth flow",
        description=None,
        context={"project_id": "project-1"},
    )
    assert result["status"] == "waiting_input"
    assert result["completion_type"] == "clarification_needed"


@pytest.mark.asyncio
async def test_penguin_api_resume_with_clarification_delegates_to_runmode():
    core = SimpleNamespace(
        engine=SimpleNamespace(),
        project_manager=SimpleNamespace(),
    )
    api = PenguinAPI(core=core)

    run_mode_instance = SimpleNamespace(
        resume_with_clarification=AsyncMock(
            return_value={
                "status": "completed",
                "message": "done",
                "completion_type": "task",
            }
        )
    )

    from unittest.mock import patch

    with patch("penguin.web.app.RunMode", return_value=run_mode_instance):
        result = await api.resume_with_clarification(
            task_id="task-1",
            answer="Use rotating refresh tokens",
            answered_by="human",
        )

    run_mode_instance.resume_with_clarification.assert_awaited_once_with(
        task_id="task-1",
        answer="Use rotating refresh tokens",
        answered_by="human",
    )
    assert result["status"] == "completed"
