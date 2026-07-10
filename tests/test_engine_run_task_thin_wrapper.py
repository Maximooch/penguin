from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.engine import Engine, EngineSettings, LoopConfig
from penguin.utils.errors import (
    LLMEmptyResponseError,
    NativeToolHistoryPersistenceError,
)


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
    cm = SimpleNamespace(
        conversation=SimpleNamespace(prepare_conversation=lambda *a, **k: None)
    )
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
    cm = SimpleNamespace(
        conversation=SimpleNamespace(prepare_conversation=lambda *a, **k: None)
    )
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


@pytest.mark.asyncio
async def test_shared_loop_completion_on_final_iteration_is_not_exhaustion():
    engine = Engine(
        settings=EngineSettings(),
        conversation_manager=SimpleNamespace(),
        api_client=SimpleNamespace(),
        tool_manager=SimpleNamespace(),
        action_executor=SimpleNamespace(),
    )
    engine.current_iteration = 0
    engine._llm_step = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "assistant_response": "Task result is ready.",
            "action_results": [],
            "usage": {},
        }
    )
    engine._save_conversation = AsyncMock()  # type: ignore[method-assign]
    cm = SimpleNamespace(core=None)
    config = LoopConfig(
        mode="task",
        termination_action="finish_task",
        async_save=True,
        default_completion_status="iterations_exceeded",
    )

    result = await engine._iteration_loop(cm, config, max_iterations=1)

    assert result["iterations"] == 1
    assert result["status"] == "implicit_completion"


@pytest.mark.asyncio
async def test_shared_loop_reports_only_genuine_iteration_exhaustion():
    engine = Engine(
        settings=EngineSettings(),
        conversation_manager=SimpleNamespace(),
        api_client=SimpleNamespace(),
        tool_manager=SimpleNamespace(),
        action_executor=SimpleNamespace(),
    )
    engine.current_iteration = 0
    engine._llm_step = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "assistant_response": "Continuing after tool output.",
            "action_results": [
                {"action": "read_file", "result": "data", "status": "completed"}
            ],
            "usage": {},
        }
    )
    engine._save_conversation = AsyncMock()  # type: ignore[method-assign]
    cm = SimpleNamespace(core=None)
    config = LoopConfig(
        mode="task",
        termination_action="finish_task",
        async_save=True,
        default_completion_status="iterations_exceeded",
    )

    result = await engine._iteration_loop(cm, config, max_iterations=1)

    assert result["iterations"] == 1
    assert result["status"] == "iterations_exceeded"


@pytest.mark.asyncio
async def test_shared_loop_exposes_empty_response_as_recoverable_stall() -> None:
    engine = Engine(
        settings=EngineSettings(),
        conversation_manager=SimpleNamespace(),
        api_client=SimpleNamespace(),
        tool_manager=SimpleNamespace(),
        action_executor=SimpleNamespace(),
    )
    engine.current_iteration = 0
    engine._llm_step = AsyncMock(  # type: ignore[method-assign]
        side_effect=LLMEmptyResponseError("provider returned no usable output")
    )
    cm = SimpleNamespace(core=None)
    config = LoopConfig(
        mode="response",
        termination_action="finish_response",
        async_save=True,
    )

    result = await engine._iteration_loop(cm, config, max_iterations=2)

    assert result["status"] == "llm_empty_response_error"
    assert result["recoverable"] is True
    assert result["error"]["code"] == "llm_empty_response"


@pytest.mark.asyncio
async def test_shared_loop_stops_after_native_tool_history_persistence_failure() -> (
    None
):
    """A missing replay unit cannot trigger a speculative next LLM turn."""

    engine = Engine(
        settings=EngineSettings(),
        conversation_manager=SimpleNamespace(),
        api_client=SimpleNamespace(),
        tool_manager=SimpleNamespace(),
        action_executor=SimpleNamespace(),
    )
    engine.current_iteration = 0
    engine._llm_step = AsyncMock(  # type: ignore[method-assign]
        side_effect=NativeToolHistoryPersistenceError(["call_pwd"])
    )
    cm = SimpleNamespace(core=None)
    config = LoopConfig(
        mode="response",
        termination_action="finish_response",
        async_save=True,
    )

    result = await engine._iteration_loop(cm, config, max_iterations=2)

    engine._llm_step.assert_awaited_once()
    assert result["status"] == "native_tool_history_error"
    assert result["recoverable"] is False
    assert result["error"]["code"] == "NATIVE_TOOL_HISTORY_PERSISTENCE_FAILED"
