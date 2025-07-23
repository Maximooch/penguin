#!/usr/bin/env python3
"""
Plugin System Validation Script

This script validates the plugin system by testing core functionality,
discovering plugins, and verifying the integration works correctly.
"""

import sys
import logging
from pathlib import Path
from typing import List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from penguin.plugins import (
    BasePlugin, PluginMetadata, ToolDefinition, ParameterSchema,
    PluginManager, PluginDiscovery, register_tool
)
from penguin.plugin_config_module.plugin_config import get_plugin_config_manager
from penguin.tools.plugin_tool_manager import PluginToolManager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ValidationPlugin(BasePlugin):
    """Test plugin for validation"""
    
    def initialize(self) -> bool:
        logger.info(f"Initializing validation plugin: {self.metadata.name}")
        
        # Register a test tool
        tool = ToolDefinition(
            name="validation_test",
            description="Validation test tool",
            parameters=[
                ParameterSchema(
                    name="message",
                    type="string", 
                    description="Test message",
                    required=True
                )
            ],
            handler=self._test_handler,
            category="validation"
        )
        self.register_tool(tool)
        
        return True
    
    def cleanup(self) -> None:
        logger.info(f"Cleaning up validation plugin: {self.metadata.name}")
    
    def _test_handler(self, message: str) -> str:
        return f"Validation plugin received: {message}"


def validate_plugin_metadata():
    """Validate plugin metadata functionality"""
    logger.info("=== Validating Plugin Metadata ===")
    
    try:
        # Test valid metadata
        metadata = PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            description="Test plugin for validation",
            author="Validation Script",
            permissions=["filesystem.read", "network.request"]
        )
        logger.info(f"✓ Created metadata for plugin: {metadata.name}")
        
        # Test metadata validation
        try:
            invalid_metadata = PluginMetadata(name="", version="1.0.0", description="Invalid")
            logger.error("✗ Metadata validation failed - should have raised exception")
            return False
        except ValueError:
            logger.info("✓ Metadata validation works correctly")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Plugin metadata validation failed: {e}")
        return False


def validate_base_plugin():
    """Validate base plugin functionality"""
    logger.info("=== Validating Base Plugin ===")
    
    try:
        metadata = PluginMetadata(
            name="validation_plugin",
            version="1.0.0",
            description="Validation test plugin"
        )
        
        plugin = ValidationPlugin(metadata)
        logger.info("✓ Created validation plugin instance")
        
        # Test initialization
        if not plugin.initialize():
            logger.error("✗ Plugin initialization failed")
            return False
        logger.info("✓ Plugin initialized successfully")
        
        # Test tool registration
        tools = plugin.get_tools()
        if "validation_test" not in tools:
            logger.error("✗ Tool registration failed")
            return False
        logger.info("✓ Tool registered successfully")
        
        # Test tool execution
        result = plugin.execute_tool("validation_test", {"message": "Hello, World!"})
        if "Hello, World!" not in result:
            logger.error(f"✗ Tool execution failed: {result}")
            return False
        logger.info("✓ Tool executed successfully")
        
        # Test cleanup
        plugin.cleanup()
        logger.info("✓ Plugin cleanup completed")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Base plugin validation failed: {e}")
        return False


def validate_plugin_discovery():
    """Validate plugin discovery functionality"""
    logger.info("=== Validating Plugin Discovery ===")
    
    try:
        # Test discovery with current directory
        current_dir = Path.cwd()
        discovery = PluginDiscovery([current_dir / "penguin" / "tools" / "plugins"])
        
        discovered = discovery.discover_all()
        logger.info(f"✓ Discovered {len(discovered)} plugins")
        
        for name, info in discovered.items():
            logger.info(f"  - {name}: {info.get('source_type', 'unknown')}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Plugin discovery validation failed: {e}")
        return False


def validate_plugin_manager():
    """Validate plugin manager functionality"""
    logger.info("=== Validating Plugin Manager ===")
    
    try:
        # Create plugin manager with current directory
        current_dir = Path.cwd()
        plugin_dirs = [current_dir / "penguin" / "tools" / "plugins"]
        
        manager = PluginManager(plugin_dirs)
        logger.info("✓ Created plugin manager")
        
        # Test plugin discovery
        discovered = manager.discover_plugins()
        logger.info(f"✓ Manager discovered {len(discovered)} plugins")
        
        # Test loading plugins (may fail if plugins have import issues)
        try:
            load_results = manager.load_all_plugins()
            successful_loads = sum(1 for success in load_results.values() if success)
            logger.info(f"✓ Manager loaded {successful_loads} of {len(load_results)} plugins")
        except Exception as e:
            logger.warning(f"Plugin loading encountered issues: {e}")
        
        # Test available tools
        tools = manager.get_available_tools()
        logger.info(f"✓ Manager provides {len(tools)} tools")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Plugin manager validation failed: {e}")
        return False


