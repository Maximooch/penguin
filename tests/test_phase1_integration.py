"""
Integration tests for Phase 1 API updates.

This module provides comprehensive integration tests that verify the complete
functionality of Phase 1 updates, including:
- End-to-end workflows using PenguinClient
- Integration between PenguinCore and PenguinClient
- Real-world usage scenarios
- Cross-component functionality
- Error handling and recovery
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any, List

from penguin.api_client import PenguinClient, ChatOptions, TaskOptions, create_client
from penguin.core import PenguinCore


@pytest.fixture
def mock_checkpoint_manager():
    """Mock checkpoint manager with realistic behavior."""
    manager = MagicMock()
    
    # Store checkpoints in memory for realistic behavior
    checkpoints = {}
    
    async def create_checkpoint(name=None, description=None):
        checkpoint_id = f"ckpt_{len(checkpoints) + 1}"
        checkpoints[checkpoint_id] = {
            "id": checkpoint_id,
            "name": name,
            "description": description,
            "created_at": "2024-01-01T10:00:00Z",
            "type": "manual",
            "session_id": "session_123"
        }
        return checkpoint_id
    
    async def rollback_to_checkpoint(checkpoint_id):
        return checkpoint_id in checkpoints
    
    async def branch_from_checkpoint(checkpoint_id, name=None, description=None):
        if checkpoint_id in checkpoints:
            branch_id = f"branch_{len(checkpoints) + 1}"
            checkpoints[branch_id] = {
                "id": branch_id,
                "name": name,
                "description": description,
                "created_at": "2024-01-01T10:30:00Z",
                "type": "branch",
                "session_id": "session_456"
            }
            return branch_id
        return None
    
    def list_checkpoints(session_id=None, limit=50):
        checkpoint_list = list(checkpoints.values())
        if session_id:
            checkpoint_list = [cp for cp in checkpoint_list if cp["session_id"] == session_id]
        return checkpoint_list[:limit]
    
    async def cleanup_old_checkpoints():
        # Simulate cleaning up old checkpoints
        return min(2, len(checkpoints))
    
    manager.create_checkpoint = create_checkpoint
    manager.rollback_to_checkpoint = rollback_to_checkpoint
    manager.branch_from_checkpoint = branch_from_checkpoint
    manager.list_checkpoints = list_checkpoints
    manager.cleanup_old_checkpoints = cleanup_old_checkpoints
    
    return manager


@pytest.fixture
def mock_model_manager():
    """Mock model manager with realistic behavior."""
    manager = MagicMock()
    
    current_model = "anthropic/claude-3-sonnet-20240229"
    available_models = {
        "claude-3-sonnet": {
            "id": "claude-3-sonnet",
            "name": "anthropic/claude-3-sonnet-20240229",
            "provider": "anthropic",
            "vision_enabled": True,
            "max_tokens": 4000,
            "current": True
        },
        "gpt-4": {
            "id": "gpt-4",
            "name": "openai/gpt-4",
            "provider": "openai",
            "vision_enabled": False,
            "max_tokens": 8000,
            "current": False
        },
        "gpt-4-vision": {
            "id": "gpt-4-vision",
            "name": "openai/gpt-4-vision-preview",
            "provider": "openai",
            "vision_enabled": True,
            "max_tokens": 4000,
            "current": False
        }
    }
    
    async def load_model(model_id):
        nonlocal current_model
        if model_id in available_models:
            # Update current model
            for model in available_models.values():
                model["current"] = False
            available_models[model_id]["current"] = True
            current_model = available_models[model_id]["name"]
            return True
        return False
    
    def list_available_models():
        models = list(available_models.values())
        # Sort so current model is first
        models.sort(key=lambda m: not m["current"])
        return models
    
    def get_current_model():
        current = next((m for m in available_models.values() if m["current"]), None)
        if current:
            return {
                "model": current["name"],
                "provider": current["provider"],
                "client_preference": "native",
                "max_tokens": current["max_tokens"],
                "temperature": 0.7,
                "streaming_enabled": True,
                "vision_enabled": current["vision_enabled"],
                "api_base": None
            }
        return None
    
    manager.load_model = load_model
    manager.list_available_models = list_available_models
    manager.get_current_model = get_current_model
    
    return manager


@pytest.fixture(scope="function")
def integrated_core(mock_checkpoint_manager, mock_model_manager):
    """Create a more integrated mock core with realistic cross-component behavior."""
    core = AsyncMock(spec=PenguinCore)
    
    # System state with proper state tracking
    system_state = {
        "initialized": True,
        "engine_available": True,
        "streaming_active": False,
        "continuous_mode": False,
        "token_usage": {"total": {"input": 0, "output": 0}, "session": {"input": 0, "output": 0}},
        "call_count": 0  # Track number of calls for proper state increment
    }
    
    # Chat functionality
    conversation_history = []
    
    async def process_message(message, context=None, conversation_id=None, context_files=None, streaming=False):
        # Simulate token usage with proper increment tracking
        system_state["call_count"] += 1
        message_tokens = len(message.split())
        system_state["token_usage"]["total"]["input"] += message_tokens
        system_state["token_usage"]["total"]["output"] += 10
        system_state["token_usage"]["session"]["input"] += message_tokens
        system_state["token_usage"]["session"]["output"] += 10
        
        # Store conversation
        conversation_history.append({
            "role": "user",
            "content": message,
            "conversation_id": conversation_id,
            "context": context,
            "context_files": context_files
        })
        
        response = f"AI response to: {message[:50]}..."
        conversation_history.append({
            "role": "assistant", 
            "content": response,
            "conversation_id": conversation_id
        })
        
        return response
    
    # Task execution
    async def execute_task_via_engine(task_prompt, **kwargs):
        # Simulate token usage for task execution too
        system_state["call_count"] += 1
        task_tokens = len(task_prompt.split())
        system_state["token_usage"]["total"]["input"] += task_tokens
        system_state["token_usage"]["total"]["output"] += 15  # Tasks generate more output
        system_state["token_usage"]["session"]["input"] += task_tokens
        system_state["token_usage"]["session"]["output"] += 15
        
        return {
            "status": "completed",
            "response": f"Task completed: {task_prompt}",
            "execution_time": 15.5,
            "iterations": 3,
            "action_results": [
                {"action": "analysis", "result": "Analyzed requirements", "status": "completed"},
                {"action": "implementation", "result": "Implemented solution", "status": "completed"}
            ]
        }
    
    # System diagnostics
    def get_system_info():
        return {
            "penguin_version": "0.3.1",
            "engine_available": system_state["engine_available"],
            "checkpoints_enabled": True,
            "current_model": mock_model_manager.get_current_model(),
            "conversation_manager": {
                "active": True,
                "current_session_id": "session_123",
                "total_messages": len(conversation_history)
            },
            "tool_manager": {
                "active": True,
                "total_tools": 12
            },
            "memory_provider": {
                "initialized": True,
                "provider_type": "LanceProvider"
            }
        }
    
    def get_system_status():
        return {
            "status": "active",
            "runmode_status": "RunMode idle.",
            "continuous_mode": system_state["continuous_mode"],
            "streaming_active": system_state["streaming_active"],
            "token_usage": system_state["token_usage"],
            "timestamp": "2024-01-01T12:00:00Z",
            "initialization": {
                "core_initialized": system_state["initialized"],
                "fast_startup_enabled": True
            }
        }
    
    def get_token_usage():
        # Ensure we're returning the current state, not a copy
        return {
            "total": system_state["token_usage"]["total"].copy(),
            "session": system_state["token_usage"]["session"].copy()
        }
    
    # Wire up all the functionality
    core.process_message = process_message
    
    # Checkpoint management
    core.create_checkpoint = mock_checkpoint_manager.create_checkpoint
    core.rollback_to_checkpoint = mock_checkpoint_manager.rollback_to_checkpoint
    core.branch_from_checkpoint = mock_checkpoint_manager.branch_from_checkpoint
    core.list_checkpoints = mock_checkpoint_manager.list_checkpoints
    core.cleanup_old_checkpoints = mock_checkpoint_manager.cleanup_old_checkpoints
    
    # Model management
    core.load_model = mock_model_manager.load_model
    core.list_available_models = mock_model_manager.list_available_models
    core.get_current_model = mock_model_manager.get_current_model
    
    # System diagnostics
    core.get_system_info = get_system_info
    core.get_system_status = get_system_status
    core.get_token_usage = get_token_usage
    core.get_checkpoint_stats = MagicMock(return_value={"enabled": True, "total_checkpoints": 0})
    
    # Task execution
    core.engine = MagicMock()
    core.engine.run_task = execute_task_via_engine
    
    # Conversations
    core.list_conversations = MagicMock(return_value=[])
    core.get_conversation = MagicMock(return_value=None)
    core.create_conversation = MagicMock(return_value="conv_new")
    
    # Context files
    core.list_context_files = MagicMock(return_value=["main.py", "readme.md"])
    
    return core


class TestPenguinClientIntegration:
    """Integration tests for PenguinClient with realistic core behavior."""
    
    @pytest.mark.asyncio
    async def test_complete_client_workflow(self, integrated_core):
        """Test a complete end-to-end client workflow."""
        # Create and initialize client
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            # Step 1: Get initial system state
            initial_info = await client.get_system_info()
            assert initial_info["penguin_version"] == "0.3.1"
            assert initial_info["engine_available"] is True
            assert initial_info["conversation_manager"]["total_messages"] == 0
            
            # Step 2: Have a conversation
            response1 = await client.chat("Hello, can you help me with Python?")
            assert "AI response to: Hello, can you help me with Python?" in response1
            
            # Step 3: Check that conversation was recorded
            updated_info = await client.get_system_info()
            assert updated_info["conversation_manager"]["total_messages"] == 2  # user + assistant
            
            # Step 4: Create checkpoint before doing work
            checkpoint_id = await client.create_checkpoint("Before Python work")
            assert checkpoint_id.startswith("ckpt_")
            
            # Step 5: Do some work
            response2 = await client.chat("Write a function to calculate fibonacci numbers")
            assert "fibonacci numbers" in response2
            
            # Step 6: Check token usage increased
            status = await client.get_system_status()
            assert status["token_usage"]["total"]["input"] > 0
            assert status["token_usage"]["total"]["output"] > 0
            
            # Step 7: List models and switch to a different one
            models = await client.list_models()
            assert len(models) == 3
            
            initial_model = await client.get_current_model()
            assert initial_model.provider == "anthropic"
            
            # Switch to GPT-4
            switch_success = await client.switch_model("gpt-4")
            assert switch_success is True
            
            new_model = await client.get_current_model()
            assert new_model.provider == "openai"
            assert new_model.max_tokens == 8000
            
            # Step 8: Execute a task with the new model
            task_result = await client.execute_task("Create a web API")
            assert task_result["status"] == "completed"
            assert "Create a web API" in task_result["response"]
            assert task_result["execution_time"] > 0
            
            # Step 9: Create branch for experimentation
            branch_id = await client.branch_from_checkpoint(
                checkpoint_id,
                name="API experimentation",
                description="Trying different API approaches"
            )
            assert branch_id.startswith("branch_")
            
            # Step 10: List checkpoints to see our work
            checkpoints = await client.list_checkpoints()
            assert len(checkpoints) >= 2  # original + branch
            
            # Step 11: Final system check
            final_info = await client.get_system_info()
            assert final_info["conversation_manager"]["total_messages"] >= 4
            assert final_info["current_model"]["provider"] == "openai"  # Should reflect model switch
            
        finally:
            await client.close()
    
    @pytest.mark.asyncio
    async def test_checkpoint_workflow_integration(self, integrated_core):
        """Test integrated checkpoint workflow with realistic state management."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            # Initial state - no checkpoints
            initial_checkpoints = await client.list_checkpoints()
            assert len(initial_checkpoints) == 0
            
            # Do some initial work
            await client.chat("I want to build a web application")
            await client.chat("Let's start with the database schema")
            
            # Create checkpoint after planning
            planning_checkpoint = await client.create_checkpoint(
                "After planning",
                "Completed initial planning phase"
            )
            
            # Verify checkpoint was created
            checkpoints = await client.list_checkpoints()
            assert len(checkpoints) == 1
            assert checkpoints[0].name == "After planning"
            assert checkpoints[0].description == "Completed initial planning phase"
            
            # Continue work
            await client.chat("Now let's implement the user authentication")
            await client.execute_task("Create authentication system")
            
            # Create another checkpoint
            auth_checkpoint = await client.create_checkpoint("After auth", "Authentication implemented")
            
            # Now we should have 2 checkpoints
            checkpoints = await client.list_checkpoints()
            assert len(checkpoints) == 2
            
            # Create experimental branch
            experiment_branch = await client.branch_from_checkpoint(
                planning_checkpoint,
                "Alternative approach",
                "Trying a different approach from planning stage"
            )
            
            # Verify branch was created
            checkpoints = await client.list_checkpoints()
            assert len(checkpoints) == 3
            
            # Work on experimental branch
            await client.chat("Let's try a NoSQL database instead")
            
            # Rollback to auth checkpoint
            rollback_success = await client.rollback_to_checkpoint(auth_checkpoint)
            assert rollback_success is True
            
            # Clean up old checkpoints
            cleaned_count = await client.cleanup_checkpoints()
            assert cleaned_count >= 0
            
        finally:
            await client.close()
    
    @pytest.mark.asyncio
    async def test_model_switching_integration(self, integrated_core):
        """Test integrated model switching with realistic behavior."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            # Check initial model
            initial_model = await client.get_current_model()
            assert initial_model.provider == "anthropic"
            assert initial_model.vision_enabled is True
            
            # List all available models
            models = await client.list_models()
            assert len(models) == 3
            
            # Find models by provider
            anthropic_models = [m for m in models if m.provider == "anthropic"]
            openai_models = [m for m in models if m.provider == "openai"]
            
            assert len(anthropic_models) == 1
            assert len(openai_models) == 2
            
            # Test with anthropic model (vision-enabled)
            response1 = await client.chat("Describe what you see in this image", 
                                        ChatOptions(image_path="/fake/path/image.png"))
            assert "AI response" in response1
            
            # Switch to non-vision model
            gpt4_model = next(m for m in models if m.id == "gpt-4")
            assert gpt4_model.vision_enabled is False
            
            switch_success = await client.switch_model("gpt-4")
            assert switch_success is True
            
            # Verify switch
            current_model = await client.get_current_model()
            assert current_model.provider == "openai"
            assert current_model.max_tokens == 8000
            assert current_model.vision_enabled is False
            
            # Switch to vision-enabled OpenAI model
            switch_success = await client.switch_model("gpt-4-vision")
            assert switch_success is True
            
            current_model = await client.get_current_model()
            assert current_model.provider == "openai"
            assert current_model.vision_enabled is True
            
            # Test with vision-enabled model
            response2 = await client.chat("Analyze this code screenshot",
                                        ChatOptions(image_path="/fake/path/code.png"))
            assert "AI response" in response2
            
            # Verify model list reflects current state
            updated_models = await client.list_models()
            current_models = [m for m in updated_models if m.current]
            assert len(current_models) == 1
            assert current_models[0].id == "gpt-4-vision"
            
        finally:
            await client.close()
    
    @pytest.mark.asyncio
    async def test_system_monitoring_integration(self, integrated_core):
        """Test integrated system monitoring with realistic state changes."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            # Initial system state
            initial_info = await client.get_system_info()
            initial_status = await client.get_system_status()
            initial_usage = await client.get_token_usage()
            
            assert initial_info["penguin_version"] == "0.3.1"
            assert initial_status["status"] == "active"
            assert initial_usage["total"]["input"] == 0
            assert initial_usage["total"]["output"] == 0
            
            # Do some work that changes system state
            await client.chat("Explain machine learning concepts")
            await client.chat("Give me a detailed explanation of neural networks")
            await client.execute_task("Create a neural network example")
            
            # Check system state changes
            updated_info = await client.get_system_info()
            updated_status = await client.get_system_status()
            updated_usage = await client.get_token_usage()
            
            # Conversation count should have increased
            assert updated_info["conversation_manager"]["total_messages"] > initial_info["conversation_manager"]["total_messages"]
            
            # Token usage should have increased
            assert updated_usage["total"]["input"] > initial_usage["total"]["input"]
            assert updated_usage["total"]["output"] > initial_usage["total"]["output"]
            
            # Create some checkpoints and check stats
            await client.create_checkpoint("Checkpoint 1")
            await client.create_checkpoint("Checkpoint 2")
            
            checkpoint_stats = await client.get_checkpoint_stats()
            assert checkpoint_stats["enabled"] is True
            
            # Switch models and verify system info reflects it
            await client.switch_model("gpt-4")
            
            model_switched_info = await client.get_system_info()
            assert model_switched_info["current_model"]["provider"] == "openai"
            
            # System should still be healthy
            final_status = await client.get_system_status()
            assert final_status["status"] == "active"
            assert final_status["initialization"]["core_initialized"] is True
            
        finally:
            await client.close()


