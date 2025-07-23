"""
Configuration management for Penguin.

This package provides configuration support for both the core system
and the plugin architecture.
"""

# Import everything from the original config module to maintain compatibility
import sys
from pathlib import Path

# Add the parent directory to sys.path to import the original config
config_parent = Path(__file__).parent.parent
if str(config_parent) not in sys.path:
    sys.path.insert(0, str(config_parent))

# Import all the original config items
try:
    from config import *  # noqa: F403, F401
except ImportError:
    # If direct import fails, try the full module path
    try:
        from penguin.config import *  # noqa: F403, F401
    except ImportError:
        # If that fails too, import from the .py file directly
        import importlib.util
        config_file = Path(__file__).parent.parent / "config.py"
        spec = importlib.util.spec_from_file_location("config", config_file)
        if spec and spec.loader:
            config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_module)
            # Import all public attributes
            for attr_name in dir(config_module):
                if not attr_name.startswith('_'):
                    globals()[attr_name] = getattr(config_module, attr_name)

# Now import the plugin-specific configuration
from .plugin_config import (
    PluginSettings,
    PluginSystemConfig, 
    PluginConfigManager,
    get_plugin_config_manager,
    get_plugin_config,
    create_default_plugin_config
)

# Update __all__ to include both original config items and plugin config
__all__ = [
    # Plugin configuration
    'PluginSettings',
    'PluginSystemConfig',
    'PluginConfigManager', 
    'get_plugin_config_manager',
    'get_plugin_config',
    'create_default_plugin_config'
    # Note: Original config items are imported with * so they're automatically available
]