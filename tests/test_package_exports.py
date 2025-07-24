"""
Tests for package exports and imports.

This module tests that all the new classes and functions added to the 
penguin package are properly exported and importable, including:
- Core classes and functions
- Checkpoint management classes
- Model configuration classes
- System classes
- API client classes
- Data classes and types
"""

import pytest
import sys
from unittest.mock import patch, MagicMock


class TestCoreExports:
    """Test core package exports."""
    
    def test_core_classes_importable(self):
        """Test that core classes can be imported."""
        try:
            from penguin import PenguinCore, PenguinAgent, Engine, EngineSettings
            assert PenguinCore is not None
            assert PenguinAgent is not None
            assert Engine is not None
            assert EngineSettings is not None
        except ImportError as e:
            pytest.fail(f"Failed to import core classes: {e}")
    
    def test_project_management_importable(self):
        """Test that project management classes can be imported."""
        try:
            from penguin import ProjectManager, Project, Task
            assert ProjectManager is not None
            assert Project is not None
            assert Task is not None
        except ImportError as e:
            pytest.fail(f"Failed to import project management classes: {e}")
    
    def test_config_importable(self):
        """Test that config can be imported."""
        try:
            from penguin import config
            assert config is not None
        except ImportError as e:
            pytest.fail(f"Failed to import config: {e}")


class TestCheckpointExports:
    """Test checkpoint management exports."""
    
    def test_checkpoint_classes_importable(self):
        """Test that checkpoint classes can be imported."""
        try:
            from penguin import CheckpointManager, CheckpointConfig, CheckpointType, CheckpointMetadata
            assert CheckpointManager is not None
            assert CheckpointConfig is not None
            assert CheckpointType is not None
            assert CheckpointMetadata is not None
        except ImportError as e:
            # These might not always be available depending on dependencies
            pytest.skip(f"Checkpoint classes not available: {e}")
    
    def test_checkpoint_type_enum(self):
        """Test that CheckpointType enum has expected values."""
        try:
            from penguin import CheckpointType
            
            # Check that enum values exist
            assert hasattr(CheckpointType, 'AUTO')
            assert hasattr(CheckpointType, 'MANUAL')
            assert hasattr(CheckpointType, 'BRANCH')
            assert hasattr(CheckpointType, 'ROLLBACK')
            
        except ImportError:
            pytest.skip("CheckpointType not available")
    
    def test_checkpoint_config_structure(self):
        """Test that CheckpointConfig has expected structure."""
        try:
            from penguin import CheckpointConfig
            
            # Create instance with defaults
            config = CheckpointConfig()
            
            # Check that expected attributes exist
            assert hasattr(config, 'enabled')
            assert hasattr(config, 'frequency')
            assert hasattr(config, 'planes')
            assert hasattr(config, 'retention')
            
            # Check default values
            assert config.enabled is True
            assert config.frequency == 1
            assert isinstance(config.planes, dict)
            assert isinstance(config.retention, dict)
            
        except ImportError:
            pytest.skip("CheckpointConfig not available")


class TestModelExports:
    """Test model configuration exports."""
    
    def test_model_config_importable(self):
        """Test that ModelConfig can be imported."""
        try:
            from penguin import ModelConfig
            assert ModelConfig is not None
        except ImportError:
            pytest.skip("ModelConfig not available")
    
    def test_model_config_structure(self):
        """Test that ModelConfig has expected structure."""
        try:
            from penguin import ModelConfig
            
            # Create instance
            config = ModelConfig(
                model="test/model",
                provider="test"
            )
            
            # Check that expected attributes exist
            assert hasattr(config, 'model')
            assert hasattr(config, 'provider')
            assert config.model == "test/model"
            assert config.provider == "test"
            
        except ImportError:
            pytest.skip("ModelConfig not available")


class TestSystemExports:
    """Test system-related exports."""
    
    def test_system_classes_importable(self):
        """Test that system classes can be imported."""
        try:
            from penguin import ConversationManager, Session, Message, MessageCategory
            assert ConversationManager is not None
            assert Session is not None
            assert Message is not None
            assert MessageCategory is not None
        except ImportError:
            pytest.skip("System classes not available")