class TestErrorHandlingIntegration:
    """Integration tests for error handling across components."""
    
    @pytest.mark.asyncio
    async def test_model_switch_failure_recovery(self, integrated_core):
        """Test recovery from model switching failures."""
        client = PenguinClient()
        
        # Mock model loading to fail for certain models
        original_load_model = integrated_core.load_model
        
        async def failing_load_model(model_id):
            if model_id == "invalid-model":
                return False
            return await original_load_model(model_id)
        
        integrated_core.load_model = failing_load_model
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            # Get initial model
            initial_model = await client.get_current_model()
            assert initial_model.provider == "anthropic"
            
            # Try to switch to invalid model
            success = await client.switch_model("invalid-model")
            assert success is False
            
            # Verify we're still on the original model
            current_model = await client.get_current_model()
            assert current_model.provider == "anthropic"
            
            # System should still be functional
            response = await client.chat("Are you still working?")
            assert "AI response" in response
            
            # Valid model switch should still work
            success = await client.switch_model("gpt-4")
            assert success is True
            
            current_model = await client.get_current_model()
            assert current_model.provider == "openai"
            
        finally:
            await client.close()
    
    @pytest.mark.asyncio
    async def test_checkpoint_failure_recovery(self, integrated_core):
        """Test recovery from checkpoint operation failures."""
        client = PenguinClient()
        
        # Mock checkpoint operations to fail under certain conditions
        original_rollback = integrated_core.rollback_to_checkpoint
        
        async def failing_rollback(checkpoint_id):
            if checkpoint_id == "invalid-checkpoint":
                return False
            return await original_rollback(checkpoint_id)
        
        integrated_core.rollback_to_checkpoint = failing_rollback
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            # Create valid checkpoint
            checkpoint_id = await client.create_checkpoint("Valid checkpoint")
            assert checkpoint_id.startswith("ckpt_")
            
            # Do some work
            await client.chat("Some work that we might want to undo")
            
            # Try to rollback to invalid checkpoint
            success = await client.rollback_to_checkpoint("invalid-checkpoint")
            assert success is False
            
            # Valid rollback should still work
            success = await client.rollback_to_checkpoint(checkpoint_id)
            assert success is True
            
            # System should still be functional
            response = await client.chat("Test after rollback")
            assert "AI response" in response
            
        finally:
            await client.close()


