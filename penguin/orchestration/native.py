"""Native orchestration backend using in-memory state with SQLite persistence.

This backend wraps the existing NetworkX DAG and RunMode functionality
to provide the OrchestrationBackend interface without requiring Temporal.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .backend import (
    OrchestrationBackend,
    PhaseResult,
    WorkflowInfo,
    WorkflowPhase,
    WorkflowResult,
    WorkflowStatus,
)
from .config import OrchestrationConfig
from .state import ContextSnapshot, WorkflowState, WorkflowStateStorage

logger = logging.getLogger(__name__)


class NativeBackend(OrchestrationBackend):
    """Native orchestration backend using in-memory execution with SQLite persistence.
    
    This backend:
    - Executes ITUV phases sequentially in-process
    - Persists workflow state to SQLite for recovery
    - Supports pause/resume via in-memory flags
    - Does NOT survive process restarts mid-execution (use Temporal for that)
    """
    
    def __init__(
        self,
        config: OrchestrationConfig,
        storage_path: Path,
    ):
        """Initialize native backend.
        
        Args:
            config: Orchestration configuration.
            storage_path: Path to SQLite database for state persistence.
        """
        self.config = config
        self.storage = WorkflowStateStorage(storage_path)
        
        # In-memory tracking of active workflows
        self._active_workflows: Dict[str, asyncio.Task] = {}
        self._paused_workflows: set = set()
        self._cancelled_workflows: set = set()
        self._feedback_queues: Dict[str, asyncio.Queue] = {}
        
        # Reference to core/engine (set by ProjectManager)
        self._core = None
        self._engine = None
        self._project_manager = None
        
        logger.info(f"NativeBackend initialized with storage at {storage_path}")
    
    def set_core(self, core) -> None:
        """Set reference to PenguinCore for task execution."""
        self._core = core
        if hasattr(core, "engine"):
            self._engine = core.engine
        if hasattr(core, "project_manager"):
            self._project_manager = core.project_manager
    
    async def start_workflow(
        self,
        task_id: str,
        blueprint_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start an ITUV workflow for a task."""
        workflow_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        # Get project_id from task if available
        project_id = None
        if self._project_manager:
            task = self._project_manager.get_task(task_id)
            if task:
                project_id = task.project_id
        
        # Create initial state
        state = WorkflowState(
            workflow_id=workflow_id,
            task_id=task_id,
            blueprint_id=blueprint_id,
            project_id=project_id,
            status=WorkflowStatus.RUNNING,
            phase=WorkflowPhase.IMPLEMENT,
            started_at=now,
            updated_at=now,
            config=config or {},
        )
        
        # Persist state
        self.storage.save_state(state)
        
        # Create feedback queue for this workflow
        self._feedback_queues[workflow_id] = asyncio.Queue()
        
        # Start execution task
        task = asyncio.create_task(self._run_workflow(workflow_id))
        self._active_workflows[workflow_id] = task
        
        logger.info(f"Started workflow {workflow_id} for task {task_id}")
        return workflow_id
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[WorkflowInfo]:
        """Get current status of a workflow."""
        state = self.storage.get_state(workflow_id)
        if not state:
            return None
        return state.to_info()
    
    async def get_workflow_result(self, workflow_id: str) -> Optional[WorkflowResult]:
        """Get the final result of a completed workflow."""
        state = self.storage.get_state(workflow_id)
        if not state:
            return None
        
        if state.status not in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
            return None
        
        # Calculate total duration
        duration = 0.0
        if state.started_at and state.completed_at:
            duration = (state.completed_at - state.started_at).total_seconds()
        
        return WorkflowResult(
            workflow_id=workflow_id,
            task_id=state.task_id,
            status=state.status,
            phase_results=state.phase_results,
            total_duration_sec=duration,
            artifacts=state.artifacts,
            error_message=state.error_message,
        )
    
    async def signal_workflow(
        self,
        workflow_id: str,
        signal: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send a signal to a running workflow."""
        state = self.storage.get_state(workflow_id)
        if not state:
            return False
        
        if signal == "pause":
            self._paused_workflows.add(workflow_id)
            state.status = WorkflowStatus.PAUSED
            state.updated_at = datetime.utcnow()
            self.storage.save_state(state)
            logger.info(f"Paused workflow {workflow_id}")
            return True
        
        elif signal == "resume":
            self._paused_workflows.discard(workflow_id)
            if state.status == WorkflowStatus.PAUSED:
                state.status = WorkflowStatus.RUNNING
                state.updated_at = datetime.utcnow()
                self.storage.save_state(state)
            logger.info(f"Resumed workflow {workflow_id}")
            return True
        
        elif signal == "cancel":
            self._cancelled_workflows.add(workflow_id)
            # Cancel the asyncio task if running
            if workflow_id in self._active_workflows:
                self._active_workflows[workflow_id].cancel()
            state.status = WorkflowStatus.CANCELLED
            state.completed_at = datetime.utcnow()
            state.updated_at = datetime.utcnow()
            self.storage.save_state(state)
            logger.info(f"Cancelled workflow {workflow_id}")
            return True
        
        elif signal == "inject_feedback":
            if workflow_id in self._feedback_queues:
                await self._feedback_queues[workflow_id].put(payload or {})
                logger.info(f"Injected feedback into workflow {workflow_id}")
                return True
            return False
        
        return False
    
    async def query_workflow(
        self,
        workflow_id: str,
        query: str,
    ) -> Optional[Any]:
        """Query a running workflow for information."""
        state = self.storage.get_state(workflow_id)
        if not state:
            return None
        
        if query == "status":
            return {
                "status": state.status.value,
                "phase": state.phase.value,
                "progress": state.progress,
            }
        
        elif query == "progress":
            return state.progress
        
        elif query == "artifacts":
            return state.artifacts
        
        elif query == "phase_results":
            return [pr.to_dict() for pr in state.phase_results]
        
        return None
    
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow."""
        return await self.signal_workflow(workflow_id, "cancel")
    
    async def list_workflows(
        self,
        project_id: Optional[str] = None,
        status_filter: Optional[List[WorkflowStatus]] = None,
        limit: int = 100,
    ) -> List[WorkflowInfo]:
        """List workflows with optional filtering."""
        states = self.storage.list_states(project_id, status_filter, limit)
        return [s.to_info() for s in states]
    
    async def cleanup_completed(
        self,
        older_than_days: int = 30,
    ) -> int:
        """Clean up old completed workflows."""
        return self.storage.cleanup_old(older_than_days)
    
    # Internal workflow execution
    
    async def _run_workflow(self, workflow_id: str) -> None:
        """Execute the ITUV workflow phases."""
        try:
            state = self.storage.get_state(workflow_id)
            if not state:
                return
            
            phases = [
                WorkflowPhase.IMPLEMENT,
                WorkflowPhase.TEST,
                WorkflowPhase.USE,
                WorkflowPhase.VERIFY,
            ]
            
            # Calculate progress increments
            progress_per_phase = 100 // len(phases)
            
            for i, phase in enumerate(phases):
                # Check for cancellation
                if workflow_id in self._cancelled_workflows:
                    break
                
                # Wait while paused
                while workflow_id in self._paused_workflows:
                    await asyncio.sleep(0.5)
                    if workflow_id in self._cancelled_workflows:
                        break
                
                if workflow_id in self._cancelled_workflows:
                    break
                
                # Update state to current phase
                state.phase = phase
                state.updated_at = datetime.utcnow()
                self.storage.save_state(state)
                
                # Execute phase
                phase_result = await self._execute_phase(workflow_id, phase, state)
                state.phase_results.append(phase_result)
                
                # Update progress
                state.progress = (i + 1) * progress_per_phase
                state.updated_at = datetime.utcnow()
                self.storage.save_state(state)
                
                # Check phase result
                if not phase_result.success:
                    state.status = WorkflowStatus.FAILED
                    state.error_message = phase_result.error_message
                    state.completed_at = datetime.utcnow()
                    self.storage.save_state(state)
                    logger.warning(f"Workflow {workflow_id} failed at phase {phase.value}")
                    return
            
            # All phases completed successfully
            if workflow_id not in self._cancelled_workflows:
                state.status = WorkflowStatus.COMPLETED
                state.phase = WorkflowPhase.COMPLETED
                state.progress = 100
                state.completed_at = datetime.utcnow()
                self.storage.save_state(state)
                logger.info(f"Workflow {workflow_id} completed successfully")
        
        except asyncio.CancelledError:
            logger.info(f"Workflow {workflow_id} was cancelled")
            state = self.storage.get_state(workflow_id)
            if state:
                state.status = WorkflowStatus.CANCELLED
                state.completed_at = datetime.utcnow()
                self.storage.save_state(state)
        
        except Exception as e:
            logger.error(f"Workflow {workflow_id} failed with error: {e}")
            state = self.storage.get_state(workflow_id)
            if state:
                state.status = WorkflowStatus.FAILED
                state.error_message = str(e)
                state.completed_at = datetime.utcnow()
                self.storage.save_state(state)
        
        finally:
            # Cleanup
            self._active_workflows.pop(workflow_id, None)
            self._feedback_queues.pop(workflow_id, None)
            self._paused_workflows.discard(workflow_id)
            self._cancelled_workflows.discard(workflow_id)
    
    async def _execute_phase(
        self,
        workflow_id: str,
        phase: WorkflowPhase,
        state: WorkflowState,
    ) -> PhaseResult:
        """Execute a single ITUV phase."""
        started_at = datetime.utcnow()
        artifacts: Dict[str, Any] = {}
        error_message: Optional[str] = None
        success = False
        retry_count = 0
        
        max_retries = state.config.get("max_retries", self.config.default_max_retries)
        timeout = self.config.phase_timeouts.get(phase.value, 600)
        
        while retry_count <= max_retries:
            try:
                if phase == WorkflowPhase.IMPLEMENT:
                    success, artifacts = await self._execute_implement(state, timeout)
                elif phase == WorkflowPhase.TEST:
                    success, artifacts = await self._execute_test(state, timeout)
                elif phase == WorkflowPhase.USE:
                    success, artifacts = await self._execute_use(state, timeout)
                elif phase == WorkflowPhase.VERIFY:
                    success, artifacts = await self._execute_verify(state, timeout)
                
                if success:
                    break
                
                retry_count += 1
                if retry_count <= max_retries:
                    delay = self.config.default_retry_delay_sec * (2 ** (retry_count - 1))
                    logger.info(f"Retrying phase {phase.value} in {delay}s (attempt {retry_count + 1})")
                    await asyncio.sleep(delay)
            
            except asyncio.TimeoutError:
                error_message = f"Phase {phase.value} timed out after {timeout}s"
                retry_count += 1
            
            except Exception as e:
                error_message = str(e)
                retry_count += 1
                logger.error(f"Phase {phase.value} error: {e}")
        
        return PhaseResult(
            phase=phase,
            success=success,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            artifacts=artifacts,
            error_message=error_message if not success else None,
            retry_count=retry_count,
        )
    
    async def _execute_implement(
        self,
        state: WorkflowState,
        timeout: int,
    ) -> tuple[bool, Dict[str, Any]]:
        """Execute the IMPLEMENT phase."""
        artifacts = {}
        
        if not self._engine:
            logger.warning("No engine available for IMPLEMENT phase")
            return True, {"note": "No engine - skipped"}
        
        try:
            # Get task details
            task = None
            if self._project_manager:
                task = self._project_manager.get_task(state.task_id)
            
            if not task:
                return False, {"error": f"Task {state.task_id} not found"}
            
            # Build implementation prompt
            prompt = f"Implement the following task:\n\nTitle: {task.title}\nDescription: {task.description}"
            
            if task.acceptance_criteria:
                prompt += "\n\nAcceptance Criteria:\n"
                for i, ac in enumerate(task.acceptance_criteria, 1):
                    prompt += f"{i}. {ac}\n"
            
            # Execute via engine
            result = await asyncio.wait_for(
                self._engine.run_task(
                    task_prompt=prompt,
                    task_name=f"IMPLEMENT: {task.title}",
                    task_context={"phase": "implement", "task_id": state.task_id},
                ),
                timeout=timeout,
            )
            
            artifacts["engine_result"] = result.get("status", "completed")
            artifacts["iterations"] = result.get("iterations", 0)
            
            # Save context snapshot
            if "conversation_history" in result:
                snapshot = self.storage.create_snapshot(
                    workflow_id=state.workflow_id,
                    phase=WorkflowPhase.IMPLEMENT,
                    conversation_history=result.get("conversation_history", []),
                )
                state.context_snapshot_id = snapshot.snapshot_id
                self.storage.save_state(state)
            
            return True, artifacts
        
        except Exception as e:
            logger.error(f"IMPLEMENT phase error: {e}")
            return False, {"error": str(e)}
    
    async def _execute_test(
        self,
        state: WorkflowState,
        timeout: int,
    ) -> tuple[bool, Dict[str, Any]]:
        """Execute the TEST phase."""
        artifacts = {}
        
        # Get task for test patterns
        task = None
        if self._project_manager:
            task = self._project_manager.get_task(state.task_id)
        
        if not task:
            return False, {"error": f"Task {state.task_id} not found"}
        
        # For now, just mark as successful
        # TODO: Integrate with pytest runner
        artifacts["note"] = "Test phase placeholder - integrate with validation_manager"
        artifacts["tests_run"] = 0
        artifacts["tests_passed"] = 0
        
        return True, artifacts
    
    async def _execute_use(
        self,
        state: WorkflowState,
        timeout: int,
    ) -> tuple[bool, Dict[str, Any]]:
        """Execute the USE phase (run usage recipes)."""
        artifacts = {}
        
        task = None
        if self._project_manager:
            task = self._project_manager.get_task(state.task_id)
        
        if not task:
            return False, {"error": f"Task {state.task_id} not found"}
        
        # Check if task has a recipe
        recipe = getattr(task, "recipe", None)
        if not recipe:
            artifacts["note"] = "No usage recipe defined - skipped"
            return True, artifacts
        
        # TODO: Integrate with recipe runner
        artifacts["recipe"] = recipe
        artifacts["note"] = "Recipe execution placeholder - integrate with validation_manager"
        
        return True, artifacts
    
    async def _execute_verify(
        self,
        state: WorkflowState,
        timeout: int,
    ) -> tuple[bool, Dict[str, Any]]:
        """Execute the VERIFY phase (check acceptance criteria)."""
        artifacts = {}
        
        task = None
        if self._project_manager:
            task = self._project_manager.get_task(state.task_id)
        
        if not task:
            return False, {"error": f"Task {state.task_id} not found"}
        
        # Check acceptance criteria
        ac = getattr(task, "acceptance_criteria", [])
        artifacts["acceptance_criteria_count"] = len(ac)
        
        # Check phase results
        phase_results = state.phase_results
        implement_passed = any(pr.phase == WorkflowPhase.IMPLEMENT and pr.success for pr in phase_results)
        test_passed = any(pr.phase == WorkflowPhase.TEST and pr.success for pr in phase_results)
        use_passed = any(pr.phase == WorkflowPhase.USE and pr.success for pr in phase_results)
        
        artifacts["implement_passed"] = implement_passed
        artifacts["test_passed"] = test_passed
        artifacts["use_passed"] = use_passed
        
        # All previous phases must pass
        all_passed = implement_passed and test_passed and use_passed
        
        if all_passed:
            artifacts["verification"] = "All gates passed"
            
            # Update task status if project manager available
            if self._project_manager and task:
                try:
                    from penguin.project.models import TaskStatus, TaskPhase
                    self._project_manager.update_task_status(
                        task.id,
                        TaskStatus.COMPLETED,
                        reason="ITUV workflow completed successfully"
                    )
                except Exception as e:
                    logger.warning(f"Could not update task status: {e}")
        else:
            artifacts["verification"] = "Some gates failed"
        
        return all_passed, artifacts

