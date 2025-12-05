"""Temporal workflow definitions for ITUV lifecycle.

The ITUVWorkflow orchestrates the four phases (IMPLEMENT, TEST, USE, VERIFY)
with proper error handling, retries, signals, and queries.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Check if temporalio is available
try:
    from temporalio import workflow
    from temporalio.common import RetryPolicy
    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False
    # Create dummy decorators
    class workflow:
        @staticmethod
        def defn(cls):
            return cls
        @staticmethod
        def run(func):
            return func
        @staticmethod
        def signal(func):
            return func
        @staticmethod
        def query(func):
            return func
    
    class RetryPolicy:
        def __init__(self, **kwargs):
            pass

from .activities import (
    PhaseInput,
    PhaseOutput,
    implement_activity,
    test_activity,
    use_activity,
    verify_activity,
)


class WorkflowPhase(str, Enum):
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


@dataclass
class ITUVWorkflowInput:
    """Input for ITUV workflow."""
    task_id: str
    blueprint_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


@dataclass
class ITUVWorkflowResult:
    """Result of ITUV workflow."""
    success: bool
    phase: WorkflowPhase
    phase_results: List[Dict[str, Any]]
    artifacts: Dict[str, Any]
    error_message: Optional[str] = None


@workflow.defn
class ITUVWorkflow:
    """Temporal workflow for ITUV lifecycle execution.
    
    This workflow:
    1. Executes phases sequentially: IMPLEMENT → TEST → USE → VERIFY
    2. Handles retries with backoff for each phase
    3. Supports pause/resume/cancel signals
    4. Provides status queries
    5. Collects artifacts from each phase
    """
    
    def __init__(self):
        self._phase = WorkflowPhase.PENDING
        self._paused = False
        self._cancelled = False
        self._feedback: Optional[Dict[str, Any]] = None
        self._phase_results: List[Dict[str, Any]] = []
        self._artifacts: Dict[str, Any] = {}
        self._progress = 0
        self._error_message: Optional[str] = None
        self._context_snapshot_id: Optional[str] = None
    
    @workflow.run
    async def run(self, input: ITUVWorkflowInput) -> ITUVWorkflowResult:
        """Execute the ITUV workflow.
        
        Args:
            input: Workflow input with task_id and config.
            
        Returns:
            Workflow result with phase results and artifacts.
        """
        config = input.config or {}
        
        # Default timeouts
        phase_timeouts = config.get("phase_timeouts", {
            "implement": 600,
            "test": 300,
            "use": 180,
            "verify": 120,
        })
        
        # Retry policy
        retry_policy = RetryPolicy(
            initial_interval=timedelta(seconds=config.get("initial_interval_sec", 1)),
            maximum_interval=timedelta(seconds=config.get("max_interval_sec", 60)),
            backoff_coefficient=config.get("backoff_coefficient", 2.0),
            maximum_attempts=config.get("max_retries", 3) + 1,
        )
        
        phases = [
            (WorkflowPhase.IMPLEMENT, implement_activity, phase_timeouts.get("implement", 600)),
            (WorkflowPhase.TEST, test_activity, phase_timeouts.get("test", 300)),
            (WorkflowPhase.USE, use_activity, phase_timeouts.get("use", 180)),
            (WorkflowPhase.VERIFY, verify_activity, phase_timeouts.get("verify", 120)),
        ]
        
        progress_per_phase = 100 // len(phases)
        
        for i, (phase, activity, timeout) in enumerate(phases):
            # Check for cancellation
            if self._cancelled:
                self._phase = WorkflowPhase.CANCELLED
                return ITUVWorkflowResult(
                    success=False,
                    phase=self._phase,
                    phase_results=self._phase_results,
                    artifacts=self._artifacts,
                    error_message="Workflow cancelled",
                )
            
            # Wait while paused
            while self._paused:
                if TEMPORAL_AVAILABLE:
                    await workflow.wait_condition(lambda: not self._paused or self._cancelled)
                if self._cancelled:
                    break
            
            if self._cancelled:
                continue
            
            # Update phase
            self._phase = phase
            
            # Prepare activity input
            phase_input = PhaseInput(
                workflow_id=workflow.info().workflow_id if TEMPORAL_AVAILABLE else "native",
                task_id=input.task_id,
                blueprint_id=input.blueprint_id,
                context_snapshot_id=self._context_snapshot_id,
                config=config,
            )
            
            # Execute activity
            try:
                if TEMPORAL_AVAILABLE:
                    result: PhaseOutput = await workflow.execute_activity(
                        activity,
                        phase_input,
                        start_to_close_timeout=timedelta(seconds=timeout),
                        retry_policy=retry_policy,
                    )
                else:
                    # Fallback for when Temporal is not available
                    result = await activity(phase_input)
                
                # Record result
                phase_result = {
                    "phase": phase.value,
                    "success": result.success,
                    "artifacts": result.artifacts,
                    "error_message": result.error_message,
                }
                self._phase_results.append(phase_result)
                
                # Update context snapshot
                if result.context_snapshot_id:
                    self._context_snapshot_id = result.context_snapshot_id
                
                # Merge artifacts
                self._artifacts[phase.value] = result.artifacts
                
                # Update progress
                self._progress = (i + 1) * progress_per_phase
                
                # Check for failure
                if not result.success:
                    self._phase = WorkflowPhase.FAILED
                    self._error_message = result.error_message
                    return ITUVWorkflowResult(
                        success=False,
                        phase=self._phase,
                        phase_results=self._phase_results,
                        artifacts=self._artifacts,
                        error_message=result.error_message,
                    )
            
            except Exception as e:
                self._phase = WorkflowPhase.FAILED
                self._error_message = str(e)
                self._phase_results.append({
                    "phase": phase.value,
                    "success": False,
                    "artifacts": {},
                    "error_message": str(e),
                })
                return ITUVWorkflowResult(
                    success=False,
                    phase=self._phase,
                    phase_results=self._phase_results,
                    artifacts=self._artifacts,
                    error_message=str(e),
                )
        
        # All phases completed successfully
        self._phase = WorkflowPhase.COMPLETED
        self._progress = 100
        
        return ITUVWorkflowResult(
            success=True,
            phase=self._phase,
            phase_results=self._phase_results,
            artifacts=self._artifacts,
        )
    
    # Signals
    
    @workflow.signal
    async def pause(self) -> None:
        """Pause workflow execution."""
        self._paused = True
        self._phase = WorkflowPhase.PAUSED
        logger.info("Workflow paused")
    
    @workflow.signal
    async def resume(self) -> None:
        """Resume workflow execution."""
        self._paused = False
        # Phase will be updated when execution continues
        logger.info("Workflow resumed")
    
    @workflow.signal
    async def cancel(self) -> None:
        """Cancel workflow execution."""
        self._cancelled = True
        logger.info("Workflow cancellation requested")
    
    @workflow.signal
    async def inject_feedback(self, feedback: Dict[str, Any]) -> None:
        """Inject human feedback into workflow."""
        self._feedback = feedback
        logger.info(f"Feedback injected: {feedback}")
    
    # Queries
    
    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """Get current workflow status."""
        return {
            "phase": self._phase.value,
            "paused": self._paused,
            "cancelled": self._cancelled,
            "progress": self._progress,
            "error_message": self._error_message,
        }
    
    @workflow.query
    def get_progress(self) -> int:
        """Get workflow progress percentage."""
        return self._progress
    
    @workflow.query
    def get_artifacts(self) -> Dict[str, Any]:
        """Get collected artifacts."""
        return self._artifacts
    
    @workflow.query
    def get_phase_results(self) -> List[Dict[str, Any]]:
        """Get results from completed phases."""
        return self._phase_results

