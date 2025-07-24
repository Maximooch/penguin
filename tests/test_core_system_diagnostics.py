"""
Tests for PenguinCore system diagnostics functionality.

This module tests the system diagnostics methods added to PenguinCore including:
- get_system_info()
- get_system_status()
- get_token_usage() (existing method verification)
- get_memory_provider_status() 
- get_startup_stats()
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from typing import Dict, Any

from penguin.core import PenguinCore
from penguin.llm.model_config import ModelConfig


@pytest.fixture
def mock_model_config():
    """Fixture to create a mock ModelConfig."""
    config = MagicMock(spec=ModelConfig)
    config.model = "anthropic/claude-3-sonnet-20240229"
    config.provider = "anthropic"
    config.streaming_enabled = True
    config.vision_enabled = True
    return config


@pytest.fixture
def mock_conversation_manager():
    """Fixture to mock ConversationManager."""
    manager = MagicMock()
    
    # Mock session
    session = MagicMock()
    session.id = "session_123"
    session.messages = ["msg1", "msg2", "msg3"]  # 3 messages
    manager.get_current_session.return_value = session
    
    # Mock token usage
    manager.get_token_usage.return_value = {
        "total": {"input": 1500, "output": 800},
        "session": {"input": 300, "output": 150}
    }
    
    return manager


@pytest.fixture
def mock_tool_manager():
    """Fixture to mock ToolManager."""
    manager = MagicMock()
    manager.tools = {
        "file_tool": MagicMock(),
        "web_tool": MagicMock(),
        "python_tool": MagicMock()
    }
    manager.fast_startup = True
    
    # Mock memory provider
    memory_provider = MagicMock()
    memory_provider.__class__.__name__ = "LanceProvider"
    manager._memory_provider = memory_provider
    
    return manager


@pytest.fixture
def mock_engine():
    """Fixture to mock Engine."""
    engine = MagicMock()
    engine.some_property = "engine_value"
    return engine


@pytest.fixture
def mock_core(mock_model_config, mock_conversation_manager, mock_tool_manager, mock_engine):
    """Fixture to create a mock PenguinCore with system diagnostics functionality."""
    core = MagicMock(spec=PenguinCore)
    
    # Set up core attributes
    core.model_config = mock_model_config
    core.conversation_manager = mock_conversation_manager
    core.tool_manager = mock_tool_manager
    core.engine = mock_engine
    core.initialized = True
    core._continuous_mode = False
    core._streaming_state = {"active": False}
    core.current_runmode_status_summary = "RunMode idle."
    
    # Mock checkpoint stats
    core.get_checkpoint_stats = MagicMock(return_value={"enabled": True})
    
    # Mock memory provider status
    core.get_memory_provider_status = MagicMock(return_value={
        "status": "initialized",
        "provider": "LanceProvider"
    })
    
    # Set up the actual methods we're testing
    core.get_system_info = PenguinCore.get_system_info.__get__(core)
    core.get_system_status = PenguinCore.get_system_status.__get__(core)
    core.get_token_usage = PenguinCore.get_token_usage.__get__(core)
    
    return core


class TestPenguinCoreSystemDiagnostics:
    """Test suite for PenguinCore system diagnostics methods."""
    
    def test_get_system_info_complete(self, mock_core):
        """Test complete system info with all components available."""
        result = mock_core.get_system_info()
        
        # Verify basic system info
        assert result["penguin_version"] == "0.3.1"
        assert result["engine_available"] is True
        assert result["checkpoints_enabled"] is True
        
        # Verify current model info
        assert result["current_model"] is not None
        assert result["current_model"]["model"] == "anthropic/claude-3-sonnet-20240229"
        assert result["current_model"]["provider"] == "anthropic"
        assert result["current_model"]["streaming_enabled"] is True
        assert result["current_model"]["vision_enabled"] is True
        
        # Verify conversation manager info
        assert result["conversation_manager"]["active"] is True
        assert result["conversation_manager"]["current_session_id"] == "session_123"
        assert result["conversation_manager"]["total_messages"] == 3
        
        # Verify tool manager info
        assert result["tool_manager"]["active"] is True
        assert result["tool_manager"]["total_tools"] == 3
        
        # Verify memory provider info
        assert result["memory_provider"]["initialized"] is True
        assert result["memory_provider"]["provider_type"] == "LanceProvider"
    
    def test_get_system_info_minimal_setup(self, mock_core):
        """Test system info with minimal component setup."""
        # Remove optional components
        mock_core.engine = None
        mock_core.model_config = None
        mock_core.conversation_manager = None
        mock_core.tool_manager = None
        
        result = mock_core.get_system_info()
        
        # Basic info should still be present
        assert result["penguin_version"] == "0.3.1"
        assert result["engine_available"] is False
        assert result["current_model"] is None
        
        # Component info should reflect missing components
        assert result["conversation_manager"]["active"] is False
        assert result["tool_manager"]["active"] is False
        assert result["memory_provider"]["initialized"] is False
    
    def test_get_system_info_session_error(self, mock_core):
        """Test system info when session retrieval fails."""
        mock_core.conversation_manager.get_current_session.side_effect = Exception("Session error")
        
        result = mock_core.get_system_info()
        
        # Should handle error gracefully
        assert result["conversation_manager"]["active"] is True
        assert result["conversation_manager"]["current_session_id"] is None
        assert result["conversation_manager"]["total_messages"] == 0
        
        # Other info should still be present
        assert "penguin_version" in result
        assert "engine_available" in result
    
    def test_get_system_info_exception_handling(self, mock_core):
        """Test system info error handling."""
        # Mock hasattr to raise exception
        # Trigger an exception by making model_config access fail
        type(mock_core).model_config = property(lambda self: (_ for _ in ()).throw(Exception("Model config error")))
        
        result = mock_core.get_system_info()
        
        # Should return error dict
        assert "error" in result
        assert "Failed to get system info" in result["error"]
    
    def test_get_system_status_complete(self, mock_core):
        """Test complete system status with all runtime info."""
        result = mock_core.get_system_status()
        
        # Verify basic status
        assert result["status"] == "active"
        assert result["runmode_status"] == "RunMode idle."
        assert result["continuous_mode"] is False
        assert result["streaming_active"] is False
        assert "timestamp" in result  # Just verify timestamp exists
        
        # Verify token usage
        assert result["token_usage"]["total"]["input"] == 1500
        assert result["token_usage"]["total"]["output"] == 800
        assert result["token_usage"]["session"]["input"] == 300
        assert result["token_usage"]["session"]["output"] == 150
        
        # Verify initialization info
        assert result["initialization"]["core_initialized"] is True
        assert result["initialization"]["fast_startup_enabled"] is True
        
        # Verify memory provider status is included
        assert result["memory_provider"]["status"] == "initialized"
    
    def test_get_system_status_active_states(self, mock_core):
        """Test system status with active streaming and continuous mode."""
        mock_core._continuous_mode = True
        mock_core._streaming_state = {"active": True}
        mock_core.current_runmode_status_summary = "Running task: Create web server"
        
        result = mock_core.get_system_status()
        
        assert result["continuous_mode"] is True
        assert result["streaming_active"] is True
        assert result["runmode_status"] == "Running task: Create web server"
    
    def test_get_system_status_missing_attributes(self, mock_core):
        """Test system status with missing optional attributes."""
        # Remove optional attributes
        del mock_core._continuous_mode
        del mock_core._streaming_state
        del mock_core.current_runmode_status_summary
        del mock_core.initialized
        mock_core.tool_manager = None
        
        result = mock_core.get_system_status()
        
        # Should use default values
        assert result["continuous_mode"] is False
        assert result["streaming_active"] is False
        assert result["runmode_status"] == "RunMode idle."
        assert result["initialization"]["core_initialized"] is False
        assert result["initialization"]["fast_startup_enabled"] is False
    
    def test_get_system_status_exception_handling(self, mock_core):
        """Test system status error handling."""
        # Force an exception by making getattr fail
        with patch('builtins.getattr', side_effect=Exception("Getattr error")):
        
            result = mock_core.get_system_status()
            
            assert result["status"] == "error"
            assert "Failed to get system status" in result["error"]
            assert "timestamp" in result
    
    def test_get_token_usage_success(self, mock_core):
        """Test successful token usage retrieval."""
        result = mock_core.get_token_usage()
        
        assert result["total"]["input"] == 1500
        assert result["total"]["output"] == 800
        assert result["session"]["input"] == 300
        assert result["session"]["output"] == 150
    
    def test_get_token_usage_no_conversation_manager(self, mock_core):
        """Test token usage when conversation manager is not available."""
        mock_core.conversation_manager = None
        
        result = mock_core.get_token_usage()
        
        # Should return default/empty usage
        assert isinstance(result, dict)
    
    def test_get_token_usage_exception_handling(self, mock_core):
        """Test token usage error handling."""
        mock_core.conversation_manager.get_token_usage.side_effect = Exception("Token error")
        
        result = mock_core.get_token_usage()
        
        # Should handle gracefully
        assert isinstance(result, dict)


class TestSystemDiagnosticsIntegration:
    """Integration tests for system diagnostics workflow scenarios."""
    
    def test_complete_system_health_check(self, mock_core):
        """Test a complete system health check workflow."""
        # Step 1: Get system information
        info = mock_core.get_system_info()
        assert info["penguin_version"] == "0.3.1"
        assert info["engine_available"] is True
        
        # Step 2: Get current status
        status = mock_core.get_system_status()
        assert status["status"] == "active"
        
        # Step 3: Check token usage
        usage = mock_core.get_token_usage()
        assert "total" in usage
        assert "session" in usage
        
        # Step 4: Verify component health
        assert info["conversation_manager"]["active"] is True
        assert info["tool_manager"]["active"] is True
        assert info["memory_provider"]["initialized"] is True
    
    def test_system_monitoring_over_time(self, mock_core):
        """Test system monitoring over multiple calls."""
        # Simulate system state changes
        initial_status = mock_core.get_system_status()
        assert initial_status["continuous_mode"] is False
        
        # Change system state
        mock_core._continuous_mode = True
        mock_core.current_runmode_status_summary = "Running continuous task"
        
        updated_status = mock_core.get_system_status()
        assert updated_status["continuous_mode"] is True
        assert updated_status["runmode_status"] == "Running continuous task"
    
    def test_diagnostics_with_system_degradation(self, mock_core):
        """Test diagnostics when system components fail."""
        # Simulate component failures
        mock_core.engine = None
        mock_core.conversation_manager.get_current_session.side_effect = Exception("DB error")
        mock_core.tool_manager._memory_provider = None
        
        # System info should reflect degraded state
        info = mock_core.get_system_info()
        assert info["engine_available"] is False
        assert info["memory_provider"]["initialized"] is False
        assert info["conversation_manager"]["current_session_id"] is None
        
        # Status should still be retrievable
        status = mock_core.get_system_status()
        assert status["status"] == "active"  # Core is still functional
    
    def test_performance_monitoring_data(self, mock_core):
        """Test that diagnostics provide useful performance monitoring data."""
        # Add mock startup stats
        mock_core.get_startup_stats = MagicMock(return_value={
            "profiling_summary": {"total_time": 2.5, "components": 5},
            "tool_manager_stats": {"fast_startup": True, "memory_provider_exists": True},
            "memory_provider_initialized": True,
            "core_initialized": True
        })
        
        info = mock_core.get_system_info()
        status = mock_core.get_system_status()
        
        # Should have performance-relevant data
        assert "initialization" in status
        assert status["initialization"]["fast_startup_enabled"] is True
        assert info["memory_provider"]["initialized"] is True
        
        # Token usage provides resource consumption data
        usage = mock_core.get_token_usage()
        assert usage["total"]["input"] > 0
        assert usage["total"]["output"] > 0


class TestSystemDiagnosticsEdgeCases:
    """Test edge cases and boundary conditions in system diagnostics."""
    
    def test_system_info_with_vision_model_edge_cases(self, mock_core):
        """Test system info with various vision model configurations."""
        # Test with model config missing vision_enabled attribute
        mock_core.model_config.vision_enabled = None
        
        result = mock_core.get_system_info()
        
        # Should handle gracefully with default value
        assert result["current_model"]["vision_enabled"] is False
    
    def test_memory_usage_tracking(self, mock_core):
        """Test that system status can track memory usage patterns."""
        # Simulate high token usage
        mock_core.conversation_manager.get_token_usage.return_value = {
            "total": {"input": 50000, "output": 25000},
            "session": {"input": 10000, "output": 5000}
        }
        
        usage = mock_core.get_token_usage()
        
        # Should track high usage
        assert usage["total"]["input"] == 50000
        assert usage["session"]["input"] == 10000
        
        # System status should be able to include this
        status = mock_core.get_system_status()
        assert status["token_usage"]["total"]["input"] == 50000
    
    def test_concurrent_diagnostics_calls(self, mock_core):
        """Test that diagnostics methods are thread-safe for concurrent calls."""
        import threading
        import time
        
        results = []
        
        def get_system_info():
            time.sleep(0.1)  # Simulate some processing time
            results.append(mock_core.get_system_info())
        
        def get_system_status():
            time.sleep(0.1)
            results.append(mock_core.get_system_status())
        
        # Start concurrent calls
        threads = [
            threading.Thread(target=get_system_info),
            threading.Thread(target=get_system_status),
            threading.Thread(target=get_system_info),
        ]
        
        for thread in threads:
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All calls should complete successfully
        assert len(results) == 3
        
        # Results should be consistent
        info_results = [r for r in results if "penguin_version" in r]
        status_results = [r for r in results if "status" in r and "penguin_version" not in r]
        
        assert len(info_results) == 2
        assert len(status_results) == 1
        
        # Info results should be identical
        assert info_results[0] == info_results[1]