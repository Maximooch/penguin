"""
Tests for PenguinCore checkpoint management functionality.

This module tests the checkpoint management methods added to PenguinCore including:
- create_checkpoint()
- rollback_to_checkpoint()
- branch_from_checkpoint() 
- list_checkpoints()
- cleanup_old_checkpoints()
- get_checkpoint_stats()
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from penguin.core import PenguinCore
from penguin.system.checkpoint_manager import CheckpointType, CheckpointConfig


@pytest.fixture
def mock_conversation_manager():
    """Fixture to mock ConversationManager with checkpoint functionality."""
    manager = MagicMock()
    
    # Mock checkpoint manager
    checkpoint_manager = MagicMock()
    checkpoint_manager.config = CheckpointConfig(
        enabled=True,
        frequency=1,
        retention={"keep_all_hours": 24, "max_age_days": 30}
    )
    manager.checkpoint_manager = checkpoint_manager
    
    # Mock checkpoint methods (use the actual method names called by PenguinCore)
    manager.create_manual_checkpoint = AsyncMock(return_value="ckpt_123")
    manager.rollback_to_checkpoint = AsyncMock(return_value=True)
    manager.branch_from_checkpoint = AsyncMock(return_value="branch_456")
    manager.list_checkpoints = MagicMock(return_value=[
        {
            "id": "ckpt_123",
            "name": "Test checkpoint",
            "description": "Test description",
            "created_at": "2024-01-01T10:00:00Z",
            "type": "manual",
            "session_id": "session_123",
            "auto": False
        },
        {
            "id": "ckpt_124", 
            "name": None,
            "description": None,
            "created_at": "2024-01-01T11:00:00Z",
            "type": "auto",
            "session_id": "session_123",
            "auto": True
        }
    ])
    manager.cleanup_old_checkpoints = AsyncMock(return_value=5)
    
    # Mock session for checkpoint operations
    mock_session = MagicMock()
    mock_session.id = "session_123"
    manager.get_current_session = MagicMock(return_value=mock_session)
    
    return manager


@pytest.fixture
def mock_core(mock_conversation_manager):
    """Fixture to create a mock PenguinCore with checkpoint functionality."""
    core = MagicMock(spec=PenguinCore)
    core.conversation_manager = mock_conversation_manager
    core.initialized = True
    
    # Set up the actual methods we're testing
    core.create_checkpoint = PenguinCore.create_checkpoint.__get__(core)
    core.rollback_to_checkpoint = PenguinCore.rollback_to_checkpoint.__get__(core)
    core.branch_from_checkpoint = PenguinCore.branch_from_checkpoint.__get__(core)
    core.list_checkpoints = PenguinCore.list_checkpoints.__get__(core)
    core.cleanup_old_checkpoints = PenguinCore.cleanup_old_checkpoints.__get__(core)
    core.get_checkpoint_stats = PenguinCore.get_checkpoint_stats.__get__(core)
    
    return core


class TestPenguinCoreCheckpointManagement:
    """Test suite for PenguinCore checkpoint management methods."""
    
    @pytest.mark.asyncio
    async def test_create_checkpoint_basic(self, mock_core):
        """Test basic checkpoint creation."""
        result = await mock_core.create_checkpoint()
        
        assert result == "ckpt_123"
        mock_core.conversation_manager.create_manual_checkpoint.assert_called_once_with(
            name=None,
            description=None
        )
    
    @pytest.mark.asyncio
    async def test_create_checkpoint_with_details(self, mock_core):
        """Test checkpoint creation with name and description."""
        result = await mock_core.create_checkpoint(
            name="Before refactoring",
            description="Checkpoint before code changes"
        )
        
        assert result == "ckpt_123"
        mock_core.conversation_manager.create_manual_checkpoint.assert_called_once_with(
            name="Before refactoring",
            description="Checkpoint before code changes"
        )
    
    @pytest.mark.asyncio
    async def test_rollback_to_checkpoint_success(self, mock_core):
        """Test successful checkpoint rollback."""
        result = await mock_core.rollback_to_checkpoint("ckpt_123")
        
        assert result is True
        mock_core.conversation_manager.rollback_to_checkpoint.assert_called_once_with("ckpt_123")
    
    @pytest.mark.asyncio 
    async def test_rollback_to_checkpoint_failure(self, mock_core):
        """Test failed checkpoint rollback."""
        mock_core.conversation_manager.rollback_to_checkpoint.return_value = False
        
        result = await mock_core.rollback_to_checkpoint("invalid_checkpoint")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_branch_from_checkpoint_basic(self, mock_core):
        """Test basic checkpoint branching."""
        result = await mock_core.branch_from_checkpoint("ckpt_123")
        
        assert result == "branch_456"
        mock_core.conversation_manager.branch_from_checkpoint.assert_called_once_with(
            "ckpt_123",
            name=None,
            description=None
        )
    
    @pytest.mark.asyncio
    async def test_branch_from_checkpoint_with_details(self, mock_core):
        """Test checkpoint branching with name and description."""
        result = await mock_core.branch_from_checkpoint(
            "ckpt_123",
            name="Alternative approach",
            description="Exploring different solution"
        )
        
        assert result == "branch_456"
        mock_core.conversation_manager.branch_from_checkpoint.assert_called_once_with(
            "ckpt_123",
            name="Alternative approach",
            description="Exploring different solution"
        )
    
    def test_list_checkpoints_basic(self, mock_core):
        """Test basic checkpoint listing."""
        result = mock_core.list_checkpoints()
        
        assert len(result) == 2
        assert result[0]["id"] == "ckpt_123"
        assert result[0]["name"] == "Test checkpoint"
        assert result[1]["id"] == "ckpt_124"
        
        mock_core.conversation_manager.list_checkpoints.assert_called_once_with(
            session_id="session_123",
            limit=50
        )
    
    def test_list_checkpoints_with_filters(self, mock_core):
        """Test checkpoint listing with session filter and limit."""
        result = mock_core.list_checkpoints(session_id="session_456", limit=20)
        
        mock_core.conversation_manager.list_checkpoints.assert_called_once_with(
            session_id="session_456",
            limit=20
        )
    
    @pytest.mark.asyncio
    async def test_cleanup_old_checkpoints(self, mock_core):
        """Test checkpoint cleanup."""
        result = await mock_core.cleanup_old_checkpoints()
        
        assert result == 5
        mock_core.conversation_manager.cleanup_old_checkpoints.assert_called_once()
    
    def test_get_checkpoint_stats_enabled(self, mock_core):
        """Test checkpoint stats when checkpointing is enabled."""
        result = mock_core.get_checkpoint_stats()
        
        assert result["enabled"] is True
        assert result["total_checkpoints"] == 2
        assert result["auto_checkpoints"] == 1
        assert result["manual_checkpoints"] == 1
        assert result["branch_checkpoints"] == 0
        assert "config" in result
        assert result["config"]["frequency"] == 1
        assert result["config"]["retention_hours"] == 24
        assert result["config"]["max_age_days"] == 30
    
    def test_get_checkpoint_stats_disabled(self, mock_core):
        """Test checkpoint stats when checkpointing is disabled."""
        mock_core.conversation_manager.checkpoint_manager = None
        
        result = mock_core.get_checkpoint_stats()
        
        assert result["enabled"] is False
        assert result["total_checkpoints"] == 0
        assert result["auto_checkpoints"] == 0
        assert result["manual_checkpoints"] == 0
        assert result["branch_checkpoints"] == 0
    
    def test_get_checkpoint_stats_with_branch_checkpoints(self, mock_core):
        """Test checkpoint stats with branch checkpoints."""
        # Add a branch checkpoint to the mock data
        checkpoints = mock_core.conversation_manager.list_checkpoints.return_value
        checkpoints.append({
            "id": "ckpt_125",
            "name": "Branch point",
            "description": "Branch checkpoint",
            "created_at": "2024-01-01T12:00:00Z",
            "type": "branch",
            "session_id": "session_123",
            "auto": False
        })
        
        result = mock_core.get_checkpoint_stats()
        
        assert result["total_checkpoints"] == 3
        assert result["branch_checkpoints"] == 1
    
    @pytest.mark.asyncio
    async def test_create_checkpoint_error_handling(self, mock_core):
        """Test error handling in checkpoint creation."""
        mock_core.conversation_manager.create_manual_checkpoint.side_effect = Exception("Database error")
        
        with pytest.raises(Exception, match="Database error"):
            await mock_core.create_checkpoint()
    
    @pytest.mark.asyncio
    async def test_rollback_error_handling(self, mock_core):
        """Test error handling in checkpoint rollback."""
        mock_core.conversation_manager.rollback_to_checkpoint.side_effect = Exception("Rollback failed")
        
        with pytest.raises(Exception, match="Rollback failed"):
            await mock_core.rollback_to_checkpoint("ckpt_123")
    
    @pytest.mark.asyncio
    async def test_branch_error_handling(self, mock_core):
        """Test error handling in checkpoint branching."""
        mock_core.conversation_manager.branch_from_checkpoint.side_effect = Exception("Branch failed")
        
        with pytest.raises(Exception, match="Branch failed"):
            await mock_core.branch_from_checkpoint("ckpt_123")
    
    @pytest.mark.asyncio
    async def test_cleanup_error_handling(self, mock_core):
        """Test error handling in checkpoint cleanup."""
        mock_core.conversation_manager.cleanup_old_checkpoints.side_effect = Exception("Cleanup failed")
        
        with pytest.raises(Exception, match="Cleanup failed"):
            await mock_core.cleanup_old_checkpoints()


class TestCheckpointIntegration:
    """Integration tests for checkpoint workflow scenarios."""
    
    @pytest.mark.asyncio
    async def test_checkpoint_workflow_scenario(self, mock_core):
        """Test a complete checkpoint workflow scenario."""
        # Step 1: Create initial checkpoint
        checkpoint_id = await mock_core.create_checkpoint("Initial state")
        assert checkpoint_id == "ckpt_123"
        
        # Step 2: Get stats to verify checkpoint exists
        stats = mock_core.get_checkpoint_stats()
        assert stats["enabled"] is True
        assert stats["total_checkpoints"] == 2
        
        # Step 3: Create a branch for experimentation
        branch_id = await mock_core.branch_from_checkpoint(
            checkpoint_id,
            name="Experimental branch"
        )
        assert branch_id == "branch_456"
        
        # Step 4: List checkpoints to see all available
        checkpoints = mock_core.list_checkpoints()
        assert len(checkpoints) == 2
        
        # Step 5: Rollback to original checkpoint
        success = await mock_core.rollback_to_checkpoint(checkpoint_id)
        assert success is True
        
        # Step 6: Clean up old checkpoints
        cleaned = await mock_core.cleanup_old_checkpoints()
        assert cleaned == 5
    
    @pytest.mark.asyncio
    async def test_checkpoint_without_conversation_manager(self):
        """Test checkpoint methods when conversation manager is not available."""
        core = MagicMock(spec=PenguinCore)
        core.conversation_manager = None
        
        # Set up the actual methods
        core.create_checkpoint = PenguinCore.create_checkpoint.__get__(core)
        core.get_checkpoint_stats = PenguinCore.get_checkpoint_stats.__get__(core)
        
        # Should handle gracefully when no conversation manager
        with pytest.raises(AttributeError):
            await core.create_checkpoint()
        
        # Stats should return disabled state
        stats = core.get_checkpoint_stats()
        assert stats["enabled"] is False