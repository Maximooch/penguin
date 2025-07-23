"""
Decorators for easy tool and action registration in Penguin plugins.
"""

from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union
import inspect
import logging

from .base_plugin import ToolDefinition, ActionDefinition, ParameterSchema

logger = logging.getLogger(__name__)

# Global registry for decorated functions (used during plugin loading)
_REGISTERED_TOOLS: Dict[str, Dict[str, Any]] = {}
_REGISTERED_ACTIONS: Dict[str, Dict[str, Any]] = {}


def register_tool(
    name: Optional[str] = None,
    description: Optional[str] = None,
    parameters: Optional[List[Dict[str, Any]]] = None,
    permissions: Optional[List[str]] = None,
    category: str = "general",
    tags: Optional[List[str]] = None,
    examples: Optional[List[str]] = None
):
    """
    Decorator to register a function as a tool.
    
    Usage:
        @register_tool(
            name="search_web",
            description="Search the web for information",
            parameters=[
                {"name": "query", "type": "string", "description": "Search query", "required": True}
            ],
            permissions=["network.request"]
        )
        def search_web(query: str) -> str:
            # Tool implementation
            return search_results
    
    Args:
        name: Tool name (defaults to function name)
        description: Tool description
        parameters: List of parameter definitions
        permissions: List of required permissions
        category: Tool category
        tags: List of tags for categorization
        examples: List of usage examples
    """
    def decorator(func: Callable) -> Callable:
        tool_name = name or func.__name__
        
        # Extract parameters from function signature if not provided
        if parameters is None:
            param_list = _extract_parameters_from_signature(func)
        else:
            param_list = [ParameterSchema(**param) for param in parameters]
        
        # Extract description from docstring if not provided
        tool_description = description
        if not tool_description and func.__doc__:
            tool_description = func.__doc__.strip().split('\n')[0]
        
        if not tool_description:
            tool_description = f"Tool: {tool_name}"
        
        # Create tool definition
        tool_def = ToolDefinition(
            name=tool_name,
            description=tool_description,
            parameters=param_list,
            handler=func,
            permissions=permissions or [],
            category=category,
            tags=tags or [],
            examples=examples or []
        )
        
        # Store in global registry
        _REGISTERED_TOOLS[tool_name] = {
            'definition': tool_def,
            'function': func,
            'module': func.__module__
        }
        
        # Add metadata to function
        func._penguin_tool = tool_def
        
        logger.debug(f"Registered tool: {tool_name} from {func.__module__}")
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def register_action(
    name: Optional[str] = None,
    description: Optional[str] = None,
    pattern: Optional[str] = None,
    permissions: Optional[List[str]] = None
):
    """
    Decorator to register a function as an action handler.
    
    Usage:
        @register_action(
            name="custom_action",
            description="Handle custom action",
            pattern=r"<custom_action>(.*?)</custom_action>",
            permissions=["file.write"]
        )
        def handle_custom_action(context: Dict[str, Any]) -> Any:
            # Action implementation
            return result
    
    Args:
        name: Action name (defaults to function name)
        description: Action description
        pattern: Regex pattern to match action tags
        permissions: List of required permissions
    """
    def decorator(func: Callable) -> Callable:
        action_name = name or func.__name__
        
        # Extract description from docstring if not provided
        action_description = description
        if not action_description and func.__doc__:
            action_description = func.__doc__.strip().split('\n')[0]
        
        if not action_description:
            action_description = f"Action: {action_name}"
        
        # Create action definition
        action_def = ActionDefinition(
            name=action_name,
            description=action_description,
            handler=func,
            pattern=pattern,
            permissions=permissions or []
        )
        
        # Store in global registry
        _REGISTERED_ACTIONS[action_name] = {
            'definition': action_def,
            'function': func,
            'module': func.__module__
        }
        
        # Add metadata to function
        func._penguin_action = action_def
        
        logger.debug(f"Registered action: {action_name} from {func.__module__}")
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        
        return wrapper
    
    return decorator


def _extract_parameters_from_signature(func: Callable) -> List[ParameterSchema]:
    """Extract parameter schema from function signature"""
    signature = inspect.signature(func)
    parameters = []
    
    for param_name, param in signature.parameters.items():
        # Skip 'self' and 'cls' parameters
        if param_name in ('self', 'cls'):
            continue
            
        # Determine type from annotation
        param_type = "string"  # default
        if param.annotation != inspect.Parameter.empty:
            if param.annotation == str:
                param_type = "string"
            elif param.annotation == int:
                param_type = "integer"
            elif param.annotation == float:
                param_type = "number"
            elif param.annotation == bool:
                param_type = "boolean"
            elif hasattr(param.annotation, '__origin__'):
                # Handle generic types like List[str], Optional[int], etc.
                origin = param.annotation.__origin__
                if origin == list:
                    param_type = "array"
                elif origin == dict:
                    param_type = "object"
                elif origin == Union:  # Optional types
                    args = param.annotation.__args__
                    if len(args) == 2 and type(None) in args:
                        # This is Optional[T]
                        non_none_type = args[0] if args[1] == type(None) else args[1]
                        if non_none_type == str:
                            param_type = "string"
                        elif non_none_type == int:
                            param_type = "integer"
                        elif non_none_type == float:
                            param_type = "number"
                        elif non_none_type == bool:
                            param_type = "boolean"
        
        # Determine if required
        required = param.default == inspect.Parameter.empty
        default_value = None if required else param.default
        
        # Try to get description from docstring (basic parsing)
        description = f"Parameter: {param_name}"
        if func.__doc__:
            # Simple docstring parsing - look for Args: section
            lines = func.__doc__.split('\n')
            in_args_section = False
            for line in lines:
                line = line.strip()
                if line == "Args:" or line.startswith("Args:"):
                    in_args_section = True
                    continue
                elif in_args_section:
                    if line.startswith(f"{param_name}:") or line.startswith(f"{param_name} "):
                        # Extract description after parameter name
                        parts = line.split(':', 1)
                        if len(parts) > 1:
                            description = parts[1].strip()
                        break
                    elif line == "" or line.startswith("Returns:") or line.startswith("Raises:"):
                        break
        
        parameters.append(ParameterSchema(
            name=param_name,
            type=param_type,
            description=description,
            required=required,
            default=default_value
        ))
    
    return parameters


def get_registered_tools() -> Dict[str, Dict[str, Any]]:
    """Get all registered tools"""
    return _REGISTERED_TOOLS.copy()


def get_registered_actions() -> Dict[str, Dict[str, Any]]:
    """Get all registered actions"""
    return _REGISTERED_ACTIONS.copy()


def clear_registrations() -> None:
    """Clear all registrations (useful for testing)"""
    global _REGISTERED_TOOLS, _REGISTERED_ACTIONS
    _REGISTERED_TOOLS.clear()
    _REGISTERED_ACTIONS.clear()


def get_tools_from_module(module_name: str) -> List[ToolDefinition]:
    """Get all tools registered from a specific module"""
    tools = []
    for tool_data in _REGISTERED_TOOLS.values():
        if tool_data['module'] == module_name:
            tools.append(tool_data['definition'])
    return tools


def get_actions_from_module(module_name: str) -> List[ActionDefinition]:
    """Get all actions registered from a specific module"""
    actions = []
    for action_data in _REGISTERED_ACTIONS.values():
        if action_data['module'] == module_name:
            actions.append(action_data['definition'])
    return actions