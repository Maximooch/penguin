"""Abstract orchestration backend interface.

Defines the contract that all orchestration backends (native, Temporal, etc.) must implement.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowPhase(Enum):
    """ITUV workflow phases."""
    PENDING = "pending"
    IMPLEMENT = "implement"
    TEST = "test"
    USE = "use"
    VERIFY = "verify"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class WorkflowStatus(Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_INPUT = "waiting_input"  # Waiting for human clarification


@dataclass
class WorkflowInfo:
    """Summary information about a workflow."""
    workflow_id: str
    task_id: str
    blueprint_id: Optional[str]
    project_id: Optional[str]
    status: WorkflowStatus
    phase: WorkflowPhase
    started_at: datetime
    updated_at: datetime
    progress: int = 0  # 0-100 percentage
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "blueprint_id": self.blueprint_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "error_message": self.error_message,
        }


@dataclass
class PhaseResult:
    """Result of a single ITUV phase."""
    phase: WorkflowPhase
    success: bool
    started_at: datetime
    completed_at: datetime
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    retry_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "phase": self.phase.value,
            "success": self.success,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "artifacts": self.artifacts,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }


@dataclass
class WorkflowResult:
    """Final result of a completed workflow."""
    workflow_id: str
    task_id: str
    status: WorkflowStatus
    phase_results: List[PhaseResult] = field(default_factory=list)
    total_duration_sec: float = 0.0
    artifacts: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    
    @property
    def success(self) -> bool:
        """Check if workflow completed successfully."""
        return self.status == WorkflowStatus.COMPLETED
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "success": self.success,
            "phase_results": [pr.to_dict() for pr in self.phase_results],
            "total_duration_sec": self.total_duration_sec,
            "artifacts": self.artifacts,
            "error_message": self.error_message,
        }


class OrchestrationBackend(ABC):
    """Abstract base class for orchestration backends.
    
    Implementations:
    - NativeBackend: In-memory workflow execution with NetworkX DAG
    - TemporalBackend: Durable workflow execution via Temporal
    """
    
    @abstractmethod
    async def start_workflow(
        self,
        task_id: str,
        blueprint_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start an ITUV workflow for a task.
        
        Args:
            task_id: ID of the task to execute.
            blueprint_id: Optional Blueprint ID for context.
            config: Optional workflow configuration (timeouts, retries, etc.).
            
        Returns:
            Workflow ID for tracking.
        """
        pass
    
    @abstractmethod
    async def get_workflow_status(self, workflow_id: str) -> Optional[WorkflowInfo]:
        """Get current status of a workflow.
        
        Args:
            workflow_id: ID of the workflow.
            
        Returns:
            WorkflowInfo or None if not found.
        """
        pass
    
    @abstractmethod
    async def get_workflow_result(self, workflow_id: str) -> Optional[WorkflowResult]:
        """Get the final result of a completed workflow.
        
        Args:
            workflow_id: ID of the workflow.
            
        Returns:
            WorkflowResult or None if not found or not completed.
        """
        pass
    
    @abstractmethod
    async def signal_workflow(
        self,
        workflow_id: str,
        signal: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send a signal to a running workflow.
        
        Supported signals:
        - "pause": Pause workflow execution
        - "resume": Resume paused workflow
        - "cancel": Cancel workflow
        - "inject_feedback": Provide human clarification
        
        Args:
            workflow_id: ID of the workflow.
            signal: Signal name.
            payload: Optional signal payload.
            
        Returns:
            True if signal was delivered, False otherwise.
        """
        pass
    
    @abstractmethod
    async def query_workflow(
        self,
        workflow_id: str,
        query: str,
    ) -> Optional[Any]:
        """Query a running workflow for information.
        
        Supported queries:
        - "status": Current status and phase
        - "progress": Progress percentage
        - "artifacts": List of artifacts
        - "phase_results": Results of completed phases
        
        Args:
            workflow_id: ID of the workflow.
            query: Query name.
            
        Returns:
            Query result or None if not found.
        """
        pass
    
    @abstractmethod
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow.
        
        Args:
            workflow_id: ID of the workflow.
            
        Returns:
            True if cancelled, False otherwise.
        """
        pass
    
    @abstractmethod
    async def list_workflows(
        self,
        project_id: Optional[str] = None,
        status_filter: Optional[List[WorkflowStatus]] = None,
        limit: int = 100,
    ) -> List[WorkflowInfo]:
        """List workflows with optional filtering.
        
        Args:
            project_id: Optional project ID to filter by.
            status_filter: Optional list of statuses to filter by.
            limit: Maximum number of results.
            
        Returns:
            List of WorkflowInfo objects.
        """
        pass
    
    @abstractmethod
    async def cleanup_completed(
        self,
        older_than_days: int = 30,
    ) -> int:
        """Clean up old completed workflows.
        
        Args:
            older_than_days: Remove workflows older than this many days.
            
        Returns:
            Number of workflows cleaned up.
        """
        pass
    
    # Convenience methods with default implementations
    
    async def pause_workflow(self, workflow_id: str) -> bool:
        """Pause a running workflow."""
        return await self.signal_workflow(workflow_id, "pause")
    
    async def resume_workflow(self, workflow_id: str) -> bool:
        """Resume a paused workflow."""
        return await self.signal_workflow(workflow_id, "resume")
    
    async def inject_feedback(
        self,
        workflow_id: str,
        feedback: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Inject human feedback into a waiting workflow."""
        return await self.signal_workflow(
            workflow_id,
            "inject_feedback",
            {"feedback": feedback, "context": context or {}},
        )
    
    async def get_progress(self, workflow_id: str) -> Optional[int]:
        """Get workflow progress percentage."""
        result = await self.query_workflow(workflow_id, "progress")
        return result if isinstance(result, int) else None
    
    async def get_artifacts(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get workflow artifacts."""
        result = await self.query_workflow(workflow_id, "artifacts")
        return result if isinstance(result, dict) else None

