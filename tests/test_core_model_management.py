"""
Tests for PenguinCore model management functionality.

This module tests the model management methods added to PenguinCore including:
- load_model()
- list_available_models() 
- get_current_model()
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any

from penguin.core import PenguinCore
from penguin.llm.model_config import ModelConfig


@pytest.fixture
def mock_model_config():
    """Fixture to create a mock ModelConfig."""
    config = MagicMock(spec=ModelConfig)
    config.model = "anthropic/claude-3-sonnet-20240229"
    config.provider = "anthropic"
    config.client_preference = "native"
    config.max_tokens = 4000
    config.temperature = 0.7
    config.streaming_enabled = True
    config.vision_enabled = True
    config.api_base = None
    return config


@pytest.fixture
def mock_config():
    """Fixture to create a mock configuration with model configs."""
    config = MagicMock()
    config.model_configs = {
        "claude-3-sonnet": {
            "model": "anthropic/claude-3-sonnet-20240229",
            "provider": "anthropic",
            "client_preference": "native",
            "vision_enabled": True,
            "max_tokens": 4000,
            "temperature": 0.7
        },
        "gpt-4": {
            "model": "openai/gpt-4",
            "provider": "openai", 
            "client_preference": "native",
            "vision_enabled": False,
            "max_tokens": 8000,
            "temperature": 0.3
        },
        "gpt-4-vision": {
            "model": "openai/gpt-4-vision-preview",
            "provider": "openai",
            "client_preference": "native", 
            "vision_enabled": True,
            "max_tokens": 4000,
            "temperature": 0.5
        }
    }
    return config


@pytest.fixture
def mock_core(mock_model_config, mock_config):
    """Fixture to create a mock PenguinCore with model management functionality."""
    core = MagicMock(spec=PenguinCore)
    core.model_config = mock_model_config
    core.config = mock_config
    core.initialized = True
    
    # Mock dependencies
    core.api_client = MagicMock()
    core.conversation_manager = MagicMock()
    core.engine = MagicMock()
    
    # Mock internal methods
    core._apply_new_model_config = MagicMock()
    core._fetch_model_specifications = AsyncMock(return_value={
        "context_length": 200000,
        "max_output_tokens": 4000,
        "supports_vision": True
    })
    core._update_config_file_with_model = MagicMock()
    
    # Set up the actual methods we're testing
    core.load_model = PenguinCore.load_model.__get__(core)
    core.list_available_models = PenguinCore.list_available_models.__get__(core)
    core.get_current_model = PenguinCore.get_current_model.__get__(core)
    
    return core


class TestPenguinCoreModelManagement:
    """Test suite for PenguinCore model management methods."""
    
    def test_list_available_models_basic(self, mock_core):
        """Test basic model listing functionality."""
        result = mock_core.list_available_models()
        
        assert len(result) == 3
        
        # Check that models are returned with correct structure
        model_ids = [model["id"] for model in result]
        assert "claude-3-sonnet" in model_ids
        assert "gpt-4" in model_ids
        assert "gpt-4-vision" in model_ids
        
        # Check current model is marked correctly
        current_models = [model for model in result if model["current"]]
        assert len(current_models) == 1
        assert current_models[0]["id"] == "claude-3-sonnet"
    
    def test_list_available_models_detailed_structure(self, mock_core):
        """Test detailed structure of model list response."""
        result = mock_core.list_available_models()
        
        claude_model = next(model for model in result if model["id"] == "claude-3-sonnet")
        
        assert claude_model["name"] == "anthropic/claude-3-sonnet-20240229"
        assert claude_model["provider"] == "anthropic"
        assert claude_model["client_preference"] == "native"
        assert claude_model["vision_enabled"] is True
        assert claude_model["max_tokens"] == 4000
        assert claude_model["temperature"] == 0.7
        assert claude_model["current"] is True
    
    def test_list_available_models_sorting(self, mock_core):
        """Test that current model is sorted to the top."""
        result = mock_core.list_available_models()
        
        # Current model should be first
        assert result[0]["current"] is True
        assert result[0]["id"] == "claude-3-sonnet"
        
        # Other models should not be current
        for model in result[1:]:
            assert model["current"] is False
    
    def test_list_available_models_no_config(self, mock_core):
        """Test model listing when no model configs are available."""
        mock_core.config.model_configs = None
        
        result = mock_core.list_available_models()
        
        assert result == []
    
    def test_list_available_models_empty_config(self, mock_core):
        """Test model listing with empty model configs."""
        mock_core.config.model_configs = {}
        
        result = mock_core.list_available_models()
        
        assert result == []
    
    def test_list_available_models_invalid_config_entries(self, mock_core):
        """Test model listing with some invalid config entries."""
        # Add invalid entries to config
        mock_core.config.model_configs["invalid"] = "not_a_dict"
        mock_core.config.model_configs["also_invalid"] = None
        
        result = mock_core.list_available_models()
        
        # Should only return valid configurations
        assert len(result) == 3
        model_ids = [model["id"] for model in result]
        assert "invalid" not in model_ids
        assert "also_invalid" not in model_ids
    
    @pytest.mark.asyncio
    async def test_load_model_existing_config(self, mock_core):
        """Test loading a model that exists in configuration."""
        # Mock ModelConfig creation
        with patch('penguin.core.ModelConfig') as mock_model_config_class:
            mock_new_config = MagicMock()
            mock_model_config_class.return_value = mock_new_config
            
            result = await mock_core.load_model("gpt-4")
            
            assert result is True
            mock_core._apply_new_model_config.assert_called_once_with(mock_new_config)
            mock_core._update_config_file_with_model.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_load_model_fully_qualified(self, mock_core):
        """Test loading a model using fully qualified name."""
        # Mock ModelConfig creation
        with patch('penguin.core.ModelConfig') as mock_model_config_class:
            mock_new_config = MagicMock()
            mock_model_config_class.return_value = mock_new_config
            
            result = await mock_core.load_model("openai/gpt-3.5-turbo")
            
            assert result is True
            mock_core._apply_new_model_config.assert_called_once_with(mock_new_config)
    
    @pytest.mark.asyncio
    async def test_load_model_invalid_format(self, mock_core):
        """Test loading a model with invalid format."""
        result = await mock_core.load_model("invalid_model_name")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_load_model_exception_handling(self, mock_core):
        """Test error handling in model loading."""
        # Mock ModelConfig to raise exception
        with patch('penguin.core.ModelConfig', side_effect=Exception("Config creation failed")):
            result = await mock_core.load_model("gpt-4")
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_load_model_fetch_specifications_failure(self, mock_core):
        """Test model loading when specification fetching fails."""
        mock_core._fetch_model_specifications.side_effect = Exception("API error")
        
        result = await mock_core.load_model("gpt-4")
        
        assert result is False
    
    def test_get_current_model_success(self, mock_core):
        """Test getting current model information."""
        result = mock_core.get_current_model()
        
        assert result is not None
        assert result["model"] == "anthropic/claude-3-sonnet-20240229"
        assert result["provider"] == "anthropic"
        assert result["client_preference"] == "native"
        assert result["max_tokens"] == 4000
        assert result["temperature"] == 0.7
        assert result["streaming_enabled"] is True
        assert result["vision_enabled"] is True
        assert result["api_base"] is None
    
    def test_get_current_model_no_config(self, mock_core):
        """Test getting current model when no model config exists."""
        mock_core.model_config = None
        
        result = mock_core.get_current_model()
        
        assert result is None
    
    def test_get_current_model_missing_attributes(self, mock_core):
        """Test getting current model with missing optional attributes."""
        # Remove optional attributes
        del mock_core.model_config.max_tokens
        del mock_core.model_config.temperature
        del mock_core.model_config.api_base
        
        result = mock_core.get_current_model()
        
        assert result is not None
        assert result["model"] == "anthropic/claude-3-sonnet-20240229"
        assert result["provider"] == "anthropic"
        assert result["max_tokens"] is None
        assert result["temperature"] is None
        assert result["api_base"] is None
        assert result["streaming_enabled"] is True
        assert result["vision_enabled"] is True


class TestModelManagementIntegration:
    """Integration tests for model management workflow scenarios."""
    
    @pytest.mark.asyncio
    async def test_model_switching_workflow(self, mock_core):
        """Test a complete model switching workflow."""
        # Step 1: Get initial model
        initial_model = mock_core.get_current_model()
        assert initial_model["model"] == "anthropic/claude-3-sonnet-20240229"
        
        # Step 2: List available models
        available_models = mock_core.list_available_models()
        assert len(available_models) == 3
        
        # Step 3: Switch to different model
        with patch('penguin.core.ModelConfig'):
            success = await mock_core.load_model("gpt-4")
            assert success is True
        
        # Step 4: Verify model was applied
        mock_core._apply_new_model_config.assert_called_once()
    
    @pytest.mark.asyncio  
    async def test_model_switching_with_vision_check(self, mock_core):
        """Test model switching considering vision capabilities."""
        # List models and find vision-enabled ones
        models = mock_core.list_available_models()
        vision_models = [m for m in models if m["vision_enabled"]]
        
        assert len(vision_models) == 2  # claude-3-sonnet and gpt-4-vision
        
        # Switch to vision model
        with patch('penguin.core.ModelConfig'):
            success = await mock_core.load_model("gpt-4-vision")
            assert success is True
    
    def test_model_filtering_by_provider(self, mock_core):
        """Test filtering models by provider."""
        models = mock_core.list_available_models()
        
        anthropic_models = [m for m in models if m["provider"] == "anthropic"]
        openai_models = [m for m in models if m["provider"] == "openai"]
        
        assert len(anthropic_models) == 1
        assert len(openai_models) == 2
        
        assert anthropic_models[0]["id"] == "claude-3-sonnet"
        assert "gpt-4" in [m["id"] for m in openai_models]
        assert "gpt-4-vision" in [m["id"] for m in openai_models]
    
    def test_model_capabilities_comparison(self, mock_core):
        """Test comparing model capabilities."""
        models = mock_core.list_available_models()
        
        # Group by capabilities
        vision_enabled = [m for m in models if m["vision_enabled"]]
        high_token_limit = [m for m in models if m.get("max_tokens", 0) >= 8000]
        low_temperature = [m for m in models if m.get("temperature", 1.0) <= 0.3]
        
        assert len(vision_enabled) == 2
        assert len(high_token_limit) == 1
        assert len(low_temperature) == 1
        
        assert high_token_limit[0]["id"] == "gpt-4"
        assert low_temperature[0]["id"] == "gpt-4"


class TestModelConfigurationEdgeCases:
    """Test edge cases and error conditions in model management."""
    
    def test_list_models_with_malformed_config(self, mock_core):
        """Test handling of malformed model configurations."""
        # Add malformed configurations
        mock_core.config.model_configs["malformed"] = {
            "model": "test/model",
            # Missing required fields
        }
        mock_core.config.model_configs["incomplete"] = {
            "provider": "test",
            # Missing model field
        }
        
        result = mock_core.list_available_models()
        
        # Should handle gracefully and include valid entries
        assert len(result) >= 3  # Original 3 valid models
        
        # Check that malformed entries have default values
        for model in result:
            assert "id" in model
            assert "name" in model
            assert "provider" in model
    
    @pytest.mark.asyncio
    async def test_load_model_network_timeout(self, mock_core):
        """Test model loading with network timeout during spec fetching."""
        import asyncio
        mock_core._fetch_model_specifications.side_effect = asyncio.TimeoutError("Network timeout")
        
        result = await mock_core.load_model("gpt-4")
        
        assert result is False
    
    def test_get_current_model_with_engine_integration(self, mock_core):
        """Test current model info includes engine compatibility."""
        # Mock engine existence
        mock_core.engine = MagicMock()
        
        result = mock_core.get_current_model()
        
        assert result is not None
        # Current model info should be independent of engine
        assert "model" in result
        assert "provider" in result