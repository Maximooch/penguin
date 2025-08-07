"""
Unified abstraction layer for displaying both Tools and Actions in the TUI.

This module provides a common interface for rendering both:
- ActionType executions from parser.py
- Tool executions from tool_manager.py
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Union
from enum import Enum
import json
from datetime import datetime


class ExecutionType(Enum):
    """Type of execution being displayed."""
    ACTION = "action"  # ActionType from parser.py
    TOOL = "tool"      # Tool from tool_manager.py
    SYSTEM = "system"  # System messages
    ERROR = "error"    # Error messages


class ExecutionStatus(Enum):
    """Status of an execution."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class UnifiedExecution:
    """
    Unified representation of any execution (tool or action).
    
    This abstraction allows the TUI to display both ActionType executions
    and Tool executions in a consistent manner.
    """
    
    # Core fields
    id: str
    name: str
    type: ExecutionType
    status: ExecutionStatus
    
    # Display metadata
    display_name: str
    icon: str = "🔧"
    category: Optional[str] = None
    
    # Execution details
    parameters: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Any] = None
    error: Optional[str] = None
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # UI hints
    is_collapsible: bool = True
    show_parameters: bool = True
    show_result: bool = True
    max_result_lines: int = 20
    
    @property
    def duration_ms(self) -> Optional[int]:
        """Calculate execution duration in milliseconds."""
        if self.started_at and self.completed_at:
            delta = self.completed_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return None
    
    @property
    def duration_str(self) -> str:
        """Get human-readable duration string."""
        ms = self.duration_ms
        if ms is None:
            return "N/A"
        if ms < 1000:
            return f"{ms}ms"
        elif ms < 60000:
            return f"{ms/1000:.1f}s"
        else:
            return f"{ms/60000:.1f}m"
    
    def to_display_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary suitable for display."""
        return {
            "name": self.display_name,
            "status": self.status.value,
            "type": self.type.value,
            "icon": self.icon,
            "duration": self.duration_str,
            "parameters": self._format_parameters(),
            "result": self._format_result(),
            "error": self.error,
        }
    
    def _format_parameters(self) -> str:
        """Format parameters for display."""
        if not self.parameters:
            return "No parameters"
        
        # Special formatting for common parameter patterns
        if len(self.parameters) == 1 and "query" in self.parameters:
            return f'query: "{self.parameters["query"]}"'
        elif len(self.parameters) == 1 and "code" in self.parameters:
            code = self.parameters["code"]
            if len(code) > 100:
                code = code[:100] + "..."
            return f"code: {code}"
        elif len(self.parameters) == 1 and "command" in self.parameters:
            return f'command: {self.parameters["command"]}'
        
        # General formatting
        try:
            return json.dumps(self.parameters, indent=2)
        except:
            return str(self.parameters)
    
    def _format_result(self) -> str:
        """Format result for display."""
        if self.result is None:
            return "No result yet"
        
        if isinstance(self.result, dict):
            try:
                return json.dumps(self.result, indent=2)
            except:
                return str(self.result)
        elif isinstance(self.result, list):
            return "\n".join(str(item) for item in self.result)
        else:
            return str(self.result)


class ExecutionAdapter:
    """Adapts various execution types to UnifiedExecution."""
    
    # Icon mapping for different execution types
    ICON_MAP = {
        # Tools
        "workspace_search": "🔍",
        "memory_search": "🧠",
        "execute": "▶️",
        "execute_command": "💻",
        "enhanced_read": "📖",
        "enhanced_write": "✏️",
        "list_files_filtered": "📁",
        "find_files_enhanced": "🔎",
        "apply_diff": "📝",
        "analyze_project": "📊",
        "browser_navigate": "🌐",
        "browser_screenshot": "📸",
        
        # Actions
        "task_create": "📋",
        "task_update": "✏️",
        "task_complete": "✅",
        "project_create": "🚀",
        "project_list": "📑",
        
        # System
        "system": "ℹ️",
        "error": "❌",
    }
    
    @classmethod
    def from_action(cls, action_type: str, params: Union[str, Dict[str, Any]], 
                    action_id: Optional[str] = None) -> UnifiedExecution:
        """Create UnifiedExecution from an ActionType execution.
        
        Args:
            action_type: The action type (e.g., "workspace_search", "execute")
            params: Either a string (XML tag content) or dict of parameters
            action_id: Optional unique identifier
        """
        from datetime import datetime
        import uuid
        
        execution_id = action_id or str(uuid.uuid4())[:8]
        display_name = action_type.replace("_", " ").title()
        icon = cls.ICON_MAP.get(action_type.lower(), "⚡")
        
        # Convert string params to dict for display
        if isinstance(params, str):
            params_dict = cls._parse_action_params(action_type, params)
        else:
            params_dict = params
        
        return UnifiedExecution(
            id=execution_id,
            name=action_type,
            type=ExecutionType.ACTION,
            status=ExecutionStatus.PENDING,
            display_name=display_name,
            icon=icon,
            parameters=params_dict,
            started_at=datetime.now()
        )
    
    @staticmethod
    def _parse_action_params(action_type: str, params_str: str) -> Dict[str, Any]:
        """Parse action tag parameters from string format.
        
        Most action tags use colon-separated parameters like:
        - workspace_search: "query:max_results"
        - enhanced_read: "path:show_line_numbers:max_lines"
        - execute: raw code string
        """
        if not params_str:
            return {}
        
        # Special cases for actions with raw content
        if action_type in ["execute", "execute_command"]:
            return {"code": params_str}
        elif action_type in ["add_declarative_note", "add_summary_note"]:
            # Format: "category:content"
            parts = params_str.split(":", 1)
            if len(parts) == 2:
                return {"category": parts[0], "content": parts[1]}
            return {"content": params_str}
        elif action_type == "workspace_search":
            # Format: "query:max_results"
            parts = params_str.split(":")
            result = {"query": parts[0]}
            if len(parts) > 1:
                try:
                    result["max_results"] = int(parts[1])
                except:
                    pass
            return result
        elif action_type == "memory_search":
            # Format: "query:k:memory_type:categories"
            parts = params_str.split(":")
            result = {"query": parts[0]}
            if len(parts) > 1 and parts[1]:
                try:
                    result["k"] = int(parts[1])
                except:
                    pass
            if len(parts) > 2 and parts[2]:
                result["memory_type"] = parts[2]
            if len(parts) > 3 and parts[3]:
                result["categories"] = parts[3].split(",")
            return result
        elif action_type in ["enhanced_read", "enhanced_write", "list_files_filtered", 
                           "find_files_enhanced", "apply_diff", "edit_with_pattern"]:
            # These have specific parameter orders
            parts = params_str.split(":")
            param_names = {
                "enhanced_read": ["path", "show_line_numbers", "max_lines"],
                "enhanced_write": ["path", "content", "backup"],
                "list_files_filtered": ["path", "group_by_type", "show_hidden"],
                "find_files_enhanced": ["pattern", "search_path", "include_hidden", "file_type"],
                "apply_diff": ["file_path", "diff_content", "backup"],
                "edit_with_pattern": ["file_path", "search_pattern", "replacement", "backup"],
            }
            
            names = param_names.get(action_type, [])
            result = {}
            for i, name in enumerate(names):
                if i < len(parts):
                    # Convert boolean strings
                    if parts[i].lower() in ["true", "false"]:
                        result[name] = parts[i].lower() == "true"
                    else:
                        result[name] = parts[i]
            return result
        else:
            # Generic colon-separated parsing
            parts = params_str.split(":")
            if len(parts) == 1:
                return {"params": params_str}
            else:
                # Try to create a meaningful dict
                return {f"param_{i+1}": part for i, part in enumerate(parts)}
    
    @classmethod
    def from_tool(cls, tool_name: str, tool_input: Dict[str, Any],
                  tool_id: Optional[str] = None) -> UnifiedExecution:
        """Create UnifiedExecution from a Tool execution."""
        from datetime import datetime
        import uuid
        
        execution_id = tool_id or str(uuid.uuid4())[:8]
        display_name = tool_name.replace("_", " ").title()
        icon = cls.ICON_MAP.get(tool_name.lower(), "🔧")
        
        return UnifiedExecution(
            id=execution_id,
            name=tool_name,
            type=ExecutionType.TOOL,
            status=ExecutionStatus.PENDING,
            display_name=display_name,
            icon=icon,
            parameters=tool_input,
            started_at=datetime.now()
        )
    
    @classmethod
    def from_system(cls, message: str, system_id: Optional[str] = None) -> UnifiedExecution:
        """Create UnifiedExecution for a system message."""
        from datetime import datetime
        import uuid
        
        execution_id = system_id or str(uuid.uuid4())[:8]
        
        return UnifiedExecution(
            id=execution_id,
            name="system",
            type=ExecutionType.SYSTEM,
            status=ExecutionStatus.SUCCESS,
            display_name="System",
            icon="ℹ️",
            result=message,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            show_parameters=False
        )
    
    @classmethod
    def from_error(cls, error: str, context: Optional[str] = None,
                   error_id: Optional[str] = None) -> UnifiedExecution:
        """Create UnifiedExecution for an error."""
        from datetime import datetime
        import uuid
        
        execution_id = error_id or str(uuid.uuid4())[:8]
        
        return UnifiedExecution(
            id=execution_id,
            name="error",
            type=ExecutionType.ERROR,
            status=ExecutionStatus.FAILED,
            display_name=context or "Error",
            icon="❌",
            error=error,
            started_at=datetime.now(),
            completed_at=datetime.now(),
            show_parameters=False,
            is_collapsible=False
        )
