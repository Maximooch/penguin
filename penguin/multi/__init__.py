"""Multi-agent coordination and execution.

This package provides components for running multiple agents in parallel:
- AgentExecutor: Background agent execution with concurrency control
- AgentCoordinator: Multi-agent orchestration and coordination
"""

from penguin.multi.executor import (
    AgentExecutor,
    AgentState,
    AgentTask,
    get_executor,
    set_executor,
)

__all__ = [
    "AgentExecutor",
    "AgentState",
    "AgentTask",
    "get_executor",
    "set_executor",
]
