"""Tests for the orchestration system (Phase 2).

Run with: pytest tests/test_orchestration.py -v
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip all tests if orchestration not available
pytest.importorskip("penguin.orchestration")


class TestOrchestrationConfig:
    """Test orchestration configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        from penguin.orchestration.config import OrchestrationConfig
        
        config = OrchestrationConfig()
        assert config.backend == "native"
        assert config.phase_timeouts["implement"] == 600
        assert config.temporal.address == "localhost:7233"
    
    def test_config_from_dict(self):
        """Test creating config from dictionary."""
        from penguin.orchestration.config import OrchestrationConfig
        
        data = {
            "backend": "temporal",
            "temporal": {
                "address": "temporal.example.com:7233",
                "namespace": "test",
            },
            "phase_timeouts": {
                "implement": 1200,
                "test": 600,
            },
        }
        
        config = OrchestrationConfig.from_dict(data)
        assert config.backend == "temporal"
        assert config.temporal.address == "temporal.example.com:7233"
        assert config.temporal.namespace == "test"
        assert config.phase_timeouts["implement"] == 1200
    
    def test_config_to_dict(self):
        """Test serializing config to dictionary."""
        from penguin.orchestration.config import OrchestrationConfig
        
        config = OrchestrationConfig()
        data = config.to_dict()
        
        assert data["backend"] == "native"
        assert "temporal" in data
        assert "phase_timeouts" in data


class TestWorkflowState:
    """Test workflow state management."""
    
    def test_workflow_state_creation(self):
        """Test creating workflow state."""
        from penguin.orchestration.state import WorkflowState
        from penguin.orchestration.backend import WorkflowStatus, WorkflowPhase
        
        state = WorkflowState(
            workflow_id="wf-123",
            task_id="task-456",
            blueprint_id="bp-789",
        )
        
        assert state.workflow_id == "wf-123"
        assert state.task_id == "task-456"
        assert state.status == WorkflowStatus.PENDING
        assert state.phase == WorkflowPhase.PENDING
    
    def test_workflow_state_serialization(self):
        """Test serializing/deserializing workflow state."""
        from penguin.orchestration.state import WorkflowState
        from penguin.orchestration.backend import WorkflowStatus, WorkflowPhase
        
        state = WorkflowState(
            workflow_id="wf-123",
            task_id="task-456",
            status=WorkflowStatus.RUNNING,
            phase=WorkflowPhase.IMPLEMENT,
        )
        
        data = state.to_dict()
        restored = WorkflowState.from_dict(data)
        
        assert restored.workflow_id == state.workflow_id
        assert restored.status == state.status
        assert restored.phase == state.phase


class TestWorkflowStateStorage:
    """Test workflow state persistence."""
    
    @pytest.fixture
    def storage(self):
        """Create temporary storage."""
        from penguin.orchestration.state import WorkflowStateStorage
        
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_workflow.db"
            storage = WorkflowStateStorage(db_path)
            yield storage
    
    def test_save_and_load_state(self, storage):
        """Test saving and loading workflow state."""
        from penguin.orchestration.state import WorkflowState
        
        state = WorkflowState(
            workflow_id="wf-test-1",
            task_id="task-1",
        )
        
        storage.save_state(state)
        loaded = storage.get_state("wf-test-1")
        
        assert loaded is not None
        assert loaded.workflow_id == "wf-test-1"
        assert loaded.task_id == "task-1"
    
    def test_list_states(self, storage):
        """Test listing workflow states."""
        from penguin.orchestration.state import WorkflowState
        from penguin.orchestration.backend import WorkflowStatus
        
        # Create multiple states
        for i in range(5):
            state = WorkflowState(
                workflow_id=f"wf-{i}",
                task_id=f"task-{i}",
                status=WorkflowStatus.RUNNING if i % 2 == 0 else WorkflowStatus.COMPLETED,
            )
            storage.save_state(state)
        
        # List all
        all_states = storage.list_states()
        assert len(all_states) == 5
        
        # Filter by status
        running = storage.list_states(status_filter=WorkflowStatus.RUNNING)
        assert len(running) == 3


