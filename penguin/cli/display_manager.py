"""
Display Manager - Handle all display logic for CLI.

Extracted from PenguinCLI during Phase 4, Stage 2.
"""

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

if TYPE_CHECKING:
    from penguin.cli.renderer import UnifiedRenderer


class DisplayManager:
    """Manages all display operations for the CLI.

    Handles:
    - Message display (user, assistant, system, error)
    - Code block formatting and highlighting
    - Diff rendering
    - Action results display
    - List responses display
    - Checkpoints, token usage, truncations display
    - File read results display
    - Code output panels
    """

    def __init__(
        self,
        console: Console,
        renderer: "UnifiedRenderer",
        panel_padding: Optional[Tuple[int, int]] = None,
    ) -> None:
        """Initialize DisplayManager.

        Args:
            console: Rich console instance
            renderer: UnifiedRenderer instance
            panel_padding: Padding for panels
        """
        self.console = console
        self.renderer = renderer
        self.panel_padding = panel_padding

    def display_message(self, content: Any, role: str = "assistant") -> None:
        """Display a message with appropriate styling.

        Args:
            content: Message content to display
            role: Message role (user, assistant, system, error)
        """
        rendered = self.renderer.render_message(content, role=role, as_panel=True)
        if rendered is not None:
            self.console.print(rendered)

    def format_code_block(
        self, message: str, code: str, language: str, original_block: str
    ) -> str:
        """Format a code block with syntax highlighting and return updated message.

        Args:
            message: Original message containing code block
            code: Code content
            language: Programming language
            original_block: Original code block to replace

        Returns:
            Updated message with code block replaced by placeholder
        """
        rendered = self.renderer.render_code_block(code, language)
        if rendered is not None:
            self.console.print(rendered)

        # Replace in original message with a note
        lang_display = self.renderer.get_language_display_name(language)
        placeholder = f"[Code block displayed above ({lang_display})]"
        return message.replace(original_block, placeholder)

    def display_file_read_result(self, result_text: str) -> None:
        """Display file read result.

        Args:
            result_text: File read result text
        """
        # Extract file path and content
        lines = result_text.split("\n")
        if not lines:
            return

        file_path = lines[0].strip()
        content = "\n".join(lines[1:])

        # Detect language
        language = self.renderer.detect_language(content)

        # Display code with syntax highlighting
        rendered = self.renderer.render_code_block(content, language)
        if rendered is not None:
            self.console.print(rendered)

        # Display file path info
        self.console.print(f"[dim]Read from: {file_path}[/dim]")

    def display_action_result(self, result: Dict[str, Any]) -> None:
        """Display action result with appropriate formatting.

        Args:
            result: Action result dictionary
        """
        action_type = result.get("action_type", result.get("action", "unknown"))
        action_name = result.get("action_name", result.get("name", action_type))
        status = result.get("status", "unknown")
        output = result.get("output", result.get("result", ""))

        # Check if result contains diff
        if isinstance(output, str) and self.renderer.is_diff(output):
            self.renderer.render_diff_result(output, action_type)
            return

        # Display action info
        action_panel = Panel(
            f"[bold]Action:[/bold] {action_name}\n[bold]Status:[/bold] {status}",
            title=f"🔧 {action_type}",
            border_style="yellow",
            padding=(1, 1),
        )
        self.console.print(action_panel)

        # Display output if available
        if output and isinstance(output, str):
            # Check if it's code
            if "```" in output or "<code>" in output:
                # Extract and format code block
                language = self.renderer.detect_language(output)
                rendered = self.renderer.render_code_block(output, language)
                if rendered is not None:
                    self.console.print(rendered)
            else:
                # Display as plain text
                output_panel = Panel(
                    output,
                    title="Output",
                    border_style="green",
                    padding=(1, 1),
                )
                self.console.print(output_panel)

    def display_list_response(self, response: Dict[str, Any]) -> None:
        """Display list response in a nicely formatted table.

        Args:
            response: List response dictionary
        """
        projects = response.get("projects")
        tasks = response.get("tasks")
        if isinstance(projects, list) and isinstance(tasks, list):
            summary = response.get("summary", {})
            summary_text = (
                f"**Summary**: {summary.get('total_projects', 0)} projects, "
                f"{summary.get('total_tasks', 0)} tasks "
                f"({summary.get('active_tasks', 0)} active)"
            )
            self.display_message(summary_text, "system")

            if projects:
                self.display_message("## Projects", "system")
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("ID", style="dim", width=8)
                table.add_column("Name", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("Tasks", style="yellow", width=6)
                table.add_column("Created", style="dim")

                for project in projects:
                    table.add_row(
                        project.get("id", "")[:8],
                        project.get("name", ""),
                        project.get("status", ""),
                        str(project.get("task_count", 0)),
                        project.get("created_at", "")[:16]
                        if project.get("created_at")
                        else "",
                    )

                self.console.print(table)

            if tasks:
                self.display_message("## Tasks", "system")
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("ID", style="dim", width=8)
                table.add_column("Title", style="white")
                table.add_column("Status", style="green")
                table.add_column("Priority", style="yellow", width=8)
                table.add_column("Project", style="cyan", width=8)
                table.add_column("Created", style="dim")

                for task in tasks:
                    project_id = task.get("project_id", "")
                    project_display = project_id[:8] if project_id else "Independent"

                    table.add_row(
                        task.get("id", "")[:8],
                        task.get("title", ""),
                        task.get("status", ""),
                        str(task.get("priority", 0)),
                        project_display,
                        task.get("created_at", "")[:16]
                        if task.get("created_at")
                        else "",
                    )

                self.console.print(table)

            if not projects and not tasks:
                self.display_message(
                    "No projects or tasks found. Create some with `/project create` or `/task create`.",
                    "system",
                )
            return

        items = response.get("items", [])
        list_type = response.get("list_type", "list")

        if not items:
            self.console.print(f"[dim]No {list_type} items found.[/dim]")
            return

        # Create table
        table = Table(title=f"📋 {list_type.title()}", show_header=True)
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="white")
        table.add_column("Type", style="green")

        for item in items:
            table.add_row(
                item.get("id", ""),
                item.get("name", ""),
                item.get("type", ""),
            )

        self.console.print(table)

    def display_checkpoints_response(self, response: Dict[str, Any]) -> None:
        """Display checkpoints in a nicely formatted table.

        Args:
            response: Checkpoints response dictionary
        """
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

    def display_token_usage_response(self, response: Dict[str, Any]) -> None:
        """Display enhanced token usage with categories.

        Args:
            response: Token usage response dictionary
        """
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

    def display_truncations_response(self, response: Dict[str, Any]) -> None:
        """Display truncation events in a nicely formatted table.

        Args:
            response: Truncations response dictionary
        """
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

    def display_code_output_panel(
        self, code_output: str, language: str, title: str = "Output"
    ) -> None:
        """Display code output panel.

        Args:
            code_output: Code output to display
            language: Programming language
            title: Panel title
        """
        lang_display = self.renderer.get_language_display_name(language)
        output_panel = Panel(
            Syntax(code_output, language, theme="monokai", word_wrap=True),
            title=f"📤 {lang_display} {title}",
            title_align="left",
            border_style="green",
            padding=(1, 2),
        )
        self.console.print(output_panel)

    def render_diff_message(self, message: str) -> bool:
        """Render system messages that contain diff content.

        Args:
            message: Message containing diff content

        Returns:
            True if diff was rendered, False otherwise
        """
        # Delegate to UnifiedRenderer
        return self.renderer.render_diff_message(message)

    def display_diff_result(self, result_text: str, action_type: str = "action", status_icon: str = "🔧") -> bool:
        """Render diff output with syntax highlighting when possible.

        Args:
            result_text: Text containing diff output
            action_type: Type of action that produced the diff
            status_icon: Icon to display in the title

        Returns:
            True if diff was rendered, False otherwise
        """
        # Delegate to UnifiedRenderer
        return self.renderer.render_diff_result(result_text, action_type, status_icon)