def validate_plugin_tool_manager():
    """Validate plugin tool manager functionality"""
    logger.info("=== Validating Plugin Tool Manager ===")
    
    try:
        # Create plugin tool manager
        current_dir = Path.cwd()
        plugin_dirs = [current_dir / "penguin" / "tools" / "plugins"]
        
        tool_manager = PluginToolManager(plugin_dirs)
        logger.info("✓ Created plugin tool manager")
        
        # Test available tools
        tools = tool_manager.get_available_tools()
        logger.info(f"✓ Tool manager provides {len(tools)} tools")
        
        # Test tool categories
        categories = tool_manager.get_tool_categories()
        logger.info(f"✓ Available tool categories: {categories}")
        
        # Test tool listing
        tool_names = tool_manager.list_tools()
        logger.info(f"✓ Available tools: {tool_names[:5]}..." if len(tool_names) > 5 else f"✓ Available tools: {tool_names}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Plugin tool manager validation failed: {e}")
        return False


def validate_plugin_config():
    """Validate plugin configuration system"""
    logger.info("=== Validating Plugin Configuration ===")
    
    try:
        # Test config manager
        config_manager = get_plugin_config_manager()
        config = config_manager.get_config()
        logger.info("✓ Created plugin configuration manager")
        
        # Test plugin enable/disable
        config.enable_plugin("test_plugin")
        if not config.is_plugin_enabled("test_plugin"):
            logger.error("✗ Plugin enable failed")
            return False
        logger.info("✓ Plugin enable works")
        
        config.disable_plugin("test_plugin")
        if config.is_plugin_enabled("test_plugin"):
            logger.error("✗ Plugin disable failed")
            return False
        logger.info("✓ Plugin disable works")
        
        # Test plugin directories
        plugin_dirs = config.get_resolved_plugin_directories(Path.cwd())
        logger.info(f"✓ Resolved plugin directories: {[str(d) for d in plugin_dirs]}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Plugin configuration validation failed: {e}")
        return False


def validate_decorators():
    """Validate plugin decorator functionality"""
    logger.info("=== Validating Plugin Decorators ===")
    
    try:
        from penguin.plugins.decorators import clear_registrations, get_registered_tools
        
        # Clear existing registrations
        clear_registrations()
        
        @register_tool(
            name="decorated_validation_tool",
            description="Tool created with decorator",
            parameters=[{"name": "input", "type": "string", "description": "Test input", "required": True}]
        )
        def validation_tool(input: str) -> str:
            return f"Decorated tool result: {input}"
        
        # Check registration
        registered = get_registered_tools()
        if "decorated_validation_tool" not in registered:
            logger.error("✗ Tool decorator registration failed")
            return False
        logger.info("✓ Tool decorator registration works")
        
        # Test function execution
        result = validation_tool("test")
        if "test" not in result:
            logger.error("✗ Decorated function execution failed")
            return False
        logger.info("✓ Decorated function execution works")
        
        # Clear registrations
        clear_registrations()
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Plugin decorators validation failed: {e}")
        return False


def run_all_validations() -> bool:
    """Run all validation tests"""
    logger.info("Starting Penguin Plugin System Validation")
    logger.info("=" * 50)
    
    validations = [
        validate_plugin_metadata,
        validate_base_plugin,
        validate_plugin_discovery,
        validate_plugin_manager,
        validate_plugin_tool_manager,
        validate_plugin_config,
        validate_decorators
    ]
    
    results = []
    for validation in validations:
        try:
            result = validation()
            results.append(result)
        except Exception as e:
            logger.error(f"Validation {validation.__name__} crashed: {e}")
            results.append(False)
        logger.info("")  # Add spacing
    
    # Summary
    passed = sum(results)
    total = len(results)
    
    logger.info("=" * 50)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 50)
    logger.info(f"Passed: {passed}/{total}")
    logger.info(f"Failed: {total - passed}/{total}")
    
    if passed == total:
        logger.info("🎉 All validations passed! Plugin system is working correctly.")
        return True
    else:
        logger.error("❌ Some validations failed. Please check the errors above.")
        return False


if __name__ == "__main__":
    success = run_all_validations()
    sys.exit(0 if success else 1)