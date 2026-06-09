"""Penguin CLI - Command Line Interface for Penguin AI Assistant.

This module provides command-line tools for interacting with Penguin, including:
- Interactive chat sessions
- Task management and execution
- Project creation and management
- Agent configuration and control

Example Usage:
    ```bash
    # Interactive chat
    penguin
    
    # Run a specific task
    penguin task run "Create a simple web server"
    
    # Manage projects
    penguin project create "My Project" "A sample project"
    penguin project list
    
    # Agent controls
    penguin agent spawn --purpose="code-review"
    ```

The CLI is built with Typer and Rich for an excellent developer experience.
"""

from typing import Optional

# CLI Application - will be imported when typer/rich are available
_cli_app: Optional[object] = None

def get_cli_app():
    """Get the CLI application instance.
    
    Returns:
        The Typer CLI application, or None if CLI dependencies not available
    """
    global _cli_app
    if _cli_app is None:
        try:
            from .cli import app
            _cli_app = app
        except ImportError:
            # CLI dependencies not available
            return None
    return _cli_app


__all__ = ["cli_app", "get_cli_app", "journal_command", "PenguinCLI"]

class PenguinCLI:
    """Main CLI interface class for programmatic access."""
    
    def __init__(self):
        """Initialize CLI interface.""" 
        self.app = get_cli_app()
        if not self.app:
            raise ImportError(
                "CLI dependencies not available. Install with: pip install penguin-ai"
            )
    
    def run(self, args: Optional[list] = None):
        """Run CLI with given arguments."""
        if args is None:
            args = []
        # This would integrate with typer's testing functionality
        # For now, it's a placeholder
        return self.app(args)


def __getattr__(name: str) -> object:
    """Lazy-load optional CLI exports."""
    if name == "cli_app":
        app = get_cli_app()
        if app is None:
            raise AttributeError(
                "CLI dependencies not available. Install with: pip install penguin-ai"
            )
        return app

    if name == "journal_command":
        try:
            from .journal_commands import journal_command
        except ImportError as exc:
            raise AttributeError("journal_command is unavailable") from exc
        return journal_command

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
