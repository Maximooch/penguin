"""
Tests for PenguinClient API client functionality.

This module tests the high-level PenguinClient API including:
- Client initialization and lifecycle
- Chat and conversation methods
- Checkpoint management
- Model management  
- Task execution
- System diagnostics
- File and context management
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import AsyncGenerator

from penguin.api_client import (
    PenguinClient, 
    ChatOptions, 
    TaskOptions, 
    CheckpointInfo, 
    ModelInfo,
    create_client
)
from penguin.core import PenguinCore


@pytest.fixture
def mock_core():
    """Fixture to create a mock PenguinCore for testing."""
    core = AsyncMock(spec=PenguinCore)
    
    # Mock chat methods
    core.process_message = AsyncMock(return_value="Test response from AI")
    core.process = AsyncMock(return_value={"assistant_response": "Processed response", "action_results": []})
    
    # Mock conversation methods
    core.list_conversations = MagicMock(return_value=[
        {"id": "conv_1", "name": "Test Conversation", "created_at": "2024-01-01T10:00:00Z"}
    ])
    core.get_conversation = MagicMock(return_value={"id": "conv_1", "messages": []})
    core.create_conversation = MagicMock(return_value="conv_new")
    
    # Mock checkpoint methods
    core.create_checkpoint = AsyncMock(return_value="ckpt_123")
    core.rollback_to_checkpoint = AsyncMock(return_value=True)
    core.branch_from_checkpoint = AsyncMock(return_value="branch_456")
    core.list_checkpoints = MagicMock(return_value=[
        {
            "id": "ckpt_123",
            "name": "Test checkpoint",
            "description": "Test description",
            "created_at": "2024-01-01T10:00:00Z",
            "type": "manual",
            "session_id": "session_123"
        }
    ])
    core.cleanup_old_checkpoints = AsyncMock(return_value=5)
    
    # Mock model methods
    core.list_available_models = MagicMock(return_value=[
        {
            "id": "claude-3-sonnet",
            "name": "anthropic/claude-3-sonnet-20240229",
            "provider": "anthropic",
            "vision_enabled": True,
            "max_tokens": 4000,
            "current": True
        },
        {
            "id": "gpt-4",
            "name": "openai/gpt-4",
            "provider": "openai", 
            "vision_enabled": False,
            "max_tokens": 8000,
            "current": False
        }
    ])
    core.load_model = AsyncMock(return_value=True)
    core.get_current_model = MagicMock(return_value={
        "model": "anthropic/claude-3-sonnet-20240229",
        "provider": "anthropic",
        "vision_enabled": True,
        "max_tokens": 4000
    })
    
    # Mock system methods
    core.get_system_info = MagicMock(return_value={
        "penguin_version": "0.3.1",
        "engine_available": True,
        "checkpoints_enabled": True
    })
    core.get_system_status = MagicMock(return_value={
        "status": "active",
        "timestamp": "2024-01-01T12:00:00Z"
    })
    core.get_token_usage = MagicMock(return_value={
        "total": {"input": 1000, "output": 500}
    })
    core.get_checkpoint_stats = MagicMock(return_value={
        "total_checkpoints": 10,
        "enabled": True
    })
    
    # Mock task execution
    core.engine = MagicMock()
    core.engine.run_task = AsyncMock(return_value={
        "status": "completed",
        "response": "Task completed successfully",
        "execution_time": 30.5,
        "action_results": []
    })
    
    # Mock file methods
    core.list_context_files = MagicMock(return_value=["file1.py", "file2.md"])
    
    # Mock conversation manager for file operations
    core.conversation_manager = MagicMock()
    core.conversation_manager.load_context_file = MagicMock()
    
    return core


@pytest.fixture(scope="function")
def client(mock_core, event_loop):
    """Fixture to create an initialized PenguinClient for testing."""
    client = PenguinClient()
    
    # Mock the core creation and initialize synchronously
    with patch('penguin.api_client.PenguinCore.create', return_value=mock_core):
        event_loop.run_until_complete(client.initialize())
    
    return client


class TestPenguinClientInitialization:
    """Test suite for PenguinClient initialization and lifecycle."""
    
    def test_client_creation(self):
        """Test basic client creation."""
        client = PenguinClient()
        
        assert client.config_path is None
        assert client.model is None
        assert client.provider is None
        assert client.workspace_path is None
        assert client._core is None
        assert client._initialized is False
    
    def test_client_creation_with_parameters(self):
        """Test client creation with custom parameters."""
        client = PenguinClient(
            model="gpt-4",
            provider="openai",
            workspace_path="/custom/workspace"
        )
        
        assert client.model == "gpt-4"
        assert client.provider == "openai"
        assert client.workspace_path == "/custom/workspace"
    
    @pytest.mark.asyncio
    async def test_client_initialization_success(self, mock_core):
        """Test successful client initialization."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=mock_core):
            await client.initialize()
        
        assert client._initialized is True
        assert client._core is mock_core
    
    @pytest.mark.asyncio
    async def test_client_initialization_failure(self):
        """Test client initialization failure handling."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', side_effect=Exception("Init failed")):
            with pytest.raises(RuntimeError, match="Penguin client initialization failed"):
                await client.initialize()
        
        assert client._initialized is False
        assert client._core is None
    
    @pytest.mark.asyncio
    async def test_client_double_initialization(self, mock_core):
        """Test that double initialization is handled gracefully."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=mock_core) as mock_create:
            await client.initialize()
            await client.initialize()  # Second call
        
        # Should only call create once
        mock_create.assert_called_once()
    
    def test_core_property_not_initialized(self):
        """Test accessing core property before initialization."""
        client = PenguinClient()
        
        with pytest.raises(RuntimeError, match="Client not initialized"):
            _ = client.core
    
    @pytest.mark.asyncio
    async def test_client_close(self, client):
        """Test client cleanup."""
        # Mock cleanup method
        cleanup_mock = AsyncMock()
        client._core.cleanup = cleanup_mock
        
        await client.close()
        
        cleanup_mock.assert_called_once()
        assert client._initialized is False
        assert client._core is None
    
    @pytest.mark.asyncio
    async def test_context_manager(self, mock_core):
        """Test client as async context manager."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=mock_core):
            async with client as ctx_client:
                assert ctx_client._initialized is True
                assert ctx_client._core is mock_core
            
            # Should be cleaned up after context
            assert client._initialized is False
            assert client._core is None


class TestPenguinClientChatMethods:
    """Test suite for PenguinClient chat and conversation methods."""
    
    @pytest.mark.asyncio
    async def test_basic_chat(self, client):
        """Test basic chat functionality."""
        response = await client.chat("Hello, how are you?")
        
        assert response == "Test response from AI"
        client._core.process_message.assert_called_once_with(
            message="Hello, how are you?",
            context=None,
            conversation_id=None,
            context_files=None,
            streaming=False
        )
    
    @pytest.mark.asyncio
    async def test_chat_with_options(self, client):
        """Test chat with full options."""
        options = ChatOptions(
            conversation_id="conv_123",
            context={"project": "test"},
            context_files=["file1.py"],
            streaming=True,
            image_path="/path/to/image.png"
        )
        
        response = await client.chat("Analyze this code", options)
        
        client._core.process_message.assert_called_once_with(
            message="Analyze this code",
            context={"project": "test"},
            conversation_id="conv_123",
            context_files=["file1.py"],
            streaming=True
        )
    
    @pytest.mark.asyncio
    async def test_stream_chat(self, client):
        """Test streaming chat functionality."""
        # Mock the streaming process
        async def mock_process(*args, **kwargs):
            return {"assistant_response": "Streamed response"}
        
        client._core.process = AsyncMock(side_effect=mock_process)
        
        # Mock the queue and callback behavior
        tokens = ["Hello", " ", "world", "!"]
        
        async def mock_stream_callback(callback):
            for token in tokens:
                await callback(token)
        
        # Patch the streaming logic
        with patch.object(client, 'stream_chat') as mock_stream:
            async def stream_generator():
                for token in tokens:
                    yield token
            
            mock_stream.return_value = stream_generator()
            
            collected_tokens = []
            async for token in client.stream_chat("Test message"):
                collected_tokens.append(token)
            
            assert collected_tokens == tokens
    
    @pytest.mark.asyncio
    async def test_list_conversations(self, client):
        """Test listing conversations."""
        conversations = await client.list_conversations()
        
        assert len(conversations) == 1
        assert conversations[0]["id"] == "conv_1"
        client._core.list_conversations.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_conversation(self, client):
        """Test getting specific conversation."""
        conversation = await client.get_conversation("conv_1")
        
        assert conversation["id"] == "conv_1"
        client._core.get_conversation.assert_called_once_with("conv_1")
    
    @pytest.mark.asyncio
    async def test_create_conversation(self, client):
        """Test creating new conversation."""
        conv_id = await client.create_conversation()
        
        assert conv_id == "conv_new"
        client._core.create_conversation.assert_called_once()


class TestPenguinClientCheckpointMethods:
    """Test suite for PenguinClient checkpoint management methods."""
    
    @pytest.mark.asyncio
    async def test_create_checkpoint_basic(self, client):
        """Test basic checkpoint creation."""
        checkpoint_id = await client.create_checkpoint()
        
        assert checkpoint_id == "ckpt_123"
        client._core.create_checkpoint.assert_called_once_with(name=None, description=None)
    
    @pytest.mark.asyncio
    async def test_create_checkpoint_with_details(self, client):
        """Test checkpoint creation with name and description."""
        checkpoint_id = await client.create_checkpoint(
            name="Test checkpoint",
            description="Before refactoring"
        )
        
        assert checkpoint_id == "ckpt_123"
        client._core.create_checkpoint.assert_called_once_with(
            name="Test checkpoint",
            description="Before refactoring"
        )
    
    @pytest.mark.asyncio
    async def test_rollback_to_checkpoint(self, client):
        """Test checkpoint rollback."""
        success = await client.rollback_to_checkpoint("ckpt_123")
        
        assert success is True
        client._core.rollback_to_checkpoint.assert_called_once_with("ckpt_123")
    
    @pytest.mark.asyncio
    async def test_branch_from_checkpoint(self, client):
        """Test checkpoint branching."""
        branch_id = await client.branch_from_checkpoint(
            "ckpt_123",
            name="Experiment",
            description="Testing new approach"
        )
        
        assert branch_id == "branch_456"
        client._core.branch_from_checkpoint.assert_called_once_with(
            "ckpt_123",
            name="Experiment",
            description="Testing new approach"
        )
    
    @pytest.mark.asyncio
    async def test_list_checkpoints(self, client):
        """Test listing checkpoints."""
        checkpoints = await client.list_checkpoints(limit=20)
        
        assert len(checkpoints) == 1
        assert isinstance(checkpoints[0], CheckpointInfo)
        assert checkpoints[0].id == "ckpt_123"
        assert checkpoints[0].name == "Test checkpoint"
        assert checkpoints[0].type == "manual"
        
        client._core.list_checkpoints.assert_called_once_with(session_id=None, limit=20)
    
    @pytest.mark.asyncio
    async def test_cleanup_checkpoints(self, client):
        """Test checkpoint cleanup."""
        cleaned_count = await client.cleanup_checkpoints()
        
        assert cleaned_count == 5
        client._core.cleanup_old_checkpoints.assert_called_once()


class TestPenguinClientModelMethods:
    """Test suite for PenguinClient model management methods."""
    
    @pytest.mark.asyncio
    async def test_list_models(self, client):
        """Test listing available models."""
        models = await client.list_models()
        
        assert len(models) == 2
        assert isinstance(models[0], ModelInfo)
        assert models[0].id == "claude-3-sonnet"
        assert models[0].name == "anthropic/claude-3-sonnet-20240229"
        assert models[0].provider == "anthropic"
        assert models[0].vision_enabled is True
        assert models[0].current is True
        
        assert models[1].id == "gpt-4"
        assert models[1].current is False
    
    @pytest.mark.asyncio
    async def test_switch_model(self, client):
        """Test switching to different model."""
        success = await client.switch_model("gpt-4")
        
        assert success is True
        client._core.load_model.assert_called_once_with("gpt-4")
    
    @pytest.mark.asyncio
    async def test_get_current_model(self, client):
        """Test getting current model information."""
        current_model = await client.get_current_model()
        
        assert isinstance(current_model, ModelInfo)
        assert current_model.id == "anthropic/claude-3-sonnet-20240229"
        assert current_model.name == "anthropic/claude-3-sonnet-20240229"
        assert current_model.provider == "anthropic"
        assert current_model.vision_enabled is True
        assert current_model.current is True
    
    @pytest.mark.asyncio
    async def test_get_current_model_none(self, client):
        """Test getting current model when none is loaded."""
        client._core.get_current_model.return_value = None
        
        current_model = await client.get_current_model()
        
        assert current_model is None


class TestPenguinClientTaskMethods:
    """Test suite for PenguinClient task execution methods."""
    
    @pytest.mark.asyncio
    async def test_execute_task_basic(self, client):
        """Test basic task execution."""
        result = await client.execute_task("Create a web server")
        
        assert result["status"] == "completed"
        assert result["response"] == "Task completed successfully"
        assert result["execution_time"] == 30.5
        
        client._core.engine.run_task.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_execute_task_with_options(self, client):
        """Test task execution with options."""
        options = TaskOptions(
            name="Web Server Task",
            description="Create a FastAPI web server",
            continuous=False,
            time_limit=300,
            context={"framework": "fastapi"}
        )
        
        result = await client.execute_task("Create a web server", options)
        
        assert result["status"] == "completed"
        client._core.engine.run_task.assert_called_once_with(
            task_prompt="Create a web server",
            max_iterations=10,
            task_name="Web Server Task",
            task_context={"framework": "fastapi"},
            enable_events=True
        )
    
    @pytest.mark.asyncio
    async def test_execute_task_no_engine(self, client):
        """Test task execution fallback when no engine available."""
        client._core.engine = None
        client._core.process = AsyncMock(return_value={
            "assistant_response": "Fallback response",
            "action_results": []
        })
        
        result = await client.execute_task("Create a function")
        
        assert result["assistant_response"] == "Fallback response"
        client._core.process.assert_called_once_with(
            input_data={"text": "Create a function"},
            context=None,
            max_iterations=10
        )
    
    @pytest.mark.asyncio
    async def test_start_run_mode(self, client):
        """Test starting run mode."""
        client._core.start_run_mode = AsyncMock()
        
        options = TaskOptions(
            name="Continuous Task",
            description="Long running task",
            continuous=True,
            time_limit=600
        )
        
        await client.start_run_mode(options)
        
        client._core.start_run_mode.assert_called_once_with(
            name="Continuous Task",
            description="Long running task",
            context=None,
            continuous=True,
            time_limit=600,
            stream_event_callback=None
        )


class TestPenguinClientSystemMethods:
    """Test suite for PenguinClient system diagnostics methods."""
    
    @pytest.mark.asyncio
    async def test_get_system_info(self, client):
        """Test getting system information."""
        info = await client.get_system_info()
        
        assert info["penguin_version"] == "0.3.1"
        assert info["engine_available"] is True
        assert info["checkpoints_enabled"] is True
        client._core.get_system_info.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_system_status(self, client):
        """Test getting system status."""
        status = await client.get_system_status()
        
        assert status["status"] == "active"
        assert status["timestamp"] == "2024-01-01T12:00:00Z"
        client._core.get_system_status.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_token_usage(self, client):
        """Test getting token usage."""
        usage = await client.get_token_usage()
        
        assert usage["total"]["input"] == 1000
        assert usage["total"]["output"] == 500
        client._core.get_token_usage.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_checkpoint_stats(self, client):
        """Test getting checkpoint statistics."""
        stats = await client.get_checkpoint_stats()
        
        assert stats["total_checkpoints"] == 10
        assert stats["enabled"] is True
        client._core.get_checkpoint_stats.assert_called_once()


class TestPenguinClientFileMethods:
    """Test suite for PenguinClient file and context methods."""
    
    @pytest.mark.asyncio
    async def test_load_context_files(self, client):
        """Test loading context files."""
        client._core.conversation_manager.load_context_file = MagicMock()
        
        success = await client.load_context_files(["file1.py", "file2.md"])
        
        assert success is True
        assert client._core.conversation_manager.load_context_file.call_count == 2
    
    @pytest.mark.asyncio
    async def test_load_context_files_error(self, client):
        """Test loading context files with error."""
        client._core.conversation_manager.load_context_file = MagicMock(side_effect=Exception("File error"))
        
        success = await client.load_context_files(["file1.py"])
        
        assert success is False
    
    @pytest.mark.asyncio
    async def test_list_context_files(self, client):
        """Test listing context files."""
        files = await client.list_context_files()
        
        assert files == ["file1.py", "file2.md"]
        client._core.list_context_files.assert_called_once()


class TestCreateClientFunction:
    """Test suite for the create_client convenience function."""
    
    @pytest.mark.asyncio
    async def test_create_client_basic(self, mock_core):
        """Test basic create_client function."""
        with patch('penguin.api_client.PenguinCore.create', return_value=mock_core):
            client = await create_client()
        
        assert isinstance(client, PenguinClient)
        assert client._initialized is True
        assert client._core is mock_core
    
    @pytest.mark.asyncio
    async def test_create_client_with_parameters(self, mock_core):
        """Test create_client with custom parameters."""
        with patch('penguin.api_client.PenguinCore.create', return_value=mock_core):
            client = await create_client(
                model="gpt-4",
                provider="openai",
                workspace_path="/custom/path"
            )
        
        assert client.model == "gpt-4"
        assert client.provider == "openai"
        assert client.workspace_path == "/custom/path"
        assert client._initialized is True


class TestPenguinClientIntegrationScenarios:
    """Integration test scenarios for PenguinClient workflows."""
    
    @pytest.mark.asyncio
    async def test_complete_workflow_scenario(self, client):
        """Test a complete client workflow scenario."""
        # Step 1: Get system info
        info = await client.get_system_info()
        assert info["penguin_version"] == "0.3.1"
        
        # Step 2: Create checkpoint
        checkpoint_id = await client.create_checkpoint("Before work")
        assert checkpoint_id == "ckpt_123"
        
        # Step 3: Chat interaction
        response = await client.chat("Help me with Python")
        assert response == "Test response from AI"
        
        # Step 4: Execute task
        task_result = await client.execute_task("Create a function")
        assert task_result["status"] == "completed"
        
        # Step 5: Switch model
        switch_success = await client.switch_model("gpt-4")
        assert switch_success is True
        
        # Step 6: Get updated system status
        status = await client.get_system_status()
        assert status["status"] == "active"
    
    @pytest.mark.asyncio
    async def test_checkpoint_experimentation_workflow(self, client):
        """Test checkpoint-based experimentation workflow."""
        # Create initial checkpoint
        initial_checkpoint = await client.create_checkpoint("Initial state")
        assert initial_checkpoint == "ckpt_123"
        
        # Do some work (simulate with chat)
        await client.chat("Implement feature A")
        
        # Create branch for alternative approach
        branch_id = await client.branch_from_checkpoint(
            initial_checkpoint,
            name="Alternative approach"
        )
        assert branch_id == "branch_456"
        
        # Try different approach
        await client.chat("Implement feature B instead")
        
        # List checkpoints to see what we have
        checkpoints = await client.list_checkpoints()
        assert len(checkpoints) == 1
        assert checkpoints[0].id == "ckpt_123"
        
        # Rollback if needed
        rollback_success = await client.rollback_to_checkpoint(initial_checkpoint)
        assert rollback_success is True
    
    @pytest.mark.asyncio
    async def test_model_comparison_workflow(self, client):
        """Test comparing responses from different models."""
        # Get initial model
        initial_model = await client.get_current_model()
        assert initial_model.current is True
        
        # List available models
        models = await client.list_models()
        assert len(models) == 2
        
        # Test with first model
        response1 = await client.chat("Explain Python classes")
        
        # Switch to second model
        await client.switch_model("gpt-4")
        
        # Test with second model
        response2 = await client.chat("Explain Python classes")
        
        # Both should return responses
        assert response1 == "Test response from AI"
        assert response2 == "Test response from AI"
    
    @pytest.mark.asyncio
    async def test_error_recovery_workflow(self, client):
        """Test error recovery scenarios."""
        # Test model switching failure
        client._core.load_model.return_value = False
        switch_success = await client.switch_model("invalid_model")
        assert switch_success is False
        
        # Test checkpoint rollback failure  
        client._core.rollback_to_checkpoint.return_value = False
        rollback_success = await client.rollback_to_checkpoint("invalid_checkpoint")
        assert rollback_success is False
        
        # System should still be functional for other operations
        info = await client.get_system_info()
        assert "penguin_version" in info