"""
Base plugin interface and metadata definitions for Penguin's plugin system.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, Callable
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class PluginStatus(Enum):
    """Plugin lifecycle status"""
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    ACTIVE = "active"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass
class ParameterSchema:
    """Schema definition for tool parameters"""
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum_values: Optional[List[Any]] = None
    pattern: Optional[str] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None


@dataclass
class ToolDefinition:
    """Definition of a tool provided by a plugin"""
    name: str
    description: str
    parameters: List[ParameterSchema] = field(default_factory=list)
    handler: Optional[Callable] = None
    permissions: List[str] = field(default_factory=list)
    category: str = "general"
    tags: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)


@dataclass
class ActionDefinition:
    """Definition of an action provided by a plugin"""
    name: str
    description: str
    handler: Callable
    pattern: Optional[str] = None
    permissions: List[str] = field(default_factory=list)


@dataclass
class PluginMetadata:
    """Plugin metadata and configuration"""
    name: str
    version: str
    description: str
    author: str = ""
    homepage: str = ""
    entry_point: str = ""
    dependencies: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    tools: List[ToolDefinition] = field(default_factory=list)
    actions: List[ActionDefinition] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    min_penguin_version: str = ""
    max_penguin_version: str = ""
    
    def __post_init__(self):
        """Validate metadata after initialization"""
        if not self.name:
            raise ValueError("Plugin name is required")
        if not self.version:
            raise ValueError("Plugin version is required")
        if not self.description:
            raise ValueError("Plugin description is required")


class BasePlugin(ABC):
    """
    Abstract base class for all Penguin plugins.
    
    Plugins must inherit from this class and implement the required methods
    to integrate with Penguin's tool system.
    """
    
    def __init__(self, metadata: PluginMetadata, config: Optional[Dict[str, Any]] = None):
        self.metadata = metadata
        self.config = config or {}
        self.status = PluginStatus.UNLOADED
        self.logger = logging.getLogger(f"plugin.{metadata.name}")
        self._tools: Dict[str, ToolDefinition] = {}
        self._actions: Dict[str, ActionDefinition] = {}
        
    @abstractmethod
    def initialize(self) -> bool:
        """
        Initialize the plugin.
        
        Called when the plugin is first loaded. Should set up any necessary
        resources, validate configuration, and prepare tools for use.
        
        Returns:
            bool: True if initialization was successful, False otherwise
        """
        pass
    
    @abstractmethod
    def cleanup(self) -> None:
        """
        Clean up plugin resources.
        
        Called when the plugin is being unloaded. Should release any
        resources, close connections, and perform cleanup tasks.
        """
        pass
    
    def get_tools(self) -> Dict[str, ToolDefinition]:
        """Get all tools provided by this plugin"""
        return self._tools.copy()
    
    def get_actions(self) -> Dict[str, ActionDefinition]:
        """Get all actions provided by this plugin"""
        return self._actions.copy()
    
    def register_tool(self, tool: ToolDefinition) -> None:
        """Register a tool with this plugin"""
        if tool.name in self._tools:
            self.logger.warning(f"Tool {tool.name} already registered, overwriting")
        self._tools[tool.name] = tool
        self.logger.debug(f"Registered tool: {tool.name}")
    
    def register_action(self, action: ActionDefinition) -> None:
        """Register an action with this plugin"""
        if action.name in self._actions:
            self.logger.warning(f"Action {action.name} already registered, overwriting")
        self._actions[action.name] = action
        self.logger.debug(f"Registered action: {action.name}")
    
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Any:
        """
        Execute a tool provided by this plugin.
        
        Args:
            tool_name: Name of the tool to execute
            parameters: Parameters to pass to the tool
            
        Returns:
            The result of the tool execution
            
        Raises:
            ValueError: If the tool is not found or parameters are invalid
        """
        if tool_name not in self._tools:
            raise ValueError(f"Tool {tool_name} not found in plugin {self.metadata.name}")
        
        tool = self._tools[tool_name]
        if not tool.handler:
            raise ValueError(f"Tool {tool_name} has no handler defined")
        
        # Validate parameters
        self._validate_parameters(tool.parameters, parameters)
        
        try:
            self.logger.debug(f"Executing tool {tool_name} with parameters: {parameters}")
            result = tool.handler(**parameters)
            self.logger.debug(f"Tool {tool_name} executed successfully")
            return result
        except Exception as e:
            self.logger.error(f"Error executing tool {tool_name}: {str(e)}")
            raise
    
    def execute_action(self, action_name: str, context: Dict[str, Any]) -> Any:
        """
        Execute an action provided by this plugin.
        
        Args:
            action_name: Name of the action to execute
            context: Context data for the action
            
        Returns:
            The result of the action execution
            
        Raises:
            ValueError: If the action is not found
        """
        if action_name not in self._actions:
            raise ValueError(f"Action {action_name} not found in plugin {self.metadata.name}")
        
        action = self._actions[action_name]
        
        try:
            self.logger.debug(f"Executing action {action_name}")
            result = action.handler(context)
            self.logger.debug(f"Action {action_name} executed successfully")
            return result
        except Exception as e:
            self.logger.error(f"Error executing action {action_name}: {str(e)}")
            raise
    
    def _validate_parameters(self, schema: List[ParameterSchema], parameters: Dict[str, Any]) -> None:
        """Validate parameters against schema"""
        for param in schema:
            if param.required and param.name not in parameters:
                raise ValueError(f"Required parameter {param.name} is missing")
            
            if param.name in parameters:
                value = parameters[param.name]
                
                # Type validation (basic)
                if param.type == "string" and not isinstance(value, str):
                    raise ValueError(f"Parameter {param.name} must be a string")
                elif param.type == "integer" and not isinstance(value, int):
                    raise ValueError(f"Parameter {param.name} must be an integer")
                elif param.type == "number" and not isinstance(value, (int, float)):
                    raise ValueError(f"Parameter {param.name} must be a number")
                elif param.type == "boolean" and not isinstance(value, bool):
                    raise ValueError(f"Parameter {param.name} must be a boolean")
                
                # Enum validation
                if param.enum_values and value not in param.enum_values:
                    raise ValueError(f"Parameter {param.name} must be one of: {param.enum_values}")
                
                # Range validation for numbers
                if isinstance(value, (int, float)):
                    if param.min_value is not None and value < param.min_value:
                        raise ValueError(f"Parameter {param.name} must be >= {param.min_value}")
                    if param.max_value is not None and value > param.max_value:
                        raise ValueError(f"Parameter {param.name} must be <= {param.max_value}")
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """
        Validate plugin configuration.
        
        Args:
            config: Configuration dictionary to validate
            
        Returns:
            bool: True if configuration is valid
        """
        # Basic validation - can be overridden by subclasses
        if not isinstance(config, dict):
            return False
        
        # Validate against config schema if defined
        if self.metadata.config_schema:
            # TODO: Implement JSON schema validation
            pass
        
        return True
    
    def get_status(self) -> PluginStatus:
        """Get current plugin status"""
        return self.status
    
    def set_status(self, status: PluginStatus) -> None:
        """Set plugin status"""
        old_status = self.status
        self.status = status
        self.logger.debug(f"Plugin status changed from {old_status.value} to {status.value}")
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.metadata.name}' version='{self.metadata.version}' status='{self.status.value}'>"