"""Background agent execution for parallel multi-agent workflows.

This module provides the AgentExecutor class for running multiple agents
concurrently using asyncio.TaskGroup.
"""

import asyncio
import logging
import os
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """State of an agent in the executor."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentTask:
    """Represents a background agent task."""
    agent_id: str
    prompt: str
    state: AgentState = AgentState.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AgentExecutor:
    """Executes multiple agents in parallel with concurrency control.

    This class manages background agent execution using asyncio.TaskGroup
    for Python 3.11+ compatible parallel task management.

    Usage:
        executor = AgentExecutor(core, max_concurrent=5)

        # Spawn agents and get futures
        task_ids = await executor.spawn_agents([
            ("researcher", "Research topic X"),
            ("implementer", "Implement feature Y"),
        ])

        # Wait for specific agent
        result = await executor.wait_for(task_ids[0])

        # Wait for all agents
        results = await executor.wait_for_all(task_ids)

        # Check status
        status = executor.get_status("researcher")
    """

    def __init__(
        self,
        core: Any,
        max_concurrent: Optional[int] = None,
    ):
        """Initialize the executor.

        Args:
            core: PenguinCore instance for agent execution
            max_concurrent: Maximum concurrent agents (default from env or 10)
        """
        self._core = core
        self._max_concurrent = max_concurrent or int(
            os.getenv("PENGUIN_MAX_CONCURRENT_TASKS", "10")
        )
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._tasks: Dict[str, AgentTask] = {}
        self._lock = asyncio.Lock()

    @property
    def max_concurrent(self) -> int:
        """Maximum concurrent agent count."""
        return self._max_concurrent

    @property
    def running_count(self) -> int:
        """Number of currently running agents."""
        return sum(1 for t in self._tasks.values() if t.state == AgentState.RUNNING)

    @property
    def pending_count(self) -> int:
        """Number of pending agents."""
        return sum(1 for t in self._tasks.values() if t.state == AgentState.PENDING)

    async def spawn_agent(
        self,
        agent_id: str,
        prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Spawn a single agent as a background task.

        Args:
            agent_id: Unique identifier for the agent
            prompt: Initial prompt for the agent
            metadata: Optional metadata for the task

        Returns:
            The agent_id for tracking

        Raises:
            ValueError: If agent_id already exists
        """
        async with self._lock:
            if agent_id in self._tasks:
                raise ValueError(f"Agent '{agent_id}' already exists")

            agent_task = AgentTask(
                agent_id=agent_id,
                prompt=prompt,
                state=AgentState.PENDING,
                metadata=metadata or {},
            )
            self._tasks[agent_id] = agent_task

        # Start the background task
        task = asyncio.create_task(self._run_agent(agent_task))
        agent_task.task = task

        return agent_id

    async def spawn_agents(
        self,
        agents: List[Tuple[str, str]],
        metadata: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[str]:
        """Spawn multiple agents in parallel.

        Args:
            agents: List of (agent_id, prompt) tuples
            metadata: Optional dict mapping agent_id to metadata

        Returns:
            List of agent_ids
        """
        metadata = metadata or {}
        agent_ids = []

        for agent_id, prompt in agents:
            aid = await self.spawn_agent(
                agent_id, prompt, metadata.get(agent_id)
            )
            agent_ids.append(aid)

        return agent_ids

    async def _run_agent(self, agent_task: AgentTask) -> None:
        """Internal method to run an agent with semaphore control.

        Args:
            agent_task: The AgentTask to execute
        """
        try:
            async with self._semaphore:
                agent_task.state = AgentState.RUNNING
                logger.info(f"Agent '{agent_task.agent_id}' started execution")

                # Execute via core.process
                if hasattr(self._core, "process"):
                    result = await self._core.process(
                        input_data={"text": agent_task.prompt},
                        agent_id=agent_task.agent_id,
                    )
                elif hasattr(self._core, "chat"):
                    result = await self._core.chat(agent_task.prompt)
                else:
                    result = f"Core does not have process or chat method"

                agent_task.result = str(result) if result else ""
                agent_task.state = AgentState.COMPLETED
                logger.info(f"Agent '{agent_task.agent_id}' completed")

        except asyncio.CancelledError:
            agent_task.state = AgentState.CANCELLED
            logger.info(f"Agent '{agent_task.agent_id}' was cancelled")
            raise

        except Exception as e:
            agent_task.error = str(e)
            agent_task.state = AgentState.FAILED
            logger.error(f"Agent '{agent_task.agent_id}' failed: {e}")

    async def wait_for(
        self,
        agent_id: str,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """Wait for a specific agent to complete.

        Args:
            agent_id: The agent to wait for
            timeout: Optional timeout in seconds

        Returns:
            The agent's result or None if not found/failed

        Raises:
            asyncio.TimeoutError: If timeout exceeded
        """
        agent_task = self._tasks.get(agent_id)
        if not agent_task or not agent_task.task:
            return None

        try:
            await asyncio.wait_for(agent_task.task, timeout=timeout)
        except asyncio.TimeoutError:
            raise

        return agent_task.result

    async def wait_for_all(
        self,
        agent_ids: Optional[List[str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Optional[str]]:
        """Wait for multiple agents to complete.

        Args:
            agent_ids: List of agent IDs to wait for (None = all)
            timeout: Optional timeout in seconds

        Returns:
            Dict mapping agent_id to result
        """
        if agent_ids is None:
            agent_ids = list(self._tasks.keys())

        tasks = []
        for aid in agent_ids:
            agent_task = self._tasks.get(aid)
            if agent_task and agent_task.task:
                tasks.append(agent_task.task)

        if tasks:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )

        return {
            aid: self._tasks[aid].result
            for aid in agent_ids
            if aid in self._tasks
        }

    def get_status(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a specific agent.

        Args:
            agent_id: The agent to check

        Returns:
            Dict with state, result, error, or None if not found
        """
        agent_task = self._tasks.get(agent_id)
        if not agent_task:
            return None

        return {
            "agent_id": agent_task.agent_id,
            "state": agent_task.state.value,
            "result": agent_task.result,
            "error": agent_task.error,
            "metadata": agent_task.metadata,
        }

    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all agents.

        Returns:
            Dict mapping agent_id to status dict
        """
        return {
            aid: self.get_status(aid)
            for aid in self._tasks
        }

    async def cancel(self, agent_id: str) -> bool:
        """Cancel a running agent.

        Args:
            agent_id: The agent to cancel

        Returns:
            True if cancelled, False if not found or already complete
        """
        agent_task = self._tasks.get(agent_id)
        if not agent_task or not agent_task.task:
            return False

        if agent_task.state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
            return False

        agent_task.task.cancel()
        agent_task.state = AgentState.CANCELLED
        return True

    async def cancel_all(self) -> int:
        """Cancel all running agents.

        Returns:
            Number of agents cancelled
        """
        cancelled = 0
        for agent_id in list(self._tasks.keys()):
            if await self.cancel(agent_id):
                cancelled += 1
        return cancelled

    def pause(self, agent_id: str) -> bool:
        """Pause an agent (marks as paused, actual pause depends on agent implementation).

        Args:
            agent_id: The agent to pause

        Returns:
            True if marked as paused
        """
        agent_task = self._tasks.get(agent_id)
        if not agent_task or agent_task.state != AgentState.RUNNING:
            return False

        agent_task.state = AgentState.PAUSED
        return True

    def resume(self, agent_id: str) -> bool:
        """Resume a paused agent.

        Args:
            agent_id: The agent to resume

        Returns:
            True if marked as running
        """
        agent_task = self._tasks.get(agent_id)
        if not agent_task or agent_task.state != AgentState.PAUSED:
            return False

        agent_task.state = AgentState.RUNNING
        return True

    def cleanup(self, agent_id: str) -> bool:
        """Remove a completed agent from tracking.

        Args:
            agent_id: The agent to remove

        Returns:
            True if removed
        """
        if agent_id in self._tasks:
            agent_task = self._tasks[agent_id]
            if agent_task.state in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
                del self._tasks[agent_id]
                return True
        return False

    def cleanup_all(self) -> int:
        """Remove all completed agents from tracking.

        Returns:
            Number of agents cleaned up
        """
        cleaned = 0
        for agent_id in list(self._tasks.keys()):
            if self.cleanup(agent_id):
                cleaned += 1
        return cleaned

    def get_stats(self) -> Dict[str, Any]:
        """Get executor statistics.

        Returns:
            Dict with counts and settings
        """
        state_counts = {state.value: 0 for state in AgentState}
        for agent_task in self._tasks.values():
            state_counts[agent_task.state.value] += 1

        return {
            "max_concurrent": self._max_concurrent,
            "total_agents": len(self._tasks),
            "state_counts": state_counts,
            "semaphore_value": self._semaphore._value,
        }


# Singleton instance for global access
_executor_instance: Optional[AgentExecutor] = None


def get_executor(core: Any = None) -> Optional[AgentExecutor]:
    """Get the global executor instance.

    Args:
        core: PenguinCore instance (required on first call)

    Returns:
        The global AgentExecutor instance
    """
    global _executor_instance
    if _executor_instance is None and core is not None:
        _executor_instance = AgentExecutor(core)
    return _executor_instance


def set_executor(executor: AgentExecutor) -> None:
    """Set the global executor instance.

    Args:
        executor: The AgentExecutor to use globally
    """
    global _executor_instance
    _executor_instance = executor
