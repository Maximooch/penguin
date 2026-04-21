from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.engine import Engine, EngineSettings


@pytest.mark.asyncio
async def test_run_task_delegates_to_iteration_loop_and_preserves_task_metadata():
    engine = Engine(
        settings=EngineSettings(),
        conversation_manager=SimpleNamespace(),
        api_client=SimpleNamespace(),
        tool_manager=SimpleNamespace(),
        action_executor=SimpleNamespace(),
    )
    engine.default_agent_id = "default"
    engine._resolve_agent = AsyncMock(return_value=("default", None))
    cm = SimpleNamespace(conversation=SimpleNamespace(prepare_conversation=lambda *a, **k: None))
    engine._resolve_components = MagicMock(return_value=(cm, None, None, None))
    engine._iteration_loop = AsyncMock(
        return_value={
            "assistant_response": "done",
            "iterations": 2,
            "status": "pending_review",
            "action_results": [{"action": "finish_task", "status": "completed"}],
            "usage": {"total_tokens": 12},
            "execution_time": 0.5,
        }
    )

    result = await engine.run_task(
        task_prompt="Do the thing",
        task_context={"project_id": "p1"},
        task_id="task-123",
        task_name="Important Task",
        enable_events=True,
    )

    engine._iteration_loop.assert_awaited_once()
    _, args, kwargs = engine._iteration_loop.mock_calls[0]
    config = args[1]
    max_iters = args[2]

    assert config.mode == "task"
    assert config.termination_action == "finish_task"
    assert config.enable_events is True
    assert config.message_callback is None
    assert config.default_completion_status == "iterations_exceeded"
    assert config.task_metadata["id"] == "task-123"
    assert config.task_metadata["name"] == "Important Task"
    assert config.task_metadata["context"] == {"project_id": "p1"}
    assert config.task_metadata["prompt"] == "Do the thing"
    assert max_iters == engine.settings.max_iterations_default

    assert result["status"] == "pending_review"
    assert result["task"]["id"] == "task-123"
    assert result["task"]["name"] == "Important Task"


@pytest.mark.asyncio
async def test_run_task_invokes_on_completion_with_result():
    engine = Engine(
        settings=EngineSettings(),
        conversation_manager=SimpleNamespace(),
        api_client=SimpleNamespace(),
        tool_manager=SimpleNamespace(),
        action_executor=SimpleNamespace(),
    )
    engine.default_agent_id = "default"
    engine._resolve_agent = AsyncMock(return_value=("default", None))
    cm = SimpleNamespace(conversation=SimpleNamespace(prepare_conversation=lambda *a, **k: None))
    engine._resolve_components = MagicMock(return_value=(cm, None, None, None))
    engine._iteration_loop = AsyncMock(
        return_value={
            "assistant_response": "done",
            "iterations": 1,
            "status": "pending_review",
            "action_results": [],
            "usage": {},
            "execution_time": 0.1,
        }
    )
    on_completion = AsyncMock()

    result = await engine.run_task(
        task_prompt="Do the thing",
        task_name="Important Task",
        on_completion=on_completion,
    )

    on_completion.assert_awaited_once()
    callback_result = on_completion.await_args.args[0]
    assert callback_result["status"] == "pending_review"
    assert callback_result["task"]["name"] == "Important Task"
    assert result["status"] == "pending_review"
