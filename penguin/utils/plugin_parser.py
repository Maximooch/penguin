"""
Plugin-aware parser and action executor for Penguin.

This module extends the existing parser to support dynamic action registration
from plugins, providing better extensibility for the action system.
"""

import asyncio
import logging
import re
from datetime import datetime
from html import unescape
from typing import List, Dict, Any, Optional, Set, Callable, Union
from enum import Enum

from penguin.plugins import PluginManager, ActionDefinition
from penguin.local_task.manager import ProjectManager
from penguin.tools.plugin_tool_manager import PluginToolManager
from penguin.utils.process_manager import ProcessManager
from penguin.system.conversation import MessageCategory

logger = logging.getLogger(__name__)


class CodeActAction:
    """Represents a parsed action from AI response"""
    
    def __init__(self, action_type: str, parameters: Any, raw_content: str = ""):
        self.action_type = action_type
        self.parameters = parameters
        self.raw_content = raw_content
        self.timestamp = datetime.now()


class PluginActionParser:
    """
    Plugin-aware action parser that can handle both built-in actions
    and dynamically registered plugin actions.
    """
    
    def __init__(self, plugin_manager: PluginManager):
        self.plugin_manager = plugin_manager
        self.logger = logging.getLogger(__name__)
        
        # Built-in action patterns that are handled specially
        self.builtin_patterns = {
            'execute': r'<execute>(.*?)</execute>',
            'execute_command': r'<execute_command>(.*?)</execute_command>',
            'search': r'<search>(.*?)</search>',
            'memory_search': r'<memory_search>(.*?)</memory_search>',
            'add_declarative_note': r'<add_declarative_note>(.*?)</add_declarative_note>',
        }
    
    def parse_response(self, response_text: str) -> List[CodeActAction]:
        """Parse AI response to extract actions"""
        actions = []
        
        # Parse built-in actions first
        actions.extend(self._parse_builtin_actions(response_text))
        
        # Parse plugin actions
        actions.extend(self._parse_plugin_actions(response_text))
        
        return actions
    
    def _parse_builtin_actions(self, response_text: str) -> List[CodeActAction]:
        """Parse built-in action patterns"""
        actions = []
        
        for action_type, pattern in self.builtin_patterns.items():
            matches = re.finditer(pattern, response_text, re.DOTALL)
            for match in matches:
                content = match.group(1).strip()
                action = CodeActAction(action_type, content, match.group(0))
                actions.append(action)
                self.logger.debug(f"Parsed built-in action: {action_type}")
        
        return actions
    
    def _parse_plugin_actions(self, response_text: str) -> List[CodeActAction]:
        """Parse actions registered by plugins"""
        actions = []
        
        # Get all available actions from plugins
        plugin_actions = self.plugin_manager.get_available_actions()
        
        for action_name, action_def in plugin_actions.items():
            if action_def.pattern:
                # Use custom pattern if provided
                pattern = action_def.pattern
            else:
                # Generate default pattern: <action_name>...</action_name>
                pattern = f'<{action_name}>(.*?)</{action_name}>'
            
            try:
                matches = re.finditer(pattern, response_text, re.DOTALL)
                for match in matches:
                    content = match.group(1).strip() if match.groups() else ""
                    action = CodeActAction(action_name, content, match.group(0))
                    actions.append(action)
                    self.logger.debug(f"Parsed plugin action: {action_name}")
            
            except Exception as e:
                self.logger.error(f"Error parsing action {action_name} with pattern {pattern}: {e}")
        
        return actions
    
    def get_available_actions(self) -> Dict[str, str]:
        """Get list of all available actions with descriptions"""
        actions = {}
        
        # Add built-in actions
        builtin_descriptions = {
            'execute': 'Execute code in a notebook environment',
            'execute_command': 'Execute a system command',
            'search': 'Search for text patterns in files',
            'memory_search': 'Search in conversation memory',
            'add_declarative_note': 'Add a note to declarative memory'
        }
        actions.update(builtin_descriptions)
        
        # Add plugin actions
        plugin_actions = self.plugin_manager.get_available_actions()
        for action_name, action_def in plugin_actions.items():
            actions[action_name] = action_def.description
        
        return actions


