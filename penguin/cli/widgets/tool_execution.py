"""
Tool Execution Widget for Penguin TUI.

Displays tool/action executions with collapsible details.
"""

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Static, Collapsible, Label, Markdown
from textual.reactive import reactive
from rich.text import Text
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown as RichMarkdown
import json
from typing import Optional, Any, Dict
from enum import Enum

from .base import PenguinWidget
from .unified_display import UnifiedExecution, ExecutionStatus, ExecutionType


class ToolStatus(Enum):
    """Visual status indicators for tool execution."""
    PENDING = ("⏳", "dim yellow")
    RUNNING = ("⟳", "bright_yellow")
    SUCCESS = ("✅", "green")
    FAILED = ("❌", "red")
    CANCELLED = ("🚫", "dim red")


class ToolExecutionWidget(PenguinWidget, can_focus=True):
    """
    Widget for displaying tool/action execution with collapsible sections.
    
    Features:
    - Unified display for both ActionType and Tool executions
    - Real-time status updates
    - Collapsible parameter and result sections
    - Syntax highlighting for code results
    - Copy functionality (future)
    """
    
    BINDINGS = [
        ("enter", "toggle", "Toggle expand/collapse"),
        ("space", "toggle", "Toggle expand/collapse"),
        ("c", "copy_result", "Copy result"),
    ]
    
    execution: reactive[Optional[UnifiedExecution]] = reactive(None)
    
    def __init__(self, execution: UnifiedExecution, **kwargs):
        super().__init__(**kwargs)
        self.execution = execution
        self.add_class("tool-execution")
        
        # Track internal state
        self._params_expanded = False
        self._result_expanded = False
        self._start_time = execution.started_at
        
    def compose(self) -> ComposeResult:
        """Build the widget structure."""
        if not self.execution:
            yield Static("No execution data")
            return
        
        # Wrap all child widgets inside a container so Textual mounts them *after* this widget is attached
        with Container(classes="tool-container"):
            # Header with status, icon, and name
            yield self._create_header()
            
            # Parameters section
            if self.execution.show_parameters and self.execution.parameters:
                params_content = self._format_parameters_content()
                with Collapsible(title="📋 Parameters", collapsed=not self._params_expanded):
                    yield Static(params_content, classes="tool-params-content")
            
            # Result section
            if self.execution.show_result or self.execution.error:
                result_title, result_content, initially_expanded = self._format_result_content()
                with Collapsible(title=result_title, collapsed=not initially_expanded):
                    yield Static(result_content, classes="tool-result-content")
    
    def _create_header(self) -> Static:
        """Create the header with status indicator."""
        exec = self.execution
        status_icon, status_color = self._get_status_display(exec.status)
        
        # Build header text
        header_parts = [
            f"{status_icon}",
            f"{exec.icon}",
            f"[bold]{exec.display_name}[/bold]",
        ]
        
        if exec.status == ExecutionStatus.RUNNING:
            header_parts.append("[dim yellow]Running...[/dim yellow]")
        elif exec.duration_str and exec.status in [ExecutionStatus.SUCCESS, ExecutionStatus.FAILED]:
            header_parts.append(f"[dim]({exec.duration_str})[/dim]")
        
        header_text = " ".join(header_parts)
        
        # Add expand/collapse indicator if collapsible
        if exec.is_collapsible:
            expand_icon = "▼" if self.is_expanded else "▶"
            header_text = f"{expand_icon} {header_text}"
        
        return Static(header_text, classes="tool-header")
    
    def _format_parameters_content(self) -> str:
        """Format parameters for display."""
        params = self.execution.parameters
        
        # Format parameters based on type
        if isinstance(params, dict):
            # Special handling for common patterns
            if len(params) == 1:
                key = list(params.keys())[0]
                value = params[key]
                
                if key in ["query", "prompt", "question"]:
                    content_str = f'[cyan]{key}:[/cyan] "{value}"'
                elif key in ["code", "script"]:
                    # Format as code block
                    lang = self._detect_language(str(value))
                    content_str = f"```{lang}\n{value}\n```"
                elif key in ["command", "cmd"]:
                    content_str = f'[green]$[/green] {value}'
                else:
                    content_str = f'[cyan]{key}:[/cyan] {value}'
            else:
                # Multiple parameters - format as JSON
                try:
                    formatted = json.dumps(params, indent=2)
                    content_str = f"```json\n{formatted}\n```"
                except:
                    content_str = str(params)
        else:
            content_str = str(params)
        
        return content_str
    
    def _format_result_content(self) -> tuple[str, str, bool]:
        """Format result content for display.
        
        Returns:
            Tuple of (title, content, initially_expanded)
        """
        exec = self.execution
        
        # Determine content to show
        if exec.error:
            title = "❌ Error"
            content = self._format_error(exec.error)
            initially_expanded = True  # Always expand errors
        elif exec.result is not None:
            title = "✅ Result"
            content = self._format_result_display(exec.result)
            initially_expanded = self._should_auto_expand_result(exec.result)
        else:
            title = "⏳ Waiting for result..."
            content = "[dim]No result yet[/dim]"
            initially_expanded = False
        
        return title, content, initially_expanded
    
    def _get_status_display(self, status: ExecutionStatus) -> tuple[str, str]:
        """Get icon and color for status."""
        mapping = {
            ExecutionStatus.PENDING: ToolStatus.PENDING.value,
            ExecutionStatus.RUNNING: ToolStatus.RUNNING.value,
            ExecutionStatus.SUCCESS: ToolStatus.SUCCESS.value,
            ExecutionStatus.FAILED: ToolStatus.FAILED.value,
            ExecutionStatus.CANCELLED: ToolStatus.CANCELLED.value,
        }
        return mapping.get(status, ("?", "white"))
    
    def _format_result_display(self, result: Any) -> str:
        """Format result for display as a string."""
        if isinstance(result, dict):
            try:
                formatted = json.dumps(result, indent=2)
                return f"```json\n{formatted}\n```"
            except:
                return str(result)
        elif isinstance(result, list):
            # Format list results
            if all(isinstance(item, dict) for item in result):
                try:
                    formatted = json.dumps(result, indent=2)
                    return f"```json\n{formatted}\n```"
                except:
                    pass
            
            # Simple list
            lines = []
            for i, item in enumerate(result[:50]):  # Limit to first 50 items
                lines.append(f"  {i+1}. {item}")
            if len(result) > 50:
                lines.append(f"  ... and {len(result) - 50} more items")
            return "\n".join(lines)
        elif isinstance(result, str):
            # Check for multiline strings that might be code
            if "\n" in result and len(result.splitlines()) > 3:
                # Try to detect and highlight code
                if self._looks_like_code(result):
                    lang = self._detect_language(result)
                    return f"```{lang}\n{result}\n```"
            return result
        else:
            return str(result)
    
    def _format_error(self, error: str) -> str:
        """Format error for display."""
        return f"[bold red]Error:[/bold red]\n{error}"
    
    def _should_auto_expand_result(self, result: Any) -> bool:
        """Determine if result should be auto-expanded."""
        if isinstance(result, str):
            # Short results can be auto-expanded
            return len(result.splitlines()) <= 10
        elif isinstance(result, (dict, list)):
            # Small structured data can be auto-expanded
            try:
                json_str = json.dumps(result)
                return len(json_str) < 500
            except:
                return False
        return True
    
    def _looks_like_code(self, text: str) -> bool:
        """Simple heuristic to detect if text looks like code."""
        code_indicators = [
            "def ", "class ", "import ", "from ",  # Python
            "function ", "const ", "let ", "var ",  # JavaScript
            "public ", "private ", "void ",  # Java/C#
            "{", "}", ";",  # General code syntax
        ]
        return any(indicator in text for indicator in code_indicators)
    
    def _detect_language(self, code: str) -> str:
        """Simple language detection."""
        # Python
        if "def " in code or "import " in code or "class " in code:
            return "python"
        # JavaScript/TypeScript
        elif "function " in code or "const " in code or "=>" in code:
            return "javascript"
        # HTML
        elif "<html" in code or "<div" in code or "<body" in code:
            return "html"
        # JSON
        elif code.strip().startswith("{") and code.strip().endswith("}"):
            try:
                json.loads(code)
                return "json"
            except:
                pass
        # SQL
        elif any(kw in code.upper() for kw in ["SELECT", "INSERT", "UPDATE", "DELETE", "CREATE"]):
            return "sql"
        # Shell
        elif code.startswith("#!") or "echo " in code or "export " in code:
            return "bash"
        
        return "text"
    
    def action_toggle(self) -> None:
        """Toggle expanded/collapsed state."""
        self.is_expanded = not self.is_expanded
        self.refresh()
    
    def action_copy_result(self) -> None:
        """Copy result to clipboard."""
        if self.execution and self.execution.result:
            try:
                import pyperclip
                result_str = str(self.execution.result)
                pyperclip.copy(result_str)
                self.notify("Result copied to clipboard ✅")
            except:
                self.notify("Clipboard not available 📋")
    
    def update_execution(self, execution: UnifiedExecution) -> None:
        """Update the execution data and refresh display."""
        self.execution = execution
        self.refresh()
    
    def update_status(self, status: ExecutionStatus, 
                     result: Optional[Any] = None,
                     error: Optional[str] = None) -> None:
        """Update execution status."""
        if self.execution:
            from datetime import datetime
            self.execution.status = status
            if result is not None:
                self.execution.result = result
            if error:
                self.execution.error = error
            if status in [ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]:
                self.execution.completed_at = datetime.now()
            self.refresh()
    
    def watch_execution(self, execution: Optional[UnifiedExecution]) -> None:
        """React to execution changes."""
        if execution:
            # Update display when execution changes
            self.refresh()
