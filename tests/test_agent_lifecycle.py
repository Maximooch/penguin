import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from penguin.agent import PenguinAgent, PenguinAgentAsync

@pytest.fixture
def mock_core():
    """Fixture to mock PenguinCore and its components, especially the engine."""
    return AsyncMock()

@pytest.fixture(autouse=True)
def patch_core_creation(mock_core):
    """Auto-used fixture to patch PenguinCore.create for all tests."""
    with patch('penguin.agent.PenguinCore.create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_core
        mock_core.engine = AsyncMock()
        yield mock_create

@pytest.mark.asyncio
async def test_penguin_agent_async_creation():
    """Test that PenguinAgentAsync can be created."""
    agent = await PenguinAgentAsync.create()
    assert isinstance(agent, PenguinAgentAsync)
    assert agent._core is not None

@pytest.mark.asyncio
async def test_async_agent_chat_uses_engine():
    """Verify that PenguinAgentAsync.chat() calls the engine correctly."""
    agent = await PenguinAgentAsync.create()
    agent._core.engine.run_single_turn.return_value = {
        "assistant_response": "Hello from async engine"
    }
    
    response = await agent.chat("hello")

    agent._core.engine.run_single_turn.assert_called_once_with(
        prompt="hello", streaming=False
    )
    assert response == "Hello from async engine"

@pytest.mark.asyncio
async def test_async_agent_stream_uses_engine():
    """Verify that PenguinAgentAsync.stream() uses the engine's stream."""
    agent = await PenguinAgentAsync.create()
    
    async def mock_stream_gen(*args, **kwargs):
        for chunk in ["one", "two", "three"]:
            yield chunk
            
    # Mock the stream method to return our async generator directly
    agent._core.engine.stream = mock_stream_gen
    
    chunks = [chunk async for chunk in agent.stream("test stream")]
    
    # Since we replaced the method entirely, we can't use assert_called_once_with
    # but we can verify the chunks are correct
    assert chunks == ["one", "two", "three"]

@pytest.mark.asyncio
async def test_async_agent_run_task_uses_engine():
    """Verify PenguinAgentAsync.run_task calls the engine."""
    agent = await PenguinAgentAsync.create()
    agent._core.engine.run_task.return_value = {"status": "completed", "output": "task done"}
    
    result = await agent.run_task("do a task")

    agent._core.engine.run_task.assert_called_once_with("do a task", max_iterations=5)
    assert result["status"] == "completed"