class PluginActionExecutor:
    """
    Plugin-aware action executor that can execute both built-in actions
    and dynamically registered plugin actions.
    """
    
    def __init__(self, 
                 plugin_tool_manager: PluginToolManager,
                 task_manager: ProjectManager,
                 conversation_system=None):
        self.tool_manager = plugin_tool_manager
        self.task_manager = task_manager
        self.process_manager = ProcessManager()
        self.current_process = None
        self.conversation_system = conversation_system
        self.logger = logging.getLogger(__name__)
        
        # Get plugin manager from tool manager
        self.plugin_manager = plugin_tool_manager.plugin_manager
        
        # Built-in action handlers
        self.builtin_handlers = {
            'execute': self._execute_code,
            'execute_command': self._execute_command,
            'search': self._handle_search,
            'memory_search': self._memory_search,
            'add_declarative_note': self._add_declarative_note,
        }
    
    async def execute_action(self, action: CodeActAction) -> str:
        """Execute a parsed action"""
        self.logger.debug(f"Attempting to execute action: {action.action_type}")
        
        try:
            # Check if it's a built-in action first
            if action.action_type in self.builtin_handlers:
                handler = self.builtin_handlers[action.action_type]
                if asyncio.iscoroutinefunction(handler):
                    return await handler(action.parameters)
                else:
                    return handler(action.parameters)
            
            # Try to execute as plugin action
            return await self._execute_plugin_action(action)
            
        except Exception as e:
            error_msg = f"Error executing action {action.action_type}: {str(e)}"
            self.logger.error(error_msg)
            return error_msg
    
    async def _execute_plugin_action(self, action: CodeActAction) -> str:
        """Execute a plugin action"""
        try:
            # Parse parameters if they're in JSON format
            context = {
                'parameters': action.parameters,
                'raw_content': action.raw_content,
                'timestamp': action.timestamp
            }
            
            # Try to parse parameters as structured data
            if isinstance(action.parameters, str):
                # Try JSON first
                try:
                    import json
                    context['structured_params'] = json.loads(action.parameters)
                except:
                    # Try YAML
                    try:
                        import yaml
                        context['structured_params'] = yaml.safe_load(action.parameters)
                    except:
                        # Fall back to plain text
                        context['structured_params'] = action.parameters
            else:
                context['structured_params'] = action.parameters
            
            # Execute the action through plugin manager
            result = self.plugin_manager.execute_action(action.action_type, context)
            
            # Convert result to string if needed
            if isinstance(result, dict):
                import json
                return json.dumps(result, indent=2)
            elif result is None:
                return f"Action {action.action_type} completed successfully"
            else:
                return str(result)
                
        except ValueError as e:
            if "not found" in str(e).lower():
                return f"Unknown action: {action.action_type}. Available actions: {list(self.get_available_actions().keys())}"
            else:
                raise
    
    def get_available_actions(self) -> Dict[str, str]:
        """Get all available actions with descriptions"""
        actions = {}
        
        # Built-in actions
        builtin_descriptions = {
            'execute': 'Execute code in a notebook environment',
            'execute_command': 'Execute a system command', 
            'search': 'Search for text patterns in files',
            'memory_search': 'Search in conversation memory',
            'add_declarative_note': 'Add a note to declarative memory'
        }
        actions.update(builtin_descriptions)
        
        # Plugin actions
        plugin_actions = self.plugin_manager.get_available_actions()
        for action_name, action_def in plugin_actions.items():
            actions[action_name] = action_def.description
        
        return actions
    
    # Built-in action handlers
    async def _execute_code(self, params: str) -> str:
        """Execute code in notebook environment"""
        try:
            result = self.tool_manager.execute_tool("code_execution", {"code": params})
            return str(result)
        except Exception as e:
            return f"Code execution failed: {str(e)}"
    
    async def _execute_command(self, params: str) -> str:
        """Execute system command"""
        try:
            result = self.tool_manager.execute_tool("execute_command", {"command": params})
            if isinstance(result, dict):
                if result.get("success"):
                    return result.get("stdout", "Command executed successfully")
                else:
                    return f"Command failed: {result.get('stderr', result.get('error', 'Unknown error'))}"
            return str(result)
        except Exception as e:
            return f"Command execution failed: {str(e)}"
    
    def _handle_search(self, params: str) -> str:
        """Handle search action"""
        try:
            result = self.tool_manager.execute_tool("grep_search", {"pattern": params})
            return str(result)
        except Exception as e:
            return f"Search failed: {str(e)}"
    
    async def _memory_search(self, params: str) -> str:
        """Handle memory search"""
        try:
            result = self.tool_manager.execute_tool("memory_search", {"query": params})
            return str(result)
        except Exception as e:
            return f"Memory search failed: {str(e)}"
    
    def _add_declarative_note(self, params: str) -> str:
        """Add declarative note"""
        try:
            # Parse parameters - expect format like "category: content"
            if ":" in params:
                category, content = params.split(":", 1)
                category = category.strip()
                content = content.strip()
            else:
                category = "general"
                content = params.strip()
            
            result = self.tool_manager.execute_tool("add_declarative_note", {
                "category": category,
                "content": content
            })
            return str(result)
        except Exception as e:
            return f"Failed to add note: {str(e)}"


