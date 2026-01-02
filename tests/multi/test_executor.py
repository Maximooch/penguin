"""Tests for AgentExecutor background agent execution.

Tests the concurrent agent execution system including:
- Agent spawning and lifecycle
- Concurrency control via semaphore
- Agent state management
- Wait/cancel operations
- Parallel execution verification
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any, Dict

from penguin.multi.executor import (
    AgentExecutor,
    AgentState,
    AgentTask,
    get_executor,
    set_executor,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_core():
    """Create a mock PenguinCore for testing."""
    core = MagicMock()

    async def mock_process(input_data: Dict[str, Any], agent_id: str = None):
        # Simulate some processing time
        await asyncio.sleep(0.01)
        return {"assistant_response": f"Response from {agent_id}", "agent_id": agent_id}

    core.process = AsyncMock(side_effect=mock_process)
    return core


@pytest.fixture
def executor(mock_core):
    """Create an AgentExecutor instance for testing."""
    return AgentExecutor(mock_core, max_concurrent=3)


@pytest.fixture(autouse=True)
def reset_global_executor():
    """Reset global executor before/after each test."""
    import penguin.multi.executor as executor_module
    original = executor_module._executor_instance
    executor_module._executor_instance = None
    yield
    executor_module._executor_instance = original


# =============================================================================
# BASIC INITIALIZATION TESTS
# =============================================================================

class TestExecutorInitialization:
    """Test AgentExecutor initialization."""

    def test_default_max_concurrent(self, mock_core):
        """Test default max_concurrent from environment."""
        with patch.dict('os.environ', {'PENGUIN_MAX_CONCURRENT_TASKS': '5'}):
            executor = AgentExecutor(mock_core)
            assert executor.max_concurrent == 5

    def test_custom_max_concurrent(self, mock_core):
        """Test custom max_concurrent parameter."""
        executor = AgentExecutor(mock_core, max_concurrent=10)
        assert executor.max_concurrent == 10

    def test_initial_counts_are_zero(self, executor):
        """Test that running and pending counts start at zero."""
        assert executor.running_count == 0
        assert executor.pending_count == 0


# =============================================================================
# AGENT SPAWNING TESTS
# =============================================================================

class TestAgentSpawning:
    """Test agent spawning functionality."""

    @pytest.mark.asyncio
    async def test_spawn_single_agent(self, executor):
        """Test spawning a single agent."""
        agent_id = await executor.spawn_agent("test-agent", "Hello world")

        assert agent_id == "test-agent"
        assert "test-agent" in executor._tasks

        # Wait for completion
        result = await executor.wait_for("test-agent", timeout=5.0)
        assert result is not None

    @pytest.mark.asyncio
    async def test_spawn_agent_with_metadata(self, executor):
        """Test spawning agent with metadata."""
        await executor.spawn_agent(
            "meta-agent",
            "Test prompt",
            metadata={"role": "researcher", "priority": 1}
        )

        status = executor.get_status("meta-agent")
        assert status["metadata"]["role"] == "researcher"
        assert status["metadata"]["priority"] == 1

    @pytest.mark.asyncio
    async def test_spawn_duplicate_agent_fails(self, executor):
        """Test that spawning duplicate agent ID raises error."""
        await executor.spawn_agent("unique-agent", "First")

        with pytest.raises(ValueError, match="already exists"):
            await executor.spawn_agent("unique-agent", "Second")

    @pytest.mark.asyncio
    async def test_spawn_multiple_agents(self, executor):
        """Test spawning multiple agents at once."""
        agents = [
            ("agent-1", "Prompt 1"),
            ("agent-2", "Prompt 2"),
            ("agent-3", "Prompt 3"),
        ]

        agent_ids = await executor.spawn_agents(agents)

        assert len(agent_ids) == 3
        assert "agent-1" in agent_ids
        assert "agent-2" in agent_ids
        assert "agent-3" in agent_ids


# =============================================================================
# AGENT STATE TESTS
# =============================================================================

class TestAgentState:
    """Test agent state transitions."""

    @pytest.mark.asyncio
    async def test_state_transitions(self, executor):
        """Test state transitions: PENDING -> RUNNING -> COMPLETED."""
        # Spawn agent
        await executor.spawn_agent("state-agent", "Test")

        # Give task time to start
        await asyncio.sleep(0.001)

        # Wait for completion
        await executor.wait_for("state-agent", timeout=5.0)

        status = executor.get_status("state-agent")
        assert status["state"] == AgentState.COMPLETED.value

    @pytest.mark.asyncio
    async def test_failed_state_on_error(self, mock_core):
        """Test FAILED state when agent encounters error."""
        async def failing_process(*args, **kwargs):
            raise Exception("Simulated failure")

        mock_core.process = AsyncMock(side_effect=failing_process)
        executor = AgentExecutor(mock_core, max_concurrent=3)

        await executor.spawn_agent("failing-agent", "Will fail")

        # Wait for task to fail
        await asyncio.sleep(0.1)

        status = executor.get_status("failing-agent")
        assert status["state"] == AgentState.FAILED.value
        assert "Simulated failure" in status["error"]

    @pytest.mark.asyncio
    async def test_cancelled_state(self, executor):
        """Test CANCELLED state after cancel() call."""
        # Create a slow-running agent
        async def slow_process(*args, **kwargs):
            await asyncio.sleep(10)  # Very long
            return "Done"

        executor._core.process = AsyncMock(side_effect=slow_process)

        await executor.spawn_agent("slow-agent", "Slow task")
        await asyncio.sleep(0.01)  # Let it start

        success = await executor.cancel("slow-agent")
        assert success is True

        status = executor.get_status("slow-agent")
        assert status["state"] == AgentState.CANCELLED.value


# =============================================================================
# WAIT OPERATIONS TESTS
# =============================================================================

class TestWaitOperations:
    """Test wait operations for agents."""

    @pytest.mark.asyncio
    async def test_wait_for_single_agent(self, executor):
        """Test waiting for a single agent."""
        await executor.spawn_agent("wait-agent", "Quick task")

        result = await executor.wait_for("wait-agent", timeout=5.0)

        assert result is not None
        assert "assistant_response" in result

    @pytest.mark.asyncio
    async def test_wait_for_nonexistent_agent(self, executor):
        """Test waiting for nonexistent agent returns None."""
        result = await executor.wait_for("nonexistent", timeout=1.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_all(self, executor):
        """Test waiting for all agents."""
        await executor.spawn_agents([
            ("all-1", "Task 1"),
            ("all-2", "Task 2"),
            ("all-3", "Task 3"),
        ])

        results = await executor.wait_for_all(timeout=5.0)

        assert len(results) == 3
        assert "all-1" in results
        assert "all-2" in results
        assert "all-3" in results

    @pytest.mark.asyncio
    async def test_wait_for_specific_agents(self, executor):
        """Test waiting for specific subset of agents."""
        await executor.spawn_agents([
            ("specific-1", "Task 1"),
            ("specific-2", "Task 2"),
            ("specific-3", "Task 3"),
        ])

        results = await executor.wait_for_all(
            agent_ids=["specific-1", "specific-3"],
            timeout=5.0
        )

        assert len(results) == 2
        assert "specific-1" in results
        assert "specific-3" in results
        assert "specific-2" not in results

    @pytest.mark.asyncio
    async def test_wait_timeout(self, mock_core):
        """Test that wait times out correctly."""
        async def very_slow(*args, **kwargs):
            await asyncio.sleep(100)
            return "Done"

        mock_core.process = AsyncMock(side_effect=very_slow)
        executor = AgentExecutor(mock_core, max_concurrent=3)

        await executor.spawn_agent("timeout-agent", "Slow")

        with pytest.raises(asyncio.TimeoutError):
            await executor.wait_for("timeout-agent", timeout=0.1)


# =============================================================================
# CONCURRENCY CONTROL TESTS
# =============================================================================

class TestConcurrencyControl:
    """Test concurrency control via semaphore."""

    @pytest.mark.asyncio
    async def test_respects_max_concurrent(self, mock_core):
        """Test that max_concurrent is respected."""
        running_count = 0
        max_running = 0
        lock = asyncio.Lock()

        async def tracking_process(*args, **kwargs):
            nonlocal running_count, max_running
            async with lock:
                running_count += 1
                max_running = max(max_running, running_count)

            await asyncio.sleep(0.05)

            async with lock:
                running_count -= 1

            return "Done"

        mock_core.process = AsyncMock(side_effect=tracking_process)
        executor = AgentExecutor(mock_core, max_concurrent=2)

        # Spawn 5 agents
        for i in range(5):
            await executor.spawn_agent(f"concurrent-{i}", f"Task {i}")

        # Wait for all
        await executor.wait_for_all(timeout=5.0)

        # Max running should never exceed 2
        assert max_running <= 2

    @pytest.mark.asyncio
    async def test_semaphore_value_tracking(self, executor):
        """Test that semaphore value is tracked in stats."""
        stats = executor.get_stats()
        assert stats["semaphore_value"] == 3  # max_concurrent

        # Spawn agents
        await executor.spawn_agents([
            ("sem-1", "Task 1"),
            ("sem-2", "Task 2"),
        ])

        await executor.wait_for_all(timeout=5.0)

        # Semaphore should be back to max
        stats = executor.get_stats()
        assert stats["semaphore_value"] == 3


# =============================================================================
# CANCEL OPERATIONS TESTS
# =============================================================================

class TestCancelOperations:
    """Test cancel operations."""

    @pytest.mark.asyncio
    async def test_cancel_running_agent(self, mock_core):
        """Test cancelling a running agent."""
        async def slow_process(*args, **kwargs):
            await asyncio.sleep(10)
            return "Done"

        mock_core.process = AsyncMock(side_effect=slow_process)
        executor = AgentExecutor(mock_core, max_concurrent=3)

        await executor.spawn_agent("cancel-test", "Slow task")
        await asyncio.sleep(0.01)  # Let it start

        success = await executor.cancel("cancel-test")

        assert success is True
        status = executor.get_status("cancel-test")
        assert status["state"] == AgentState.CANCELLED.value

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_agent(self, executor):
        """Test cancelling nonexistent agent returns False."""
        success = await executor.cancel("nonexistent")
        assert success is False

    @pytest.mark.asyncio
    async def test_cancel_completed_agent(self, executor):
        """Test cancelling already completed agent returns False."""
        await executor.spawn_agent("completed-agent", "Quick task")
        await executor.wait_for("completed-agent", timeout=5.0)

        success = await executor.cancel("completed-agent")
        assert success is False

    @pytest.mark.asyncio
    async def test_cancel_all(self, mock_core):
        """Test cancelling all running agents."""
        async def slow_process(*args, **kwargs):
            await asyncio.sleep(10)
            return "Done"

        mock_core.process = AsyncMock(side_effect=slow_process)
        executor = AgentExecutor(mock_core, max_concurrent=5)

        # Spawn several agents
        for i in range(4):
            await executor.spawn_agent(f"cancel-all-{i}", "Slow task")

        await asyncio.sleep(0.05)  # Let them start

        cancelled = await executor.cancel_all()
        assert cancelled >= 1  # At least some should be cancelled


# =============================================================================
# PAUSE/RESUME TESTS
# =============================================================================

class TestPauseResume:
    """Test pause and resume operations."""

    @pytest.mark.asyncio
    async def test_pause_running_agent(self, mock_core):
        """Test pausing a running agent."""
        async def slow_process(*args, **kwargs):
            await asyncio.sleep(10)
            return "Done"

        mock_core.process = AsyncMock(side_effect=slow_process)
        executor = AgentExecutor(mock_core, max_concurrent=3)

        await executor.spawn_agent("pause-test", "Slow task")
        await asyncio.sleep(0.05)  # Let it start

        # Verify it's running
        status = executor.get_status("pause-test")
        assert status["state"] == AgentState.RUNNING.value

        # Pause it
        success = executor.pause("pause-test")
        assert success is True

        status = executor.get_status("pause-test")
        assert status["state"] == AgentState.PAUSED.value

    @pytest.mark.asyncio
    async def test_resume_paused_agent(self, mock_core):
        """Test resuming a paused agent."""
        async def slow_process(*args, **kwargs):
            await asyncio.sleep(10)
            return "Done"

        mock_core.process = AsyncMock(side_effect=slow_process)
        executor = AgentExecutor(mock_core, max_concurrent=3)

        await executor.spawn_agent("resume-test", "Slow task")
        await asyncio.sleep(0.05)

        executor.pause("resume-test")
        success = executor.resume("resume-test")

        assert success is True
        status = executor.get_status("resume-test")
        assert status["state"] == AgentState.RUNNING.value

    def test_pause_nonexistent_agent(self, executor):
        """Test pausing nonexistent agent returns False."""
        success = executor.pause("nonexistent")
        assert success is False

    def test_resume_non_paused_agent(self, executor):
        """Test resuming non-paused agent returns False."""
        success = executor.resume("nonexistent")
        assert success is False


# =============================================================================
# CLEANUP TESTS
# =============================================================================

class TestCleanup:
    """Test cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_completed_agent(self, executor):
        """Test cleaning up completed agent."""
        await executor.spawn_agent("cleanup-test", "Quick task")
        await executor.wait_for("cleanup-test", timeout=5.0)

        success = executor.cleanup("cleanup-test")

        assert success is True
        assert "cleanup-test" not in executor._tasks

    @pytest.mark.asyncio
    async def test_cleanup_running_agent_fails(self, mock_core):
        """Test that cleanup of running agent fails."""
        async def slow_process(*args, **kwargs):
            await asyncio.sleep(10)
            return "Done"

        mock_core.process = AsyncMock(side_effect=slow_process)
        executor = AgentExecutor(mock_core, max_concurrent=3)

        await executor.spawn_agent("running-cleanup", "Slow task")
        await asyncio.sleep(0.05)  # Let it start

        success = executor.cleanup("running-cleanup")
        assert success is False

    @pytest.mark.asyncio
    async def test_cleanup_all(self, executor):
        """Test cleaning up all completed agents."""
        await executor.spawn_agents([
            ("cleanup-1", "Task 1"),
            ("cleanup-2", "Task 2"),
            ("cleanup-3", "Task 3"),
        ])

        await executor.wait_for_all(timeout=5.0)

        cleaned = executor.cleanup_all()

        assert cleaned == 3
        assert len(executor._tasks) == 0