class TestConcurrencyIntegration:
    """Integration tests for concurrent operations."""
    
    @pytest.mark.asyncio
    async def test_concurrent_chat_operations(self, integrated_core):
        """Test concurrent chat operations with shared state."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            # Start multiple concurrent chat operations
            tasks = [
                client.chat(f"Question {i}: Tell me about topic {i}")
                for i in range(5)
            ]
            
            # Wait for all to complete
            responses = await asyncio.gather(*tasks)
            
            # All should have received responses
            assert len(responses) == 5
            for i, response in enumerate(responses):
                assert f"topic {i}" in response
            
            # System state should reflect all operations
            info = await client.get_system_info()
            assert info["conversation_manager"]["total_messages"] == 10  # 5 user + 5 assistant
            
            usage = await client.get_token_usage()
            assert usage["total"]["input"] > 0
            assert usage["total"]["output"] > 0
            
        finally:
            await client.close()
    
    @pytest.mark.asyncio
    async def test_concurrent_checkpoint_operations(self, integrated_core):
        """Test concurrent checkpoint operations."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            # Create multiple checkpoints concurrently
            checkpoint_tasks = [
                client.create_checkpoint(f"Checkpoint {i}", f"Description {i}")
                for i in range(3)
            ]
            
            checkpoint_ids = await asyncio.gather(*checkpoint_tasks)
            
            # All should have been created
            assert len(checkpoint_ids) == 3
            for checkpoint_id in checkpoint_ids:
                assert checkpoint_id.startswith("ckpt_")
            
            # List checkpoints to verify
            checkpoints = await client.list_checkpoints()
            assert len(checkpoints) == 3
            
            # Concurrent rollback operations (only one should succeed per checkpoint)
            rollback_tasks = [
                client.rollback_to_checkpoint(checkpoint_id)
                for checkpoint_id in checkpoint_ids[:2]  # Only try first 2
            ]
            
            rollback_results = await asyncio.gather(*rollback_tasks)
            assert all(rollback_results)  # All should succeed since they're different checkpoints
            
        finally:
            await client.close()


