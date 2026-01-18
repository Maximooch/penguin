"""
Session Manager - Handle prompt session and response display methods.

Extracted from PenguinCLI during Phase 4, Stage 1.
"""

from rich.table import Table
from rich.panel import Panel
from typing import Dict, Any
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style


class SessionManager:
    """Manages prompt sessions and displays various response types.

    Handles:
    - Multi-line prompt session configuration
    - Checkpoints display
    - Token usage display
    - Truncations display
    """

    def __init__(self, console, user_color: str, penguin_color: str):
        """Initialize SessionManager.

        Args:
            console: Rich console instance
            user_color: Color for user messages
            penguin_color: Color for Penguin messages
        """
        self.console = console
        self.user_color = user_color
        self.penguin_color = penguin_color

    def create_prompt_session(self) -> PromptSession:
        """Create and configure a prompt_toolkit session with multi-line support"""
        # Define key bindings
        kb = KeyBindings()

        # Add keybinding for Alt+Enter to create a new line
        @kb.add(Keys.Escape, Keys.Enter)
        def _(event):
            """Insert a new line when Alt (or Option) + Enter is pressed."""
            event.current_buffer.insert_text("\n")

        # Add keybinding for Enter to submit
        @kb.add(Keys.Enter)
        def _(event):
            """Submit of input when Enter is pressed without modifiers."""
            # If there's already text and cursor is at the end, submit
            buffer = event.current_buffer
            if buffer.text and buffer.cursor_position == len(buffer.text):
                buffer.validate_and_handle()
            else:
                # Otherwise insert a new line
                buffer.insert_text("\n")

        # Add a custom style
        style = Style.from_dict({
            "prompt": f"bold {self.user_color}",
        })

        # Create a PromptSession
        return PromptSession(
            key_bindings=kb,
            style=style,
            multiline=True,  # Enable multi-line editing
            vi_mode=False,  # Use Emacs keybindings by default
            wrap_lines=True,  # Wrap long lines
            complete_in_thread=True,
        )

    def display_checkpoints_response(self, response: Dict[str, Any]) -> None:
        """Display checkpoints in a nicely formatted table"""
        try:
            from rich.table import Table

            checkpoints = response.get("checkpoints", [])

            if not checkpoints:
                self.console.print("No checkpoints found", style="system")
                return

            # Create table for checkpoints
            table = Table(show_header=True, header_style="bold magenta", title="📍 Checkpoints")
            table.add_column("ID", style="cyan", width=12)
            table.add_column("Type", style="blue", width=8)
            table.add_column("Name", style="green")

            for checkpoint in checkpoints:
                table.add_row(
                    checkpoint.get("id", ""),
                    checkpoint.get("type", ""),
                    checkpoint.get("name", ""),
                )

            self.console.print(table)
        except Exception as e:
            self.console.print(f"Error displaying checkpoints: {e}", style="red")

    def display_token_usage_response(self, response: Dict[str, Any]) -> None:
        """Display enhanced token usage with categories"""
        try:
            from rich.table import Table
            from rich.panel import Panel

            token_data = response.get("token_usage", response.get("token_usage_detailed", {}))

            # Create main usage table
            table = Table(show_header=True, header_style="bold magenta", title="📊 Token Usage")
            table.add_column("Category", style="cyan")
            table.add_column("Tokens", style="green", justify="right")
            table.add_column("Percentage", style="yellow", justify="right")

            # Get category breakdown if available
            categories = token_data.get("categories", {})

            for category, tokens in categories.items():
                total = token_data.get("total", 0)
                percentage = (tokens / total * 100) if total > 0 else 0
                table.add_row(category, str(tokens), f"{percentage:.1f}%")

            self.console.print(table)
        except Exception as e:
            self.console.print(f"Error displaying token usage: {e}", style="red")

    def display_truncations_response(self, response: Dict[str, Any]) -> None:
        """Display truncation events in a nicely formatted table"""
        try:
            from rich.table import Table
            from rich.panel import Panel

            truncations = response.get("truncations", [])

            if not truncations:
                self.console.print("✓ No truncation events - context window is within budget", style="system")
                return

            # Show summary panel first
            total_removed = response.get("total_messages_removed", 0)
            total_freed = response.get("total_tokens_freed", 0)
            total_events = response.get("total_events", 0)

            summary_panel = Panel(
                f"Total: {total_events} events\nMessages removed: {total_removed}\nTokens freed: {total_freed}",
                title="📉 Truncation Summary",
                border_style="yellow",
                padding=(1, 1),
            )
            self.console.print(summary_panel)

            # Create table for truncations
            table = Table(show_header=True, header_style="bold magenta", title="📉 Truncation Events")
            table.add_column("Time", style="dim", width=12)
            table.add_column("Type", style="cyan")
            table.add_column("Resource", style="white", max_width=30)
            table.add_column("Result", style="bold")
            table.add_column("Reason", max_width=35)

            for truncation in truncations:
                # Parse timestamp to show just time
                time_str = truncation.timestamp.split("T")[1][:8] if "T" in truncation.timestamp else truncation.timestamp[:8]

                # Color result
                result_color = {"allow": "green", "ask": "yellow", "deny": "red"}.get(truncation.result, "white")
                result_display = f"[{result_color}]{truncation.result.upper()}[/{result_color}]"

                # Truncate resource if needed
                resource = truncation.resource
                if len(resource) > 30:
                    resource = "..." + resource[-27:]

                table.add_row(
                    time_str,
                    truncation.operation,
                    resource,
                    result_display,
                    truncation.reason[:35] + "..." if len(truncation.reason) > 35 else truncation.reason,
                )

            self.console.print(table)
        except Exception as e:
            self.console.print(f"Error displaying truncations: {e}", style="red")
