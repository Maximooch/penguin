"""
Plugin-based Tool Manager for Penguin.

This is the new ToolManager that uses the plugin system for dynamic tool
discovery and execution, replacing the static tool registration.
"""

import logging
import asyncio
from typing import Any, Dict, List, Optional, Union
from pathlib import Path

from penguin.config import config, WORKSPACE_PATH
from penguin.plugins import PluginManager, BasePlugin, ToolDefinition
from penguin.utils.profiling import profile_operation

logger = logging.getLogger(__name__)


class PluginToolManager:
    """
    Plugin-based tool manager that replaces the static ToolManager.
    
    This manager uses the plugin system for dynamic tool discovery and execution,
    providing better extensibility and modularity.
    """
    
    def __init__(self, plugin_dirs: Optional[List[Union[str, Path]]] = None):
        """
        Initialize the plugin-based tool manager.
        
        Args:
            plugin_dirs: Additional plugin directories to search
        """
        self.logger = logging.getLogger(__name__)
        
        # Default plugin directories
        default_plugin_dirs = [
            Path(__file__).parent / "plugins",  # Built-in plugins
            Path(WORKSPACE_PATH) / "plugins" if WORKSPACE_PATH else None,  # Workspace plugins
            Path.home() / ".penguin" / "plugins",  # User plugins
        ]
        
        # Filter out None values and combine with custom dirs
        all_plugin_dirs = [d for d in default_plugin_dirs if d is not None]
        if plugin_dirs:
            all_plugin_dirs.extend(plugin_dirs)
        
        # Initialize plugin manager
        self.plugin_manager = PluginManager(
            plugin_dirs=all_plugin_dirs,
            config=config.get('plugins', {}) if hasattr(config, 'get') else getattr(config, 'plugins', {})
        )
        
        # Load built-in tools as fallback
        self._legacy_tool_manager = None
        
        # Initialize plugins
        self._initialize_plugins()
    
    def _initialize_plugins(self):
        """Initialize the plugin system and load plugins"""
        try:
            with profile_operation("PluginToolManager.initialize_plugins"):
                # Discover and load all plugins
                discovered = self.plugin_manager.discover_plugins()
                self.logger.info(f"Discovered {len(discovered)} plugins")
                
                # Load plugins in parallel for better performance
                load_results = self.plugin_manager.load_all_plugins(parallel=True)
                
                successful_loads = sum(1 for success in load_results.values() if success)
                self.logger.info(f"Successfully loaded {successful_loads} of {len(load_results)} plugins")
                
                # Log any failed loads
                for plugin_name, success in load_results.items():
                    if not success:
                        self.logger.warning(f"Failed to load plugin: {plugin_name}")
        
        except Exception as e:
            self.logger.error(f"Error initializing plugins: {e}")
            # Continue without plugins - fall back to legacy tools
    
    def get_available_tools(self) -> Dict[str, ToolDefinition]:
        """Get all available tools from loaded plugins"""
        with profile_operation("PluginToolManager.get_available_tools"):
            return self.plugin_manager.get_available_tools()
    
    def get_tools_by_category(self, category: str) -> Dict[str, ToolDefinition]:
        """Get tools filtered by category"""
        with profile_operation(f"PluginToolManager.get_tools_by_category.{category}"):
            return self.plugin_manager.get_tools_by_category(category)
    
    def get_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """
        Get the schema for a specific tool.
        
        Args:
            tool_name: Name of the tool
            
        Returns:
            Tool schema dictionary or None if not found
        """
        tools = self.get_available_tools()
        tool = tools.get(tool_name)
        
        if not tool:
            return None
        
        # Convert ToolDefinition to schema format expected by the system
        schema = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
        
        # Convert parameters to JSON schema format
        for param in tool.parameters:
            schema["input_schema"]["properties"][param.name] = {
                "type": param.type,
                "description": param.description
            }
            
            if param.enum_values:
                schema["input_schema"]["properties"][param.name]["enum"] = param.enum_values
            
            if param.default is not None:
                schema["input_schema"]["properties"][param.name]["default"] = param.default
            
            if param.required:
                schema["input_schema"]["required"].append(param.name)
        
        return schema
    
    def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Union[str, dict]:
        """
        Execute a tool by name.
        
        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool
            
        Returns:
            Tool execution result
        """
        with profile_operation(f"PluginToolManager.execute_tool.{tool_name}"):
            try:
                # Try to execute through plugin system first
                result = self.plugin_manager.execute_tool(tool_name, tool_input)
                self.logger.debug(f"Successfully executed plugin tool: {tool_name}")
                return result
                
            except ValueError as e:
                # Tool not found in plugin system, try legacy fallback
                if "not found" in str(e).lower():
                    return self._execute_legacy_tool(tool_name, tool_input)
                else:
                    # Parameter validation or other error
                    raise
            
            except Exception as e:
                self.logger.error(f"Error executing tool {tool_name}: {e}")
                raise
    
    def _execute_legacy_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Union[str, dict]:
        """
        Fallback to legacy tool execution for backward compatibility.
        
        This method handles tools that haven't been migrated to plugins yet.
        """
        # Lazy load legacy tool manager only when needed
        if self._legacy_tool_manager is None:
            try:
                from penguin.tools.tool_manager import ToolManager
                self._legacy_tool_manager = ToolManager()
                self.logger.debug("Loaded legacy ToolManager for fallback")
            except Exception as e:
                self.logger.error(f"Failed to load legacy ToolManager: {e}")
                raise ValueError(f"Tool {tool_name} not found and legacy fallback unavailable")
        
        try:
            result = self._legacy_tool_manager.execute_tool(tool_name, tool_input)
            self.logger.warning(f"Executed tool {tool_name} via legacy fallback - consider migrating to plugin")
            return result
        except Exception as e:
            raise ValueError(f"Tool {tool_name} not found in plugin system or legacy fallback")
    
    def list_tools(self) -> List[str]:
        """List all available tool names"""
        tools = self.get_available_tools()
        return list(tools.keys())
    
    def list_plugins(self) -> List[str]:
        """List all loaded plugin names"""
        return self.plugin_manager.list_plugins()
    
    def get_plugin_info(self, plugin_name: str) -> Optional[BasePlugin]:
        """Get information about a loaded plugin"""
        return self.plugin_manager.get_plugin(plugin_name)
    
    def reload_plugin(self, plugin_name: str) -> bool:
        """Reload a specific plugin"""
        return self.plugin_manager.reload_plugin(plugin_name)
    
    def load_plugin(self, plugin_name: str) -> bool:
        """Load a specific plugin"""
        return self.plugin_manager.load_plugin(plugin_name)
    
    def unload_plugin(self, plugin_name: str) -> bool:
        """Unload a specific plugin"""
        return self.plugin_manager.unload_plugin(plugin_name)
    
    def enable_plugin(self, plugin_name: str) -> bool:
        """Enable a disabled plugin"""
        return self.plugin_manager.enable_plugin(plugin_name)
    
    def disable_plugin(self, plugin_name: str) -> bool:
        """Disable a plugin"""
        return self.plugin_manager.disable_plugin(plugin_name)
    
    def get_tool_categories(self) -> List[str]:
        """Get list of all available tool categories"""
        tools = self.get_available_tools()
        categories = set()
        for tool in tools.values():
            categories.add(tool.category)
        return sorted(list(categories))
    
    def search_tools(self, query: str, category: Optional[str] = None) -> Dict[str, ToolDefinition]:
        """
        Search for tools by name, description, or tags.
        
        Args:
            query: Search query
            category: Optional category filter
            
        Returns:
            Dictionary of matching tools
        """
        tools = self.get_available_tools()
        if category:
            tools = {name: tool for name, tool in tools.items() if tool.category == category}
        
        query_lower = query.lower()
        matches = {}
        
        for name, tool in tools.items():
            # Search in name, description, and tags
            if (query_lower in name.lower() or 
                query_lower in tool.description.lower() or
                any(query_lower in tag.lower() for tag in tool.tags)):
                matches[name] = tool
        
        return matches
    
    def validate_tool_input(self, tool_name: str, tool_input: Dict[str, Any]) -> bool:
        """
        Validate tool input parameters.
        
        Args:
            tool_name: Name of the tool
            tool_input: Input parameters to validate
            
        Returns:
            True if input is valid, False otherwise
        """
        tools = self.get_available_tools()
        tool = tools.get(tool_name)
        
        if not tool:
            return False
        
        try:
            # Get the plugin that owns this tool and validate parameters
            plugin = self.plugin_manager.tool_registry.get(tool_name)
            if plugin:
                plugin._validate_parameters(tool.parameters, tool_input)
                return True
        except Exception as e:
            self.logger.debug(f"Tool input validation failed for {tool_name}: {e}")
            return False
        
        return False
    
    def get_tool_help(self, tool_name: str) -> Optional[str]:
        """Get help text for a specific tool"""
        tools = self.get_available_tools()
        tool = tools.get(tool_name)
        
        if not tool:
            return None
        
        help_text = f"Tool: {tool.name}\n"
        help_text += f"Description: {tool.description}\n"
        help_text += f"Category: {tool.category}\n"
        
        if tool.parameters:
            help_text += "\nParameters:\n"
            for param in tool.parameters:
                help_text += f"  - {param.name} ({param.type}): {param.description}"
                if param.required:
                    help_text += " [REQUIRED]"
                if param.default is not None:
                    help_text += f" [default: {param.default}]"
                help_text += "\n"
        
        if tool.examples:
            help_text += "\nExamples:\n"
            for example in tool.examples:
                help_text += f"  - {example}\n"
        
        return help_text
    
    def shutdown(self):
        """Shutdown the plugin tool manager"""
        self.logger.info("Shutting down PluginToolManager")
        self.plugin_manager.shutdown()
        
        if self._legacy_tool_manager:
            # If legacy tool manager has shutdown method, call it
            if hasattr(self._legacy_tool_manager, 'shutdown'):
                self._legacy_tool_manager.shutdown()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()