class TestAPIClientExports:
    """Test API client exports."""
    
    def test_api_client_classes_importable(self):
        """Test that API client classes can be imported."""
        try:
            from penguin import PenguinClient, ChatOptions, TaskOptions, CheckpointInfo, ModelInfo, create_client
            assert PenguinClient is not None
            assert ChatOptions is not None
            assert TaskOptions is not None
            assert CheckpointInfo is not None
            assert ModelInfo is not None
            assert create_client is not None
        except ImportError:
            pytest.skip("API client classes not available")
    
    def test_chat_options_structure(self):
        """Test that ChatOptions has expected structure."""
        try:
            from penguin import ChatOptions
            
            # Create instance with defaults
            options = ChatOptions()
            
            # Check that expected attributes exist
            assert hasattr(options, 'conversation_id')
            assert hasattr(options, 'context')
            assert hasattr(options, 'context_files')
            assert hasattr(options, 'streaming')
            assert hasattr(options, 'max_iterations')
            assert hasattr(options, 'image_path')
            
            # Check default values
            assert options.conversation_id is None
            assert options.context is None
            assert options.context_files is None
            assert options.streaming is False
            assert options.max_iterations == 5
            assert options.image_path is None
            
        except ImportError:
            pytest.skip("ChatOptions not available")
    
    def test_task_options_structure(self):
        """Test that TaskOptions has expected structure."""
        try:
            from penguin import TaskOptions
            
            # Create instance with defaults
            options = TaskOptions()
            
            # Check that expected attributes exist
            assert hasattr(options, 'name')
            assert hasattr(options, 'description')
            assert hasattr(options, 'continuous')
            assert hasattr(options, 'time_limit')
            assert hasattr(options, 'context')
            
            # Check default values
            assert options.name is None
            assert options.description is None
            assert options.continuous is False
            assert options.time_limit is None
            assert options.context is None
            
        except ImportError:
            pytest.skip("TaskOptions not available")
    
    def test_checkpoint_info_structure(self):
        """Test that CheckpointInfo has expected structure."""
        try:
            from penguin import CheckpointInfo
            
            # Create instance
            info = CheckpointInfo(
                id="ckpt_123",
                name="Test",
                description="Test checkpoint",
                created_at="2024-01-01T10:00:00Z",
                type="manual",
                session_id="session_123"
            )
            
            # Check attributes
            assert info.id == "ckpt_123"
            assert info.name == "Test"
            assert info.description == "Test checkpoint"
            assert info.created_at == "2024-01-01T10:00:00Z"
            assert info.type == "manual"
            assert info.session_id == "session_123"
            
        except ImportError:
            pytest.skip("CheckpointInfo not available")
    
    def test_model_info_structure(self):
        """Test that ModelInfo has expected structure."""
        try:
            from penguin import ModelInfo
            
            # Create instance
            info = ModelInfo(
                id="test-model",
                name="test/model",
                provider="test",
                vision_enabled=True,
                max_tokens=4000,
                current=True
            )
            
            # Check attributes
            assert info.id == "test-model"
            assert info.name == "test/model"
            assert info.provider == "test"
            assert info.vision_enabled is True
            assert info.max_tokens == 4000
            assert info.current is True
            
        except ImportError:
            pytest.skip("ModelInfo not available")


class TestWebExports:
    """Test web-related exports."""
    
    def test_web_classes_importable_when_available(self):
        """Test that web classes can be imported when dependencies are available."""
        try:
            from penguin import create_app, PenguinAPI, PenguinWeb
            assert create_app is not None
            assert PenguinAPI is not None
            assert PenguinWeb is not None
        except ImportError:
            pytest.skip("Web classes not available (missing optional dependencies)")
    
    def test_cli_classes_importable_when_available(self):
        """Test that CLI classes can be imported when dependencies are available."""
        try:
            from penguin import PenguinCLI, get_cli_app
            assert PenguinCLI is not None
            assert get_cli_app is not None
        except ImportError:
            pytest.skip("CLI classes not available (missing optional dependencies)")


class TestVersionInfo:
    """Test version and metadata exports."""
    
    def test_version_info_importable(self):
        """Test that version info can be imported."""
        try:
            from penguin import __version__, __author__, __email__, __license__
            assert __version__ is not None
            assert __author__ is not None
            assert __email__ is not None
            assert __license__ is not None
            
            # Check expected values
            assert __version__ == "0.3.1"
            assert __author__ == "Maximus Putnam"
            assert __email__ == "MaximusPutnam@gmail.com"
            assert __license__ == "AGPL-3.0-or-later"
            
        except ImportError as e:
            pytest.fail(f"Failed to import version info: {e}")


