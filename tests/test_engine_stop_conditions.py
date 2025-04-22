import asyncio
import pytest  # type: ignore

from penguin.core import PenguinCore
from penguin.engine import TokenBudgetStop, WallClockStop


@pytest.mark.asyncio
async def test_token_budget_stop(monkeypatch):
    """Engine.run_task should break early when TokenBudgetStop triggers."""
    core = await PenguinCore.create()
    core.reset_context()

    # Stub the LLM call to avoid network
    async def fake_response(*args, **kwargs):
        return "stub response"

    monkeypatch.setattr(core.api_client, "get_response", fake_response)

    # Force the context_window to report over‑budget immediately
    def always_over_budget():
        return True

    monkeypatch.setattr(
        core.conversation_manager.context_window,
        "is_over_budget",
        always_over_budget,
    )

    # Inject TokenBudgetStop as the sole stop condition
    core.engine.stop_conditions = [TokenBudgetStop()]

    await core.engine.run_task("demo task", max_iterations=10)

    # Should have exited after first iteration
    assert core.engine.current_iteration == 1


@pytest.mark.asyncio
async def test_wall_clock_stop(monkeypatch):
    """Engine.run_task should respect WallClockStop time budget."""
    core = await PenguinCore.create()
    core.reset_context()

    async def fake_response(*args, **kwargs):
        return "stub response"

    monkeypatch.setattr(core.api_client, "get_response", fake_response)

    # WallClockStop with 0 seconds – should trigger immediately
    core.engine.stop_conditions = [WallClockStop(0)]

    await core.engine.run_task("quick task", max_iterations=10)
    assert core.engine.current_iteration == 1


@pytest.mark.asyncio
async def test_engine_stream(monkeypatch):
    """Ensure engine.stream completes and yields no chunks with stubbed response."""
    core = await PenguinCore.create()
    core.reset_context()

    async def fake_response(*args, **kwargs):
        # Simulate provider returning the full response even in streaming mode
        return "streamed response"

    monkeypatch.setattr(core.api_client, "get_response", fake_response)

    chunks = []
    async for chunk in core.engine.stream("hello stream"):
        chunks.append(chunk)

    # Current implementation yields no chunks (only sentinel), just ensure it completed
    assert chunks == [] 