class TestPerformanceIntegration:
    """Integration tests for performance characteristics."""
    
    @pytest.mark.asyncio
    async def test_large_conversation_handling(self, integrated_core):
        """Test handling of large conversations with many messages."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            # Have a long conversation
            message_count = 20
            for i in range(message_count):
                response = await client.chat(f"Message {i}: This is a test message to build up conversation history")
                assert "AI response" in response
            
            # Check system can handle the large conversation
            info = await client.get_system_info()
            assert info["conversation_manager"]["total_messages"] == message_count * 2
            
            # Token usage should scale appropriately
            usage = await client.get_token_usage()
            assert usage["total"]["input"] > message_count * 5  # Rough estimate
            assert usage["total"]["output"] > message_count * 5
            
            # System should still be responsive
            status = await client.get_system_status()
            assert status["status"] == "active"
            
            # Operations should still work efficiently
            checkpoint_id = await client.create_checkpoint("After long conversation")
            assert checkpoint_id.startswith("ckpt_")
            
        finally:
            await client.close()
    
    @pytest.mark.asyncio
    async def test_multiple_model_switches(self, integrated_core):
        """Test performance with multiple model switches."""
        client = PenguinClient()
        
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            await client.initialize()
        
        try:
            models = await client.list_models()
            model_ids = [m.id for m in models]
            
            # Switch between models multiple times
            for i in range(6):  # 2 cycles through 3 models
                model_id = model_ids[i % len(model_ids)]
                success = await client.switch_model(model_id)
                assert success is True
                
                # Verify switch
                current = await client.get_current_model()
                assert current is not None
                
                # Do some work with each model
                response = await client.chat(f"Test with model switch {i}")
                assert "AI response" in response
            
            # System should handle all switches correctly
            final_info = await client.get_system_info()
            assert final_info["current_model"] is not None
            
        finally:
            await client.close()


class TestCreateClientIntegration:
    """Integration tests for the create_client convenience function."""
    
    @pytest.mark.asyncio
    async def test_create_client_context_manager(self, integrated_core):
        """Test create_client as context manager with full workflow."""
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            # Properly await create_client first, then use client as context manager
            client = await create_client()
            try:
                # Should be automatically initialized
                assert client._initialized is True
                
                # Full workflow should work
                info = await client.get_system_info()
                assert info["penguin_version"] == "0.3.1"
                
                checkpoint_id = await client.create_checkpoint("Test")
                assert checkpoint_id.startswith("ckpt_")
                
                response = await client.chat("Hello")
                assert "AI response" in response
                
                models = await client.list_models()
                assert len(models) == 3
            finally:
                # Manual cleanup
                await client.close()
                assert client._initialized is False
    
    @pytest.mark.asyncio
    async def test_create_client_with_custom_parameters(self, integrated_core):
        """Test create_client with custom parameters."""
        with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
            client = await create_client(
                model="gpt-4",
                provider="openai",
                workspace_path="/custom/workspace"
            )
        
        try:
            # Should have custom parameters
            assert client.model == "gpt-4"
            assert client.provider == "openai"
            assert client.workspace_path == "/custom/workspace"
            
            # Should be initialized and functional
            assert client._initialized is True
            
            response = await client.chat("Test with custom params")
            assert "AI response" in response
            
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_complete_phase1_integration_scenario(integrated_core):
    """
    Complete Phase 1 integration test scenario covering all major features.
    
    This test simulates a realistic development workflow using all Phase 1 features:
    - Client initialization and management
    - Conversation with context
    - Checkpoint-based workflow
    - Model switching for different tasks
    - Task execution
    - System monitoring
    - Error handling and recovery
    """
    with patch('penguin.api_client.PenguinCore.create', return_value=integrated_core):
        # Properly await create_client first
        client = await create_client()
        try:
            
            # === PHASE 1: SETUP AND INITIAL EXPLORATION ===
            
            # Check system capabilities
            info = await client.get_system_info()
            assert info["penguin_version"] == "0.3.1"
            assert info["engine_available"] is True
            assert info["checkpoints_enabled"] is True
            
            # List available models for the project
            models = await client.list_models()
            assert len(models) >= 2
            
            vision_models = [m for m in models if m.vision_enabled]
            coding_models = [m for m in models if m.max_tokens >= 8000]
            
            print(f"Available vision models: {len(vision_models)}")
            print(f"Available high-context models: {len(coding_models)}")
            
            # === PHASE 2: PROJECT PLANNING ===
            
            # Start project planning conversation
            planning_response = await client.chat(
                "I want to create a web application for task management. Help me plan the architecture.",
                ChatOptions(context={"project": "task_manager", "phase": "planning"})
            )
            assert "AI response" in planning_response
            
            # Create checkpoint after initial planning
            planning_checkpoint = await client.create_checkpoint(
                "Initial Planning", 
                "Completed architecture planning for task management app"
            )
            assert planning_checkpoint.startswith("ckpt_")
            
            # Continue planning with more specific questions
            db_response = await client.chat(
                "What database schema would you recommend for this task management system?"
            )
            assert "AI response" in db_response
            
            # === PHASE 3: IMPLEMENTATION PHASE ===
            
            # Switch to a high-context model for coding
            if coding_models:
                switch_success = await client.switch_model(coding_models[0].id)
                assert switch_success is True
                
                current_model = await client.get_current_model()
                assert current_model.max_tokens >= 8000
            
            # Execute implementation task
            backend_task = await client.execute_task(
                "Create the backend API for the task management system",
                TaskOptions(
                    name="Backend Implementation",
                    description="Implement REST API with user authentication and task CRUD operations",
                    context={"framework": "FastAPI", "database": "PostgreSQL"}
                )
            )
            
            assert backend_task["status"] == "completed"
            assert "Create the backend API" in backend_task.get("response", "")
            
            # Create checkpoint after backend
            backend_checkpoint = await client.create_checkpoint(
                "Backend Complete",
                "Completed backend API implementation"
            )
            
            # === PHASE 4: FRONTEND EXPLORATION ===
            
            # Create experimental branch for frontend approach
            frontend_branch = await client.branch_from_checkpoint(
                backend_checkpoint,
                "Frontend Experiment",
                "Exploring different frontend frameworks"
            )
            assert frontend_branch.startswith("branch_")
            
            # Switch to vision model for UI work
            if vision_models:
                await client.switch_model(vision_models[0].id)
                current_model = await client.get_current_model()
                assert current_model.vision_enabled is True
            
            # Work on frontend with vision model
            frontend_response = await client.chat(
                "Design a modern UI for the task management application",
                ChatOptions(
                    context={"component": "frontend", "style": "modern"},
                    image_path="/fake/path/mockup.png"  # Simulated image
                )
            )
            assert "AI response" in frontend_response
            
            # === PHASE 5: TESTING AND REFINEMENT ===
            
            # Execute testing task
            testing_task = await client.execute_task(
                "Create comprehensive tests for the task management API",
                TaskOptions(name="Testing", context={"test_framework": "pytest"})
            )
            assert testing_task["status"] == "completed"
            
            # === PHASE 6: SYSTEM MONITORING AND OPTIMIZATION ===
            
            # Monitor system state
            status = await client.get_system_status()
            usage = await client.get_token_usage()
            
            assert status["status"] == "active"
            assert usage["total"]["input"] > 0
            assert usage["total"]["output"] > 0
            
            # Check conversation history
            final_info = await client.get_system_info()
            assert final_info["conversation_manager"]["total_messages"] >= 6  # Multiple exchanges
            
            # List all checkpoints created during the project
            checkpoints = await client.list_checkpoints()
            assert len(checkpoints) >= 3  # planning, backend, branch
            
            checkpoint_names = [cp.name for cp in checkpoints]
            assert "Initial Planning" in checkpoint_names
            assert "Backend Complete" in checkpoint_names
            
            # === PHASE 7: ERROR RECOVERY SIMULATION ===
            
            # Simulate rollback scenario
            rollback_success = await client.rollback_to_checkpoint(planning_checkpoint)
            assert rollback_success is True
            
            # Continue from planning checkpoint with different approach
            alternative_response = await client.chat(
                "Let's try a microservices approach instead"
            )
            assert "AI response" in alternative_response
            
            # === PHASE 8: CLEANUP AND MAINTENANCE ===
            
            # Clean up old checkpoints
            cleaned_count = await client.cleanup_checkpoints()
            assert cleaned_count >= 0
            
            # Final system health check
            final_status = await client.get_system_status()
            final_stats = await client.get_checkpoint_stats()
            
            assert final_status["status"] == "active"
            assert final_status["initialization"]["core_initialized"] is True
            assert final_stats["enabled"] is True
            
            print("✅ Complete Phase 1 integration test passed!")
            print(f"   - Total messages: {final_info['conversation_manager']['total_messages']}")
            print(f"   - Token usage: {usage['total']['input']} input, {usage['total']['output']} output")
            print(f"   - Checkpoints created: {len(checkpoints)}")
            print(f"   - Models used: {len(set(m.provider for m in models))}")
        finally:
            # Manual cleanup
            await client.close()


if __name__ == "__main__":
    # This allows running the integration tests directly
    pytest.main([__file__, "-v"])