# =============================================================================
# STATUS AND STATS TESTS
# =============================================================================

class TestStatusAndStats:
    """Test status and statistics methods."""

    @pytest.mark.asyncio
    async def test_get_status(self, executor):
        """Test getting status of an agent."""
        await executor.spawn_agent("status-test", "Quick task")
        await executor.wait_for("status-test", timeout=5.0)

        status = executor.get_status("status-test")

        assert status["agent_id"] == "status-test"
        assert status["state"] == AgentState.COMPLETED.value
        assert status["result"] is not None
        assert status["error"] is None

    def test_get_status_nonexistent(self, executor):
        """Test getting status of nonexistent agent returns None."""
        status = executor.get_status("nonexistent")
        assert status is None

    @pytest.mark.asyncio
    async def test_get_all_status(self, executor):
        """Test getting status of all agents."""
        await executor.spawn_agents([
            ("all-status-1", "Task 1"),
            ("all-status-2", "Task 2"),
        ])

        await executor.wait_for_all(timeout=5.0)

        all_status = executor.get_all_status()

        assert len(all_status) == 2
        assert "all-status-1" in all_status
        assert "all-status-2" in all_status

    @pytest.mark.asyncio
    async def test_get_stats(self, executor):
        """Test getting executor statistics."""
        await executor.spawn_agents([
            ("stats-1", "Task 1"),
            ("stats-2", "Task 2"),
        ])

        await executor.wait_for_all(timeout=5.0)

        stats = executor.get_stats()

        assert stats["max_concurrent"] == 3
        assert stats["total_agents"] == 2
        assert "state_counts" in stats
        assert stats["state_counts"]["completed"] == 2


