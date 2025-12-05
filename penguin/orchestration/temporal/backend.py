"""Temporal orchestration backend implementation.

Provides durable workflow execution via Temporal with:
- Automatic retries and backoff
- Signals for pause/resume/cancel
- Queries for status and artifacts
- State persistence that survives restarts
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Check if temporalio is available
try:
    from temporalio.client import Client, WorkflowHandle
    from temporalio.common import WorkflowIDReusePolicy
    TEMPORAL_AVAILABLE = True
except ImportError:
    TEMPORAL_AVAILABLE = False
    Client = None
    WorkflowHandle = None
    WorkflowIDReusePolicy = None

from ..backend import (
    OrchestrationBackend,
    PhaseResult,
    WorkflowInfo,
    WorkflowPhase,
    WorkflowResult,
    WorkflowStatus,
)
from ..config import OrchestrationConfig
from ..state import WorkflowState, WorkflowStateStorage
from .client import TemporalClient
from .workflows import ITUVWorkflow, ITUVWorkflowInput


class TemporalBackend(OrchestrationBackend):
    """Temporal-based orchestration backend for durable ITUV workflows."""
    
    def __init__(
        self,
        config: OrchestrationConfig,
        storage_path: Path,
    ):
        """Initialize Temporal backend.
        
        Args:
            config: Orchestration configuration.
            storage_path: Path to SQLite database for local state tracking.
        """
        if not TEMPORAL_AVAILABLE:
            raise ImportError(
                "temporalio package not installed. "
                "Install with: pip install temporalio"
            )
        
        self.config = config
        self.storage = WorkflowStateStorage(storage_path)
        
        # Temporal client (lazy initialization)
        self._temporal_client: Optional[TemporalClient] = None
        self._client: Optional[Client] = None
        
        logger.info("TemporalBackend initialized")
    
    async def _get_client(self) -> Client:
        """Get or create Temporal client."""
        if self._client is None:
            self._temporal_client = TemporalClient(
                address=self.config.temporal.address,
                namespace=self.config.temporal.namespace,
                auto_start=self.config.temporal.auto_start,
            )
            self._client = await self._temporal_client.connect()
        return self._client
    
    async def start_workflow(
        self,
        task_id: str,
        blueprint_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Start an ITUV workflow for a task."""
        client = await self._get_client()
        
        workflow_id = f"ituv-{task_id}-{uuid.uuid4().hex[:8]}"
        now = datetime.utcnow()
        
        # Merge config with defaults
        workflow_config = {
            "phase_timeouts": self.config.phase_timeouts,
            "max_retries": self.config.temporal.max_retries,
            "initial_interval_sec": self.config.temporal.initial_interval_sec,
            "max_interval_sec": self.config.temporal.max_interval_sec,
            "backoff_coefficient": self.config.temporal.backoff_coefficient,
        }
        if config:
            workflow_config.update(config)
        
        # Create workflow input
        workflow_input = ITUVWorkflowInput(
            task_id=task_id,
            blueprint_id=blueprint_id,
            config=workflow_config,
        )
        
        # Start workflow
        handle = await client.start_workflow(
            ITUVWorkflow.run,
            workflow_input,
            id=workflow_id,
            task_queue=self.config.temporal.task_queue,
            execution_timeout=timedelta(seconds=self.config.temporal.workflow_execution_timeout),
            run_timeout=timedelta(seconds=self.config.temporal.workflow_run_timeout),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
        
        # Track locally
        state = WorkflowState(
            workflow_id=workflow_id,
            task_id=task_id,
            blueprint_id=blueprint_id,
            status=WorkflowStatus.RUNNING,
            phase=WorkflowPhase.IMPLEMENT,
            started_at=now,
            updated_at=now,
            config=workflow_config,
        )
        self.storage.save_state(state)
        
        logger.info(f"Started Temporal workflow {workflow_id} for task {task_id}")
        return workflow_id
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[WorkflowInfo]:
        """Get current status of a workflow."""
        # First check local state
        state = self.storage.get_state(workflow_id)
        if not state:
            return None
        
        # Try to get live status from Temporal
        try:
            client = await self._get_client()
            handle = client.get_workflow_handle(workflow_id)
            
            # Query workflow status
            status = await handle.query(ITUVWorkflow.get_status)
            
            # Update local state
            state.phase = WorkflowPhase(status["phase"])
            state.progress = status["progress"]
            
            if status["paused"]:
                state.status = WorkflowStatus.PAUSED
            elif status["cancelled"]:
                state.status = WorkflowStatus.CANCELLED
            elif status["phase"] == "completed":
                state.status = WorkflowStatus.COMPLETED
            elif status["phase"] == "failed":
                state.status = WorkflowStatus.FAILED
                state.error_message = status.get("error_message")
            else:
                state.status = WorkflowStatus.RUNNING
            
            state.updated_at = datetime.utcnow()
            self.storage.save_state(state)
        
        except Exception as e:
            logger.debug(f"Could not query Temporal workflow {workflow_id}: {e}")
        
        return state.to_info()
    
    async def get_workflow_result(self, workflow_id: str) -> Optional[WorkflowResult]:
        """Get the final result of a completed workflow."""
        state = self.storage.get_state(workflow_id)
        if not state:
            return None
        
        # Try to get result from Temporal
        try:
            client = await self._get_client()
            handle = client.get_workflow_handle(workflow_id)
            
            # Get workflow result (blocks until complete)
            result = await handle.result()
            
            # Update local state
            state.status = WorkflowStatus.COMPLETED if result.success else WorkflowStatus.FAILED
            state.phase = WorkflowPhase(result.phase.value)
            state.artifacts = result.artifacts
            state.error_message = result.error_message
            state.completed_at = datetime.utcnow()
            self.storage.save_state(state)
            
            # Calculate duration
            duration = 0.0
            if state.started_at and state.completed_at:
                duration = (state.completed_at - state.started_at).total_seconds()
            
            return WorkflowResult(
                workflow_id=workflow_id,
                task_id=state.task_id,
                status=state.status,
                phase_results=state.phase_results,
                total_duration_sec=duration,
                artifacts=result.artifacts,
                error_message=result.error_message,
            )
        
        except Exception as e:
            logger.error(f"Could not get Temporal workflow result {workflow_id}: {e}")
            return None
    
    async def signal_workflow(
        self,
        workflow_id: str,
        signal: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send a signal to a running workflow."""
        try:
            client = await self._get_client()
            handle = client.get_workflow_handle(workflow_id)
            
            if signal == "pause":
                await handle.signal(ITUVWorkflow.pause)
            elif signal == "resume":
                await handle.signal(ITUVWorkflow.resume)
            elif signal == "cancel":
                await handle.signal(ITUVWorkflow.cancel)
            elif signal == "inject_feedback":
                await handle.signal(ITUVWorkflow.inject_feedback, payload or {})
            else:
                logger.warning(f"Unknown signal: {signal}")
                return False
            
            logger.info(f"Sent signal '{signal}' to workflow {workflow_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to signal workflow {workflow_id}: {e}")
            return False
    
    async def query_workflow(
        self,
        workflow_id: str,
        query: str,
    ) -> Optional[Any]:
        """Query a running workflow for information."""
        try:
            client = await self._get_client()
            handle = client.get_workflow_handle(workflow_id)
            
            if query == "status":
                return await handle.query(ITUVWorkflow.get_status)
            elif query == "progress":
                return await handle.query(ITUVWorkflow.get_progress)
            elif query == "artifacts":
                return await handle.query(ITUVWorkflow.get_artifacts)
            elif query == "phase_results":
                return await handle.query(ITUVWorkflow.get_phase_results)
            else:
                logger.warning(f"Unknown query: {query}")
                return None
        
        except Exception as e:
            logger.error(f"Failed to query workflow {workflow_id}: {e}")
            return None
    
    async def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a running workflow."""
        try:
            client = await self._get_client()
            handle = client.get_workflow_handle(workflow_id)
            
            # Send cancel signal first for graceful shutdown
            await handle.signal(ITUVWorkflow.cancel)
            
            # Also cancel via Temporal
            await handle.cancel()
            
            # Update local state
            state = self.storage.get_state(workflow_id)
            if state:
                state.status = WorkflowStatus.CANCELLED
                state.completed_at = datetime.utcnow()
                self.storage.save_state(state)
            
            logger.info(f"Cancelled workflow {workflow_id}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to cancel workflow {workflow_id}: {e}")
            return False
    
    async def list_workflows(
        self,
        project_id: Optional[str] = None,
        status_filter: Optional[List[WorkflowStatus]] = None,
        limit: int = 100,
    ) -> List[WorkflowInfo]:
        """List workflows with optional filtering."""
        # Use local storage for listing
        states = self.storage.list_states(project_id, status_filter, limit)
        return [s.to_info() for s in states]
    
    async def cleanup_completed(
        self,
        older_than_days: int = 30,
    ) -> int:
        """Clean up old completed workflows."""
        return self.storage.cleanup_old(older_than_days)

