"""
Penguin Plugin System

This module provides the core plugin architecture for Penguin, enabling
dynamic tool discovery and registration through a standardized plugin interface.
"""

from .base_plugin import BasePlugin, PluginMetadata, ToolDefinition, ActionDefinition, ParameterSchema
from .plugin_manager import PluginManager
from .decorators import register_tool, register_action
from .discovery import PluginDiscovery

__all__ = [
    'BasePlugin',
    'PluginMetadata', 
    'ToolDefinition',
    'ActionDefinition',
    'ParameterSchema',
    'PluginManager',
    'register_tool',
    'register_action',
    'PluginDiscovery'
]