class TestNativeBackend:
    """Test native orchestration backend."""
    
    @pytest.fixture
    def backend(self):
        """Create native backend with temp storage."""
        from penguin.orchestration.config import OrchestrationConfig
        from penguin.orchestration.native import NativeBackend
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = OrchestrationConfig()
            db_path = Path(tmpdir) / "test.db"
            backend = NativeBackend(config, db_path)
            yield backend
    
    @pytest.mark.asyncio
    async def test_start_workflow(self, backend):
        """Test starting a workflow."""
        workflow_id = await backend.start_workflow(
            task_id="task-123",
            blueprint_id="bp-456",
        )
        
        assert workflow_id is not None
        assert workflow_id.startswith("ituv-task-123-")
    
    @pytest.mark.asyncio
    async def test_get_workflow_status(self, backend):
        """Test getting workflow status."""
        from penguin.orchestration.backend import WorkflowStatus
        
        workflow_id = await backend.start_workflow(task_id="task-status")
        
        # Let it start
        await asyncio.sleep(0.1)
        
        info = await backend.get_workflow_status(workflow_id)
        
        assert info is not None
        assert info.workflow_id == workflow_id
        assert info.task_id == "task-status"
    
    @pytest.mark.asyncio
    async def test_pause_resume_workflow(self, backend):
        """Test pausing and resuming a workflow."""
        from penguin.orchestration.backend import WorkflowStatus
        
        workflow_id = await backend.start_workflow(task_id="task-pause")
        await asyncio.sleep(0.1)
        
        # Pause
        success = await backend.pause_workflow(workflow_id)
        assert success
        
        info = await backend.get_workflow_status(workflow_id)
        assert info.status == WorkflowStatus.PAUSED
        
        # Resume
        success = await backend.resume_workflow(workflow_id)
        assert success
        
        info = await backend.get_workflow_status(workflow_id)
        assert info.status == WorkflowStatus.RUNNING
    
    @pytest.mark.asyncio
    async def test_cancel_workflow(self, backend):
        """Test cancelling a workflow."""
        from penguin.orchestration.backend import WorkflowStatus
        
        workflow_id = await backend.start_workflow(task_id="task-cancel")
        await asyncio.sleep(0.1)
        
        success = await backend.cancel_workflow(workflow_id)
        assert success
        
        info = await backend.get_workflow_status(workflow_id)
        assert info.status == WorkflowStatus.CANCELLED
    
    @pytest.mark.asyncio
    async def test_list_workflows(self, backend):
        """Test listing workflows."""
        # Create multiple workflows
        for i in range(3):
            await backend.start_workflow(task_id=f"task-list-{i}")
        
        await asyncio.sleep(0.1)
        
        workflows = await backend.list_workflows()
        assert len(workflows) == 3


class TestBackendFactory:
    """Test backend factory function."""
    
    def test_get_native_backend(self):
        """Test getting native backend."""
        from penguin.orchestration import get_backend
        from penguin.orchestration.config import OrchestrationConfig, reset_backend, set_config
        from penguin.orchestration.native import NativeBackend
        
        # Reset global state
        reset_backend()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            config = OrchestrationConfig(backend="native")
            set_config(config)
            
            backend = get_backend(workspace_path=Path(tmpdir))
            
            assert isinstance(backend, NativeBackend)
            
            # Reset for other tests
            reset_backend()
    
    def test_temporal_fallback_to_native(self):
        """Test falling back to native when Temporal unavailable."""
        from penguin.orchestration import get_backend
        from penguin.orchestration.config import OrchestrationConfig, reset_backend, set_config
        from penguin.orchestration.native import NativeBackend
        
        reset_backend()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Request Temporal but it should fall back
            config = OrchestrationConfig(backend="temporal")
            set_config(config)
            
            # This should fall back to native if temporalio not installed
            backend = get_backend(workspace_path=Path(tmpdir))
            
            # Either Temporal or Native is fine
            assert backend is not None
            
            reset_backend()


class TestWorkflowInfo:
    """Test WorkflowInfo data class."""
    
    def test_workflow_info_to_dict(self):
        """Test serializing WorkflowInfo."""
        from penguin.orchestration.backend import WorkflowInfo, WorkflowStatus, WorkflowPhase
        from datetime import datetime
        
        info = WorkflowInfo(
            workflow_id="wf-123",
            task_id="task-456",
            blueprint_id="bp-789",
            status=WorkflowStatus.RUNNING,
            phase=WorkflowPhase.IMPLEMENT,
            started_at=datetime.now(),
        )
        
        data = info.to_dict()
        
        assert data["workflow_id"] == "wf-123"
        assert data["status"] == "running"
        assert data["phase"] == "implement"


# Integration test placeholder for Temporal
class TestTemporalBackend:
    """Test Temporal backend (requires Temporal server)."""
    
    @pytest.mark.skip(reason="Requires running Temporal server")
    @pytest.mark.asyncio
    async def test_temporal_workflow(self):
        """Test workflow execution via Temporal."""
        # This test requires a running Temporal server
        # Run with: temporal server start-dev
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