class PluginCodeActParser:
    """
    Main parser class that combines parsing and execution with plugin support.
    """
    
    def __init__(self, 
                 plugin_tool_manager: PluginToolManager,
                 task_manager: ProjectManager,
                 conversation_system=None):
        self.tool_manager = plugin_tool_manager
        self.plugin_manager = plugin_tool_manager.plugin_manager
        
        self.parser = PluginActionParser(self.plugin_manager)
        self.executor = PluginActionExecutor(plugin_tool_manager, task_manager, conversation_system)
        
        self.logger = logging.getLogger(__name__)
    
    def parse_and_execute_response(self, response_text: str) -> List[Dict[str, Any]]:
        """Parse response and execute all found actions"""
        actions = self.parser.parse_response(response_text)
        results = []
        
        for action in actions:
            try:
                result = asyncio.run(self.executor.execute_action(action))
                results.append({
                    'action_type': action.action_type,
                    'parameters': action.parameters,
                    'result': result,
                    'success': True
                })
            except Exception as e:
                self.logger.error(f"Failed to execute action {action.action_type}: {e}")
                results.append({
                    'action_type': action.action_type,
                    'parameters': action.parameters,
                    'error': str(e),
                    'success': False
                })
        
        return results
    
    async def parse_and_execute_response_async(self, response_text: str) -> List[Dict[str, Any]]:
        """Async version of parse and execute"""
        actions = self.parser.parse_response(response_text)
        results = []
        
        for action in actions:
            try:
                result = await self.executor.execute_action(action)
                results.append({
                    'action_type': action.action_type,
                    'parameters': action.parameters,
                    'result': result,
                    'success': True
                })
            except Exception as e:
                self.logger.error(f"Failed to execute action {action.action_type}: {e}")
                results.append({
                    'action_type': action.action_type,
                    'parameters': action.parameters,
                    'error': str(e),
                    'success': False
                })
        
        return results
    
    def get_available_actions(self) -> Dict[str, str]:
        """Get all available actions"""
        return self.executor.get_available_actions()
    
    def register_custom_action(self, action_def: ActionDefinition) -> None:
        """Register a custom action at runtime"""
        # This could be used to register actions without full plugin structure
        # For now, actions should be registered through plugins
        self.logger.warning("register_custom_action is not implemented - use plugins instead")
    
    def reload_plugins(self) -> bool:
        """Reload all plugins to pick up new actions"""
        try:
            plugin_names = self.plugin_manager.list_plugins()
            success_count = 0
            
            for plugin_name in plugin_names:
                if self.plugin_manager.reload_plugin(plugin_name):
                    success_count += 1
            
            self.logger.info(f"Reloaded {success_count} of {len(plugin_names)} plugins")
            return success_count == len(plugin_names)
            
        except Exception as e:
            self.logger.error(f"Error reloading plugins: {e}")
            return False