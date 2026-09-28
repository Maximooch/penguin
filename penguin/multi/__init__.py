"""Multi-agent coordination and execution.

This package provides components for running multiple agents in parallel:
- AgentExecutor: Background agent execution with concurrency control
- AgentCoordinator: Multi-agent orchestration and coordination
"""

from penguin.multi.admission import validate_spawn_request
from penguin.multi.executor import (
    AgentExecutionOutcome,
    AgentExecutor,
    AgentState,
    AgentTask,
    classify_agent_result,
    get_executor,
    set_executor,
)

__all__ = [
    "AgentExecutionOutcome",
    "AgentExecutor",
    "AgentState",
    "AgentTask",
    "classify_agent_result",
    "get_executor",
    "set_executor",
    "validate_spawn_request",
]
