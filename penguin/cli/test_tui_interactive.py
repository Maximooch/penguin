#!/usr/bin/env python3
"""
Interactive test script for Penguin TUI with new widgets.

This script runs a mock TUI session to test the new widget system.
Run with: python test_tui_interactive.py
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# Add penguin to path
sys.path.insert(0, str(Path(__file__).parent))

from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.widgets import Header, Footer, Input, Static, Button
from textual.reactive import reactive
from rich.panel import Panel

from penguin.cli.widgets import ToolExecutionWidget
from penguin.cli.widgets.unified_display import UnifiedExecution, ExecutionAdapter, ExecutionStatus, ExecutionType


class MockTUIApp(App):
    """Mock TUI app to test widgets."""
    
    CSS = """
    Screen {
        background: #0c141f;
    }
    
    #message-area {
        height: 1fr;
        border: round #89cff0;
        padding: 1;
    }
    
    #button-panel {
        height: 3;
        layout: horizontal;
        padding: 1;
    }
    
    Button {
        margin: 0 1;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("t", "add_tool", "Add Tool"),
        ("a", "add_action", "Add Action"),
        ("e", "add_error", "Add Error"),
        ("s", "update_status", "Update Status"),
    ]
    
    def __init__(self):
        super().__init__()
        self.tool_widgets = []
        self.widget_counter = 0
    
    def compose(self) -> ComposeResult:
        """Create the UI."""
        yield Header()
        
        with Container():
            yield VerticalScroll(id="message-area")
            
            with Container(id="button-panel"):
                yield Button("Add Tool [T]", id="btn-tool", variant="primary")
                yield Button("Add Action [A]", id="btn-action", variant="primary")
                yield Button("Add Error [E]", id="btn-error", variant="error")
                yield Button("Update Status [S]", id="btn-status", variant="success")
        
        yield Footer()
    
    async def on_mount(self) -> None:
        """Called when app starts."""
        # Add welcome message
        welcome = Panel(
            "Interactive TUI Widget Test\n\n"
            "Press:\n"
            "• [T] to add a tool execution\n"
            "• [A] to add an action execution\n"
            "• [E] to add an error\n"
            "• [S] to update last widget status\n"
            "• [Q] to quit",
            title="Welcome",
            border_style="cyan"
        )
        self.query_one("#message-area").mount(Static(welcome))
    
    def action_add_tool(self) -> None:
        """Add a tool execution widget."""
        self.widget_counter += 1
        
        # Create sample tool execution
        execution = ExecutionAdapter.from_tool(
            tool_name="workspace_search",
            tool_input={
                "query": f"test query {self.widget_counter}",
                "max_results": 5
            },
            tool_id=f"tool-{self.widget_counter}"
        )
        execution.status = ExecutionStatus.RUNNING
        
        # Create and mount widget
        widget = ToolExecutionWidget(execution)
        self.query_one("#message-area").mount(widget)
        self.tool_widgets.append(widget)
        
        # Simulate completion after delay
        self.call_later(self._complete_tool, widget)
    
    def action_add_action(self) -> None:
        """Add an action execution widget (XML-style action tag)."""
        self.widget_counter += 1
        
        # Rotate through different action types to test parsing
        action_types = [
            ("workspace_search", f"authentication flow {self.widget_counter}:10"),
            ("execute", f"print('Test {self.widget_counter}')\nx = {self.widget_counter}"),
            ("enhanced_read", f"src/file_{self.widget_counter}.py:true:50"),
            ("memory_search", f"query {self.widget_counter}:5:all:test,demo"),
            ("add_summary_note", f"progress:Completed step {self.widget_counter} of testing"),
        ]
        
        action_type, params = action_types[self.widget_counter % len(action_types)]
        
        # Create sample action execution with XML-style params
        execution = ExecutionAdapter.from_action(
            action_type=action_type,
            params=params,  # Colon-separated string params
            action_id=f"action-{self.widget_counter}"
        )
        execution.status = ExecutionStatus.RUNNING
        
        # Create and mount widget
        widget = ToolExecutionWidget(execution)
        self.query_one("#message-area").mount(widget)
        self.tool_widgets.append(widget)
        
        # Simulate completion
        self.call_later(self._complete_action, widget)
    
    def action_add_error(self) -> None:
        """Add an error widget."""
        self.widget_counter += 1
        
        # Create error execution
        execution = ExecutionAdapter.from_error(
            error="Sample error: Something went wrong!",
            context=f"Error context {self.widget_counter}"
        )
        
        # Create and mount widget
        widget = ToolExecutionWidget(execution)
        self.query_one("#message-area").mount(widget)
        self.tool_widgets.append(widget)
    
    def action_update_status(self) -> None:
        """Update the status of the last widget."""
        if self.tool_widgets:
            widget = self.tool_widgets[-1]
            
            # Cycle through statuses
            current = widget.execution.status
            if current == ExecutionStatus.PENDING:
                new_status = ExecutionStatus.RUNNING
            elif current == ExecutionStatus.RUNNING:
                new_status = ExecutionStatus.SUCCESS
                widget.update_status(new_status, result="Operation completed successfully!")
            elif current == ExecutionStatus.SUCCESS:
                new_status = ExecutionStatus.FAILED
                widget.update_status(new_status, error="Simulated failure")
            else:
                new_status = ExecutionStatus.PENDING
                widget.update_status(new_status)
    
    def _complete_tool(self, widget: ToolExecutionWidget) -> None:
        """Complete a tool execution after delay."""
        result = {
            "matches": [
                {"file": "auth.py", "line": 42, "content": "def authenticate(user):"},
                {"file": "login.py", "line": 15, "content": "authenticate(request.user)"},
            ],
            "total_matches": 2
        }
        widget.update_status(ExecutionStatus.SUCCESS, result=result)
    
    def _complete_action(self, widget: ToolExecutionWidget) -> None:
        """Complete an action execution."""
        # Generate appropriate result based on action type
        action_type = widget.execution.name
        
        if action_type == "workspace_search":
            result = {
                "matches": [
                    {"file": "auth.py", "line": 42, "content": "def authenticate():"},
                    {"file": "models.py", "line": 15, "content": "class Authentication:"},
                ],
                "query": widget.execution.parameters.get("query", "unknown"),
                "total": 2
            }
        elif action_type == "execute":
            result = f"Code executed successfully:\n{widget.execution.parameters.get('code', '')[:100]}\n\nOutput: Success"
        elif action_type == "enhanced_read":
            path = widget.execution.parameters.get("path", "unknown")
            result = f"File: {path}\n1| def main():\n2|     print('Hello')\n3|     return 0"
        elif action_type == "memory_search":
            result = f"Found 3 memories matching '{widget.execution.parameters.get('query', 'unknown')}'"
        elif action_type == "add_summary_note":
            result = f"Note added to category: {widget.execution.parameters.get('category', 'general')}"
        else:
            result = f"Action '{action_type}' completed successfully"
        
        widget.update_status(ExecutionStatus.SUCCESS, result=result)
    
    def call_later(self, callback, *args):
        """Schedule a callback after 2 seconds."""
        async def delayed_call():
            await asyncio.sleep(2)
            callback(*args)
        
        asyncio.create_task(delayed_call())
    
    async def on_button_pressed(self, event) -> None:
        """Handle button presses."""
        button_id = event.button.id
        
        if button_id == "btn-tool":
            self.action_add_tool()
        elif button_id == "btn-action":
            self.action_add_action()
        elif button_id == "btn-error":
            self.action_add_error()
        elif button_id == "btn-status":
            self.action_update_status()


def main():
    """Run the mock TUI app."""
    print("Starting interactive TUI widget test...")
    print("This will open a Textual interface to test the new widgets.")
    print("Press 'q' to quit once the app opens.\n")
    
    app = MockTUIApp()
    app.run()
    
    print("\nTest completed!")

if __name__ == "__main__":
    main()
