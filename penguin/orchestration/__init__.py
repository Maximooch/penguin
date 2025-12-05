"""Penguin Orchestration - Durable workflow execution for ITUV lifecycle.

This package provides backend-agnostic workflow orchestration with support for:
- Native backend (NetworkX DAG + in-memory state)
- Temporal backend (durable workflows with retries, signals, queries)

Usage:
    from penguin.orchestration import get_backend, OrchestrationBackend
    
    backend = get_backend()  # Returns configured backend
    workflow_id = await backend.start_workflow(task_id, blueprint_id)
    status = await backend.get_workflow_status(workflow_id)
"""

from .backend import (
    OrchestrationBackend,
    WorkflowStatus,
    WorkflowPhase,
    WorkflowInfo,
    WorkflowResult,
)
from .state import WorkflowState, WorkflowStateStorage
from .config import OrchestrationConfig, get_backend

__all__ = [
    # Backend interface
    "OrchestrationBackend",
    "WorkflowStatus",
    "WorkflowPhase",
    "WorkflowInfo",
    "WorkflowResult",
    # State management
    "WorkflowState",
    "WorkflowStateStorage",
    # Config and factory
    "OrchestrationConfig",
    "get_backend",
]