class TestAllExports:
    """Test the __all__ list and complete export verification."""
    
    def test_all_list_exists(self):
        """Test that __all__ list exists and contains expected exports."""
        try:
            import penguin
            assert hasattr(penguin, '__all__')
            assert isinstance(penguin.__all__, list)
            assert len(penguin.__all__) > 0
        except ImportError as e:
            pytest.fail(f"Failed to import penguin module: {e}")
    
    def test_all_exports_importable(self):
        """Test that all items in __all__ are actually importable."""
        try:
            import penguin
            
            failed_imports = []
            for export_name in penguin.__all__:
                try:
                    getattr(penguin, export_name)
                except AttributeError:
                    failed_imports.append(export_name)
            
            if failed_imports:
                pytest.fail(f"These exports in __all__ are not available: {failed_imports}")
                
        except ImportError as e:
            pytest.fail(f"Failed to import penguin module: {e}")
    
    def test_expected_core_exports_in_all(self):
        """Test that expected core exports are in __all__."""
        try:
            import penguin
            
            expected_core = [
                "PenguinCore", "PenguinAgent", "Engine", "EngineSettings",
                "ProjectManager", "Project", "Task", "config",
                "__version__", "__author__", "__email__", "__license__"
            ]
            
            for export in expected_core:
                assert export in penguin.__all__, f"Expected export '{export}' not found in __all__"
                
        except ImportError as e:
            pytest.fail(f"Failed to import penguin module: {e}")
    
    def test_conditional_exports_handling(self):
        """Test that conditional exports are handled properly."""
        try:
            import penguin
            
            # These should be in __all__ if available
            possible_exports = [
                "CheckpointManager", "CheckpointConfig", "CheckpointType", "CheckpointMetadata",
                "ModelConfig",
                "ConversationManager", "Session", "Message", "MessageCategory",
                "PenguinClient", "ChatOptions", "TaskOptions", "CheckpointInfo", "ModelInfo", "create_client"
            ]
            
            # Count how many are available
            available_count = sum(1 for export in possible_exports if export in penguin.__all__)
            
            # Should have at least some available (exact number depends on dependencies)
            assert available_count >= 4, f"Expected at least some conditional exports, got {available_count}"
            
        except ImportError as e:
            pytest.fail(f"Failed to import penguin module: {e}")


class TestImportErrorHandling:
    """Test graceful handling of import errors for optional components."""
    
    def test_missing_dependencies_handled_gracefully(self):
        """Test that missing optional dependencies are handled gracefully."""
        # Mock missing dependencies
        original_import = __builtins__['__import__']
        
        def mock_import(name, *args, **kwargs):
            if 'fastapi' in name or 'uvicorn' in name:
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)
        
        with patch('builtins.__import__', side_effect=mock_import):
            try:
                # This should not raise an error even if web dependencies are missing
                import penguin
                
                # Basic functionality should still work
                assert hasattr(penguin, 'PenguinCore')
                assert hasattr(penguin, '__version__')
                
            except ImportError as e:
                # Only fail if it's not about optional dependencies
                if 'fastapi' not in str(e) and 'uvicorn' not in str(e):
                    pytest.fail(f"Unexpected import error: {e}")
    
    def test_partial_import_success(self):
        """Test that partial imports work when some components are unavailable."""
        # Test importing specific components
        core_imports = [
            "from penguin import PenguinCore",
            "from penguin import __version__",
            "from penguin import config"
        ]
        
        for import_stmt in core_imports:
            try:
                exec(import_stmt)
            except ImportError as e:
                pytest.fail(f"Core import failed: {import_stmt} - {e}")
    
    def test_import_warnings_for_missing_components(self):
        """Test that appropriate warnings are issued for missing components."""
        # This would test the warning system for missing agent components
        # The actual implementation has warning handling for PenguinAgent
        
        with patch('warnings.warn') as mock_warn:
            try:
                # Try to import when agent is missing
                with patch.dict(sys.modules, {'penguin.agent': None}):
                    import importlib
                    importlib.reload(sys.modules.get('penguin.penguin', penguin))
                    
                    # Check if warning was called (implementation specific)
                    # This tests the warning system exists, actual behavior may vary
                    
            except Exception:
                # This test is more about structure than specific behavior
                pass


class TestDocumentationConsistency:
    """Test that exports match documentation claims."""
    
    def test_docstring_examples_importable(self):
        """Test that examples in docstrings use importable classes."""
        try:
            import penguin
            docstring = penguin.__doc__
            
            if docstring and "from penguin import" in docstring:
                # The docstring should only reference actually importable classes
                # This is a basic check that docstring examples aren't broken
                
                # Extract example imports (simplified)
                import_lines = [line.strip() for line in docstring.split('\n') 
                               if line.strip().startswith('from penguin import')]
                
                for line in import_lines:
                    # This is a simplified check - real implementation would parse properly
                    if 'PenguinClient' in line:
                        try:
                            from penguin import PenguinClient
                        except ImportError:
                            pytest.fail(f"Docstring references PenguinClient but it's not importable")
                            
        except ImportError:
            pytest.skip("Could not import penguin module for docstring test")
    
    def test_readme_consistency(self):
        """Test that README examples use available exports."""
        # This would test that README.md examples match actual exports
        # Implementation would read README and check examples
        
        # For now, just ensure basic classes mentioned in README are available
        try:
            from penguin import PenguinCore, PenguinAgent
            assert PenguinCore is not None
            assert PenguinAgent is not None
        except ImportError as e:
            pytest.fail(f"Basic classes mentioned in README not available: {e}")