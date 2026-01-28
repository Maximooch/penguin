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


# Try to expose CLI components
try:
    from .cli import app as cli_app
    # Note: individual command modules don't exist yet, so we'll skip those imports for now
    
    __all__ = [
        "cli_app",
        "get_cli_app",
        "PenguinCLI"
    ]
    
    # Import PenguinCLI class if available
    try:
        from .cli import PenguinCLI
    except ImportError:
        # PenguinCLI class might not be available in all setups
        pass
    
except ImportError:
    # CLI dependencies not available (minimal install)
    __all__ = ["get_cli_app"]


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