# =============================================================================
# GLOBAL EXECUTOR TESTS
# =============================================================================

class TestGlobalExecutor:
    """Test global executor singleton pattern."""

    def test_get_executor_without_core_returns_none(self):
        """Test get_executor without core returns None."""
        executor = get_executor()
        assert executor is None

    def test_get_executor_with_core_creates_instance(self, mock_core):
        """Test get_executor with core creates instance."""
        executor = get_executor(mock_core)

        assert executor is not None
        assert isinstance(executor, AgentExecutor)

    def test_get_executor_returns_same_instance(self, mock_core):
        """Test get_executor returns same instance."""
        executor1 = get_executor(mock_core)
        executor2 = get_executor()  # No core needed second time

        assert executor1 is executor2

    def test_set_executor(self, mock_core):
        """Test set_executor replaces global instance."""
        custom_executor = AgentExecutor(mock_core, max_concurrent=99)
        set_executor(custom_executor)

        retrieved = get_executor()

        assert retrieved is custom_executor
        assert retrieved.max_concurrent == 99


# =============================================================================
# PARALLEL EXECUTION VERIFICATION
# =============================================================================

class TestParallelExecution:
    """Verify that agents actually run in parallel."""

    @pytest.mark.asyncio
    async def test_parallel_execution_is_faster(self, mock_core):
        """Test that parallel execution completes faster than sequential."""
        task_duration = 0.05  # 50ms per task
        num_tasks = 4

        async def timed_process(*args, **kwargs):
            await asyncio.sleep(task_duration)
            return "Done"

        mock_core.process = AsyncMock(side_effect=timed_process)
        executor = AgentExecutor(mock_core, max_concurrent=4)

        import time
        start = time.time()

        # Spawn all agents
        for i in range(num_tasks):
            await executor.spawn_agent(f"parallel-{i}", f"Task {i}")

        # Wait for all
        await executor.wait_for_all(timeout=5.0)

        elapsed = time.time() - start

        # Sequential would take ~200ms (4 * 50ms)
        # Parallel should take ~50ms (+ overhead)
        # Allow for overhead, but should be much faster than sequential
        assert elapsed < (num_tasks * task_duration)  # Should be faster than sequential


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
