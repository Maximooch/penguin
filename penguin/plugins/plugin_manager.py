"""
Plugin Manager for Penguin's dynamic plugin system.

Handles plugin lifecycle management, loading, unloading, and provides
a centralized interface for plugin operations.
"""

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Any, Type, Callable, Union
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .base_plugin import BasePlugin, PluginMetadata, PluginStatus, ToolDefinition, ActionDefinition
from .discovery import PluginDiscovery
from .decorators import get_tools_from_module, get_actions_from_module, clear_registrations

logger = logging.getLogger(__name__)


class PluginLoadError(Exception):
    """Exception raised when a plugin fails to load"""
    pass


class PluginManager:
    """
    Manages the lifecycle of plugins in Penguin.
    
    Handles plugin discovery, loading, unloading, and provides access
    to plugin tools and actions.
    """
    
    def __init__(self, 
                 plugin_dirs: Optional[List[Union[str, Path]]] = None,
                 config: Optional[Dict[str, Any]] = None):
        """
        Initialize the plugin manager.
        
        Args:
            plugin_dirs: List of directories to search for plugins
            config: Global plugin configuration
        """
        self.plugin_dirs = plugin_dirs or []
        self.config = config or {}
        
        # Plugin storage
        self.loaded_plugins: Dict[str, BasePlugin] = {}
        self.plugin_configs: Dict[str, Dict[str, Any]] = {}
        self.disabled_plugins: Set[str] = set(self.config.get('disabled_plugins', []))
        
        # Discovery system
        self.discovery = PluginDiscovery(plugin_dirs)
        
        # Tool and action registries
        self.tool_registry: Dict[str, BasePlugin] = {}  # tool_name -> plugin
        self.action_registry: Dict[str, BasePlugin] = {}  # action_name -> plugin
        
        # Thread safety
        self._lock = threading.RLock()
        
        # Plugin dependency resolution
        self.dependency_graph: Dict[str, Set[str]] = {}
        
    def discover_plugins(self) -> Dict[str, Dict[str, Any]]:
        """Discover all available plugins"""
        with self._lock:
            return self.discovery.discover_all()
    
    def load_all_plugins(self, parallel: bool = True) -> Dict[str, bool]:
        """
        Load all discovered plugins.
        
        Args:
            parallel: Whether to load plugins in parallel
            
        Returns:
            Dictionary mapping plugin names to load success status
        """
        with self._lock:
            discovered = self.discovery.discover_all()
            results = {}
            
            if parallel and len(discovered) > 1:
                results = self._load_plugins_parallel(discovered)
            else:
                for plugin_name in discovered:
                    results[plugin_name] = self.load_plugin(plugin_name)
            
            logger.info(f"Loaded {sum(results.values())} of {len(results)} plugins")
            return results
    
    def _load_plugins_parallel(self, discovered_plugins: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
        """Load plugins in parallel using ThreadPoolExecutor"""
        results = {}
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            # Submit all plugin load tasks
            future_to_name = {
                executor.submit(self.load_plugin, name): name 
                for name in discovered_plugins
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_name):
                plugin_name = future_to_name[future]
                try:
                    results[plugin_name] = future.result()
                except Exception as e:
                    logger.error(f"Error loading plugin {plugin_name}: {e}")
                    results[plugin_name] = False
        
        return results
    
    def load_plugin(self, plugin_name: str) -> bool:
        """
        Load a specific plugin.
        
        Args:
            plugin_name: Name of the plugin to load
            
        Returns:
            True if plugin loaded successfully, False otherwise
        """
        if plugin_name in self.disabled_plugins:
            logger.debug(f"Plugin {plugin_name} is disabled, skipping")
            return False
        
        if plugin_name in self.loaded_plugins:
            logger.debug(f"Plugin {plugin_name} is already loaded")
            return True
        
        try:
            plugin_info = self.discovery.get_plugin_info(plugin_name)
            if not plugin_info:
                raise PluginLoadError(f"Plugin {plugin_name} not found in discovery")
            
            # Create and load the plugin
            plugin = self._create_plugin_instance(plugin_info)
            
            # Set status to loading
            plugin.set_status(PluginStatus.LOADING)
            
            # Initialize the plugin
            if not plugin.initialize():
                raise PluginLoadError(f"Plugin {plugin_name} initialization failed")
            
            # Register the plugin
            with self._lock:
                self.loaded_plugins[plugin_name] = plugin
                self._register_plugin_tools_and_actions(plugin)
            
            plugin.set_status(PluginStatus.ACTIVE)
            logger.info(f"Successfully loaded plugin: {plugin_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load plugin {plugin_name}: {e}")
            logger.debug(traceback.format_exc())
            return False
    
    def _create_plugin_instance(self, plugin_info: Dict[str, Any]) -> BasePlugin:
        """Create a plugin instance from plugin info"""
        source_type = plugin_info.get('source_type')
        plugin_name = plugin_info['name']
        
        if source_type == 'directory':
            return self._load_directory_plugin(plugin_info)
        elif source_type == 'file':
            return self._load_file_plugin(plugin_info)
        elif source_type == 'entry_point':
            return self._load_entry_point_plugin(plugin_info)
        else:
            raise PluginLoadError(f"Unsupported plugin source type: {source_type}")
    
    def _load_directory_plugin(self, plugin_info: Dict[str, Any]) -> BasePlugin:
        """Load a plugin from a directory with manifest"""
        # Load module
        module_file = plugin_info.get('module_file')
        module_name = plugin_info.get('module_name', 'main')
        
        if not module_file:
            raise PluginLoadError("No module file specified")
        
        spec = importlib.util.spec_from_file_location(module_name, module_file)
        if not spec or not spec.loader:
            raise PluginLoadError(f"Could not load module spec for {module_file}")
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Create plugin metadata
        metadata = self.discovery.create_metadata_from_info(plugin_info)
        
        # Look for plugin class
        class_name = plugin_info.get('class_name')
        if class_name:
            if not hasattr(module, class_name):
                raise PluginLoadError(f"Plugin class {class_name} not found in module")
            plugin_class = getattr(module, class_name)
            if not issubclass(plugin_class, BasePlugin):
                raise PluginLoadError(f"Plugin class {class_name} does not inherit from BasePlugin")
            
            plugin_config = self.plugin_configs.get(plugin_info['name'], {})
            return plugin_class(metadata, plugin_config)
        else:
            # Create a dynamic plugin from decorated functions
            return self._create_dynamic_plugin(metadata, module)
    
    def _load_file_plugin(self, plugin_info: Dict[str, Any]) -> BasePlugin:
        """Load a plugin from a single Python file"""
        module_file = plugin_info.get('module_file')
        module_name = plugin_info.get('module_name')
        
        if not module_file:
            raise PluginLoadError("No module file specified")
        
        # Load the module
        spec = importlib.util.spec_from_file_location(module_name, module_file)
        if not spec or not spec.loader:
            raise PluginLoadError(f"Could not load module spec for {module_file}")
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Check for plugin classes first
        plugin_classes = plugin_info.get('plugin_classes', [])
        if plugin_classes:
            # Use the first plugin class found
            plugin_class = plugin_classes[0]
            metadata = PluginMetadata(
                name=plugin_info['name'],
                version="1.0.0",
                description=f"File plugin: {plugin_info['name']}"
            )
            plugin_config = self.plugin_configs.get(plugin_info['name'], {})
            return plugin_class(metadata, plugin_config)
        else:
            # Create dynamic plugin from decorated functions
            metadata = PluginMetadata(
                name=plugin_info['name'],
                version="1.0.0", 
                description=f"Dynamic plugin: {plugin_info['name']}"
            )
            return self._create_dynamic_plugin(metadata, module)
    
    def _load_entry_point_plugin(self, plugin_info: Dict[str, Any]) -> BasePlugin:
        """Load a plugin from setuptools entry point"""
        entry_point = plugin_info.get('entry_point')
        if not entry_point:
            raise PluginLoadError("No entry point specified")
        
        try:
            plugin_class = entry_point.load()
            if not issubclass(plugin_class, BasePlugin):
                raise PluginLoadError(f"Entry point does not return a BasePlugin subclass")
            
            metadata = PluginMetadata(
                name=plugin_info['name'],
                version="1.0.0",
                description=f"Entry point plugin: {plugin_info['name']}"
            )
            plugin_config = self.plugin_configs.get(plugin_info['name'], {})
            return plugin_class(metadata, plugin_config)
            
        except Exception as e:
            raise PluginLoadError(f"Failed to load entry point: {e}")
    
    def _create_dynamic_plugin(self, metadata: PluginMetadata, module) -> BasePlugin:
        """Create a dynamic plugin from decorated functions in a module"""
        # Get tools and actions from the module
        tools = get_tools_from_module(module.__name__)
        actions = get_actions_from_module(module.__name__)
        
        class DynamicPlugin(BasePlugin):
            def initialize(self) -> bool:
                # Register all discovered tools and actions
                for tool in tools:
                    self.register_tool(tool)
                for action in actions:
                    self.register_action(action)
                return True
            
            def cleanup(self) -> None:
                pass
        
        return DynamicPlugin(metadata)
    
    def _register_plugin_tools_and_actions(self, plugin: BasePlugin) -> None:
        """Register all tools and actions from a plugin"""
        # Register tools
        for tool_name, tool in plugin.get_tools().items():
            if tool_name in self.tool_registry:
                existing_plugin = self.tool_registry[tool_name]
                logger.warning(f"Tool {tool_name} already registered by plugin {existing_plugin.metadata.name}, overriding")
            
            self.tool_registry[tool_name] = plugin
            logger.debug(f"Registered tool {tool_name} from plugin {plugin.metadata.name}")
        
        # Register actions  
        for action_name, action in plugin.get_actions().items():
            if action_name in self.action_registry:
                existing_plugin = self.action_registry[action_name]
                logger.warning(f"Action {action_name} already registered by plugin {existing_plugin.metadata.name}, overriding")
            
            self.action_registry[action_name] = plugin
            logger.debug(f"Registered action {action_name} from plugin {plugin.metadata.name}")
    
    def unload_plugin(self, plugin_name: str) -> bool:
        """
        Unload a specific plugin.
        
        Args:
            plugin_name: Name of the plugin to unload
            
        Returns:
            True if plugin unloaded successfully, False otherwise
        """
        with self._lock:
            if plugin_name not in self.loaded_plugins:
                logger.debug(f"Plugin {plugin_name} is not loaded")
                return False
            
            try:
                plugin = self.loaded_plugins[plugin_name]
                
                # Cleanup plugin
                plugin.cleanup()
                plugin.set_status(PluginStatus.UNLOADED)
                
                # Unregister tools and actions
                self._unregister_plugin_tools_and_actions(plugin)
                
                # Remove from loaded plugins
                del self.loaded_plugins[plugin_name]
                
                logger.info(f"Successfully unloaded plugin: {plugin_name}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to unload plugin {plugin_name}: {e}")
                return False
    
    def _unregister_plugin_tools_and_actions(self, plugin: BasePlugin) -> None:
        """Unregister tools and actions from a plugin"""
        plugin_name = plugin.metadata.name
        
        # Unregister tools
        tools_to_remove = []
        for tool_name, registered_plugin in self.tool_registry.items():
            if registered_plugin.metadata.name == plugin_name:
                tools_to_remove.append(tool_name)
        
        for tool_name in tools_to_remove:
            del self.tool_registry[tool_name]
            logger.debug(f"Unregistered tool {tool_name} from plugin {plugin_name}")
        
        # Unregister actions
        actions_to_remove = []
        for action_name, registered_plugin in self.action_registry.items():
            if registered_plugin.metadata.name == action_name:
                actions_to_remove.append(action_name)
        
        for action_name in actions_to_remove:
            del self.action_registry[action_name]
            logger.debug(f"Unregistered action {action_name} from plugin {plugin_name}")
    
    def reload_plugin(self, plugin_name: str) -> bool:
        """
        Reload a plugin (unload then load).
        
        Args:
            plugin_name: Name of the plugin to reload
            
        Returns:
            True if plugin reloaded successfully, False otherwise
        """
        logger.info(f"Reloading plugin: {plugin_name}")
        
        # Unload if currently loaded
        if plugin_name in self.loaded_plugins:
            if not self.unload_plugin(plugin_name):
                return False
        
        # Load again
        return self.load_plugin(plugin_name)
    
    def get_plugin(self, plugin_name: str) -> Optional[BasePlugin]:
        """Get a loaded plugin by name"""
        return self.loaded_plugins.get(plugin_name)
    
    def list_plugins(self) -> List[str]:
        """List all loaded plugin names"""
        return list(self.loaded_plugins.keys())
    
    def get_plugin_status(self, plugin_name: str) -> Optional[PluginStatus]:
        """Get the status of a plugin"""
        plugin = self.loaded_plugins.get(plugin_name)
        return plugin.get_status() if plugin else None
    
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Any:
        """Execute a tool by name"""
        plugin = self.tool_registry.get(tool_name)
        if not plugin:
            raise ValueError(f"Tool {tool_name} not found")
        
        return plugin.execute_tool(tool_name, parameters)
    
    def execute_action(self, action_name: str, context: Dict[str, Any]) -> Any:
        """Execute an action by name"""
        plugin = self.action_registry.get(action_name)
        if not plugin:
            raise ValueError(f"Action {action_name} not found")
        
        return plugin.execute_action(action_name, context)
    
    def get_available_tools(self) -> Dict[str, ToolDefinition]:
        """Get all available tools from loaded plugins"""
        tools = {}
        for plugin in self.loaded_plugins.values():
            tools.update(plugin.get_tools())
        return tools
    
    def get_available_actions(self) -> Dict[str, ActionDefinition]:
        """Get all available actions from loaded plugins"""
        actions = {}
        for plugin in self.loaded_plugins.values():
            actions.update(plugin.get_actions())
        return actions
    
    def get_tools_by_category(self, category: str) -> Dict[str, ToolDefinition]:
        """Get tools filtered by category"""
        tools = {}
        for plugin in self.loaded_plugins.values():
            for tool_name, tool in plugin.get_tools().items():
                if tool.category == category:
                    tools[tool_name] = tool
        return tools
    
    def set_plugin_config(self, plugin_name: str, config: Dict[str, Any]) -> None:
        """Set configuration for a plugin"""
        self.plugin_configs[plugin_name] = config
        
        # Update config for loaded plugin if it exists
        if plugin_name in self.loaded_plugins:
            plugin = self.loaded_plugins[plugin_name]
            plugin.config.update(config)
    
    def enable_plugin(self, plugin_name: str) -> bool:
        """Enable a disabled plugin"""
        if plugin_name in self.disabled_plugins:
            self.disabled_plugins.remove(plugin_name)
            return self.load_plugin(plugin_name)
        return True
    
    def disable_plugin(self, plugin_name: str) -> bool:
        """Disable a plugin"""
        self.disabled_plugins.add(plugin_name)
        if plugin_name in self.loaded_plugins:
            return self.unload_plugin(plugin_name)
        return True
    
    def shutdown(self) -> None:
        """Shutdown the plugin manager and unload all plugins"""
        logger.info("Shutting down plugin manager")
        
        with self._lock:
            # Unload all plugins
            plugin_names = list(self.loaded_plugins.keys())
            for plugin_name in plugin_names:
                try:
                    self.unload_plugin(plugin_name)
                except Exception as e:
                    logger.error(f"Error unloading plugin {plugin_name} during shutdown: {e}")
            
            # Clear registries
            self.tool_registry.clear()
            self.action_registry.clear()
            clear_registrations()  # Clear decorator registrations
        
        logger.info("Plugin manager shutdown complete")