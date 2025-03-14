import asyncio
import os
from typing import Dict, List, Optional, Any
import re

from textual.app import App, ComposeResult # type: ignore
from textual.widgets import Header, Footer, Input, Static, Button # type: ignore
from textual.containers import Container, ScrollableContainer, Horizontal, Vertical # type: ignore
from rich.markdown import Markdown # type: ignore
from rich.panel import Panel # type: ignore
from rich.text import Text # type: ignore
from rich.syntax import Syntax # type: ignore
from textual.reactive import reactive # type: ignore
from textual.binding import Binding # type: ignore
from rich.table import Table # type: ignore
from rich.progress import BarColumn, Progress, TextColumn # type: ignore
from textual import log # type: ignore

from penguin.chat.interface import PenguinInterface
from penguin.core import PenguinCore

class MessageWidget(Static):
    """Base class for message widgets."""
    
    def __init__(self, content: str, role: str):
        self.role = role
        
        # Create a properly formatted prefix based on role
        if role == "user":
            prefix = Text("You: ", style="bold green")
            self.sender_name = "You"
        elif role == "assistant":
            prefix = Text("Penguin: ", style="bold blue")
            self.sender_name = "Penguin"
        elif role == "system":
            prefix = Text("System: ", style="bold yellow")
            self.sender_name = "System"
        
        # Process content based on whether it's markdown or contains formatting
        processed_content = self._process_content(content)
        
        # Add the role as a CSS class
        super().__init__(processed_content, classes=role)
    
    def _process_content(self, content: str) -> Any:
        """Process content for proper rendering in Textual."""
        # For markdown content, use Rich's Markdown
        if content.startswith("#") or "```" in content or "*" in content:
            # Use Panel for better visual separation
            return Panel(
                Markdown(content),
                border_style="dim",
                padding=(0, 1),
                expand=True
            )
        else:
            # For regular text, use Rich's Text for better formatting control
            return Text(content)

class ConversationView(ScrollableContainer):
    """Displays the conversation history."""
    
    async def add_message(self, content: str, role: str):
        """Add a message to the conversation."""
        message = MessageWidget(content, role)
        await self.mount(message)
        # Scroll to the bottom
        try:
            await self.scroll_end()
        except (AttributeError, TypeError):
            # Handle different Textual versions
            try:
                self.scroll_end()
            except (AttributeError, TypeError):
                pass

class TokenDisplay(Static):
    """Widget to display token usage statistics."""
    
    # Reactive properties that automatically update the widget when changed
    prompt_tokens = reactive(0)
    completion_tokens = reactive(0)
    total_tokens = reactive(0)
    max_tokens = reactive(0)
    
    def __init__(self, id: str = None):
        super().__init__(id=id)
        self.update_display()
    
    def on_mount(self):
        """Set up styling after mount."""
        self.styles.background = "transparent"
        self.styles.color = "white"
        
    def update_token_stats(self, usage: Dict[str, int]):
        """Update token statistics with new usage data."""
        self.prompt_tokens = usage.get("prompt", 0)
        self.completion_tokens = usage.get("completion", 0)
        self.total_tokens = usage.get("total", 0)
        self.max_tokens = usage.get("max_tokens", 200000)  # Default to MAX_CONTEXT_TOKENS
        self.update_display()
        
    def watch_prompt_tokens(self, value):
        """Watch for changes to prompt tokens."""
        self.update_display()
        
    def watch_completion_tokens(self, value):
        """Watch for changes to completion tokens."""
        self.update_display()
        
    def watch_total_tokens(self, value):
        """Watch for changes to total tokens."""
        self.update_display()
        
    def watch_max_tokens(self, value):
        """Watch for changes to max tokens."""
        self.update_display()
    
    def update_display(self):
        """Update the display with current token statistics."""
        text = Text()
        text.append("Tokens: ", style="dim")
        text.append(f"{self.total_tokens}", style="bold")
        
        # Add percentage of max tokens if available
        if self.max_tokens > 0:
            percentage = (self.total_tokens / self.max_tokens) * 100
            text.append(f" ({percentage:.1f}%)", style="yellow" if percentage > 70 else "green")
        
        text.append(" (")
        text.append(f"I: {self.prompt_tokens}", style="green")
        text.append(" | ")
        text.append(f"O: {self.completion_tokens}", style="blue")
        text.append(")")
        
        self.update(text)

class DetailedTokenDisplay(Static):
    """Widget to display detailed token usage by category."""
    
    def __init__(self, id: str = None):
        super().__init__(id=id)
        self.token_data = {}
    
    def update_token_data(self, token_data: Dict[str, Any]):
        """Update with detailed token data from conversation system."""
        self.token_data = token_data
        self.update_display()
    
    def update_display(self):
        """Update the display with current token statistics by category."""
        if not self.token_data or "error" in self.token_data:
            error_msg = self.token_data.get("error", "No token data available")
            self.update(Text(f"Token data error: {error_msg}", style="red"))
            return
            
        # Extract data
        categories = self.token_data.get("categories", {})
        raw_counts = self.token_data.get("raw_counts", {})
        total_tokens = self.token_data.get("total", 0)
        max_tokens = self.token_data.get("max_tokens", 0)
        
        # Create a table for display
        table = Table(title="Token Usage by Category")
        table.add_column("Category", style="cyan")
        table.add_column("Tokens", style="green")
        table.add_column("% of Total", style="yellow")
        table.add_column("% of Context", style="blue")
        
        # Add rows for each category
        for category, percentage in sorted(categories.items(), key=lambda x: x[1], reverse=True):
            token_count = raw_counts.get(category, 0)
            table.add_row(
                category,
                str(token_count),
                f"{percentage * 100:.1f}%",
                f"{(token_count / max_tokens * 100) if max_tokens else 0:.1f}%"
            )
        
        # Add total row
        table.add_row(
            "TOTAL", 
            str(total_tokens),
            "100.0%",
            f"{(total_tokens / max_tokens * 100) if max_tokens else 0:.1f}%",
            style="bold"
        )
        
        # Create progress bars for visual representation
        progress = Progress(
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("{task.completed}/{task.total}"),
            TextColumn("({task.percentage:.0f}%)"),
        )
        
        if max_tokens:
            progress.add_task("Total", total=max_tokens, completed=total_tokens)
            for category, token_count in raw_counts.items():
                if token_count > 0:
                    category_name = category.split('_')[-1].capitalize()
                    progress.add_task(f"{category_name}", total=max_tokens, completed=token_count)
        
        # Combine table and progress bars
        from rich.console import Group # type: ignore
        self.update(Group(table, progress))

class StatusBar(Static):
    """Shows current status and token usage."""
    
    def __init__(self, id: str = None):
        # Initialize without text parameter
        super().__init__(id=id)
        # Set initial text after initialization
        self.update_status("Ready")
    
    def update_status(self, status: str, tokens: Dict[str, int] = None):
        """Update status display."""
        text = status
        if tokens:
            text += f" | Tokens: {tokens.get('total', 0)}"
        self.update(text)

class CodeEditorWidget(Static):
    """A widget for displaying and editing code."""
    
    code = reactive("")
    language = reactive("python")
    filename = reactive(None)
    
    def __init__(self, id: str = None):
        super().__init__(id=id)
        self.show_line_numbers = True
        self.theme = "monokai"
    
    def on_mount(self):
        """Set up styling after mount."""
        self.set_content("")
    
    def set_content(self, code: str, language: str = "python", filename: str = None):
        """Set the code content and language."""
        self.code = code
        self.language = language
        self.filename = filename
        self.update_display()
    
    def watch_code(self, value):
        """Watch for changes to code."""
        self.update_display()
    
    def watch_language(self, value):
        """Watch for changes to language."""
        self.update_display()
    
    def update_display(self):
        """Update the display with current code."""
        if not self.code.strip():
            self.update(Panel("No code to display", title="Code Editor", border_style="blue"))
            return
            
        syntax = Syntax(
            self.code,
            self.language,
            theme=self.theme,
            line_numbers=self.show_line_numbers,
            word_wrap=True
        )
        
        title = f"Code Editor - {self.language.upper()}"
        if self.filename:
            title = f"{title} - {self.filename}"
            
        self.update(Panel(
            syntax,
            title=title,
            title_align="left",
            border_style="blue",
            padding=(1, 2)
        ))
        
    async def copy_to_clipboard(self):
        """Copy code to clipboard."""
        # Implement clipboard functionality
        # This might require platform-specific code or an external library
        pass
        
    async def save_to_file(self):
        """Save code to a file."""
        if not self.code.strip():
            return
            
        filename = self.filename or f"penguin_code_{self.language}.{self.language}"
        # Create a file dialog or use a simple text input
        # For now, save to a fixed location
        path = os.path.expanduser(f"~/penguin_code/{filename}")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        with open(path, "w") as f:
            f.write(self.code)
        
        return path

class CodeToolbar(Static):
    """Toolbar for code editor actions."""
    
    def __init__(self, editor, id: str = None):
        super().__init__(id=id)
        self.editor = editor
    
    def compose(self) -> ComposeResult:
        """Create child widgets for the toolbar."""
        yield Button("Copy", id="copy-btn")
        yield Button("Save", id="save-btn")
        yield Button("Run", id="run-btn")
        yield Button("Hide", id="hide-btn")
    
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        button_id = event.button.id
        
        if button_id == "copy-btn":
            await self.editor.copy_to_clipboard()
        elif button_id == "save-btn":
            path = await self.editor.save_to_file()
            if path:
                await self.app.conversation_view.add_message(f"Code saved to {path}", "system")
        elif button_id == "run-btn":
            # Execute code via the core
            if hasattr(self.app, "interface") and self.editor.code.strip():
                response = await self.app.interface.process_input({
                    "text": f"/run\n```{self.editor.language}\n{self.editor.code}\n```"
                })
                if "assistant_response" in response:
                    await self.app.conversation_view.add_message(response["assistant_response"], "assistant")
        elif button_id == "hide-btn":
            # Hide the code editor
            await self.app.toggle_code_editor(False)

class PenguinTUI(App):
    """Penguin Terminal UI using Textual."""
    
    # Add bindings for the menu
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
        Binding("ctrl+s", "save", "Save"),
        Binding("f1", "help", "Help"),
        Binding("f2", "token_details", "Token Details"),
        Binding("f3", "toggle_code_editor", "Toggle Code Editor"),
    ]
    
    CSS = """
    #main-container {
        layout: horizontal;
        height: 1fr;
    }
    
    #conversation-container {
        width: 2fr;
        height: 1fr;
    }
    
    #code-container {
        width: 1fr;
        height: 1fr;
        display: none;
    }
    
    #conversation-view {
        width: 100%;
        height: 1fr;
        border: solid $accent;
        overflow: auto;
    }
    
    #code-editor {
        width: 100%;
        height: 1fr;
        border: solid $primary;
        overflow: auto;
    }
    
    #code-toolbar {
        width: 100%;
        height: auto;
        background: $primary-darken-1;
        color: $text;
        layout: horizontal;
    }
    
    #code-toolbar Button {
        margin: 1 1;
    }
    
    #status-bar {
        height: 1;
        dock: bottom;
    }
    
    #token-display {
        dock: top;
        height: 1;
        content-align: right middle;
        padding: 0 2;
        background: $surface;
        color: $text;
    }
    
    MessageWidget {
        margin: 1 0;
        padding: 1 1 1 2;
        border: solid transparent;
        border-left: heavy transparent;
    }
    
    MessageWidget.user {
        border-left: heavy green;
        background: $panel-darken-1;
    }
    
    MessageWidget.assistant {
        border-left: heavy blue;
        background: $panel;
    }
    
    MessageWidget.system {
        border-left: heavy yellow;
        color: $text-muted;
        background: $surface-darken-1;
        padding-left: 4;
    }
    
    Header {
        dock: top;
        background: $primary;
    }
    
    Header > .header--title {
        color: $text;
        text-style: bold;
        text-align: center;
    }
    
    Footer {
        dock: bottom;
    }
    """
    
    def __init__(self, core: PenguinCore):
        super().__init__()
        self.interface = PenguinInterface(core)
        self.code_editor_visible = False
        
    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header(show_clock=True, name="Menu: Penguin AI Assistant", icon="🐧")
        yield TokenDisplay(id="token-display")
        
        with Horizontal(id="main-container"):
            with Container(id="conversation-container"):
                yield ConversationView(id="conversation-view")
            
            with Container(id="code-container"):
                with Vertical():
                    yield CodeToolbar(None, id="code-toolbar")
                    yield CodeEditorWidget(id="code-editor")
        
        yield Input(id="command-input", placeholder="Enter a message or command...")
        yield StatusBar(id="status-bar")
        yield Footer()
    
    async def on_mount(self):
        """Set up the UI when the app starts."""
        # Set up code toolbar to reference the editor
        code_toolbar = self.query_one("#code-toolbar")
        code_editor = self.query_one("#code-editor")
        code_toolbar.editor = code_editor
        
        # Set focus to input
        self.command_input = self.query_one("#command-input")
        self.command_input.focus()
        
        # Get other components
        self.conversation_view = self.query_one("#conversation-view")
        self.status_bar = self.query_one("#status-bar")
        self.token_display = self.query_one("#token-display")
        self.code_editor = code_editor
        self.code_container = self.query_one("#code-container")
        
        # Create a detailed token display (not mounted by default)
        self.detailed_token_display = DetailedTokenDisplay()
        
        # Register callbacks
        self.interface.register_progress_callback(self.on_progress_update)
        self.interface.register_token_callback(self.on_token_update)
        
        # Update token display with initial values
        initial_usage = self.interface.get_token_usage()
        self.token_display.update_token_stats(initial_usage)
        
        # Show welcome message
        await self.conversation_view.add_message(
            "# Welcome to Penguin AI Assistant\n\nType a message or use commands like `/help` to get started. Press F3 to toggle the code editor panel.",
            "system"
        )
    
    async def on_input_submitted(self, event):
        """Handle user input."""
        user_input = event.value
        self.command_input.value = ""  # Clear input
        
        if not user_input.strip():
            return
            
        if user_input.strip().lower() == "exit":
            await self.conversation_view.add_message("Goodbye! Shutting down...", "system")
            await asyncio.sleep(1)
            await self.shutdown()
            return
            
        # Handle token detail command
        if user_input.strip().lower() == "/tokens detail":
            await self.show_token_details()
            return
            
        # Handle token reset command
        if user_input.strip().lower() == "/tokens reset":
            try:
                response = await self.interface.handle_command("tokens reset")
                await self.conversation_view.add_message(response.get("status", "Token counters reset"), "system")
                # Update token display
                self.token_display.update_token_stats(self.interface.get_token_usage())
            except Exception as e:
                await self.conversation_view.add_message(f"Error resetting tokens: {str(e)}", "system")
            return
            
        # Handle basic token command
        if user_input.strip().lower() == "/tokens":
            usage = self.interface.get_token_usage()
            await self.conversation_view.add_message(
                f"Current Token Usage:\n"
                f"• Input: {usage['prompt']}\n"
                f"• Output: {usage['completion']}\n"
                f"• Total: {usage['total']}", 
                "system"
            )
            return
            
        # Show user message
        await self.conversation_view.add_message(user_input, "user")
        
        # Update status
        self.status_bar.update_status("Processing...")
        
        try:
            # Process input
            response = await self.interface.process_input({"text": user_input})
            
            # Check for exit
            if "status" in response and response["status"] == "exit":
                await self.conversation_view.add_message("Goodbye! Shutting down...", "system")
                # Add a small delay so the message is visible
                await asyncio.sleep(1)
                await self.shutdown()
                return
                
            # Check for code blocks in the response
            if "assistant_response" in response:
                response_text = response["assistant_response"]
                code_blocks = self.extract_code_blocks(response_text)
                
                if code_blocks and not self.code_editor_visible:
                    # Show the code editor if we found code blocks
                    await self.toggle_code_editor(True)
                    
                # Display the last code block in the editor
                if code_blocks:
                    lang, code = code_blocks[-1]
                    self.code_editor.set_content(code, lang)
                
                # Show the response in the conversation view
                await self.conversation_view.add_message(response_text, "assistant")
                
            # Show errors
            if "error" in response:
                await self.conversation_view.add_message(f"Error: {response['error']}", "system")
                
            # Show action results
            if "action_results" in response:
                for result in response["action_results"]:
                    if isinstance(result, dict) and "result" in result:
                        await self.conversation_view.add_message(result["result"], "system")

            # Show help
            if "help" in response and "commands" in response:
                help_text = f"# Available Commands\n\n"
                for cmd in response["commands"]:
                    help_text += f"- `{cmd}`\n"
                await self.conversation_view.add_message(help_text, "system")
                
            # Show token usage details if requested
            if "token_usage_detailed" in response:
                await self.show_detailed_token_data(response["token_usage_detailed"])
        except Exception as e:
            # Show error
            await self.conversation_view.add_message(f"Error: {str(e)}", "system")
        finally:
            # Update status
            self.status_bar.update_status("Ready")
    
    def on_progress_update(self, iteration: int, max_iterations: int, message: Optional[str] = None):
        """Handle progress updates."""
        status = f"Processing... ({iteration}/{max_iterations})"
        if message:
            status += f" {message}"
        self.status_bar.update_status(status)
    
    def on_token_update(self, usage: Dict[str, int]):
        """Handle token usage updates."""
        # Use Textual's log function for debugging
        log(f"Token update received: {usage}")
        
        self.status_bar.update_status("Ready")
        self.token_display.update_token_stats(usage)
        
        # If we have conversation system token data, update that too
        if hasattr(self.interface.core, 'conversation_system'):
            try:
                detailed_data = self.get_detailed_token_data()
                log("Detailed token data:", detailed_data)
                # Make sure we're only updating if the detailed_token_display exists
                if hasattr(self, "detailed_token_display"):
                    self.detailed_token_display.update_token_data(detailed_data)
            except Exception as e:
                # Use Textual's log.error for error logging
                log.error(f"Error updating detailed token data: {str(e)}")

    async def add_system_message(self, content: str):
        """Add a formatted system message."""
        # Create a more structured system message
        text = Text(content)
        panel = Panel(
            text,
            title="System Information",
            border_style="yellow",
            padding=(1, 2)
        )
        
        message = MessageWidget(f"```\n{content}\n```", "system")
        await self.mount(message)
        
        try:
            await self.scroll_end()
        except (AttributeError, TypeError):
            try:
                self.scroll_end()
            except (AttributeError, TypeError):
                pass
                
    def get_detailed_token_data(self) -> Dict[str, Any]:
        """Get detailed token usage data from the conversation system."""
        if not hasattr(self.interface.core, 'conversation_system'):
            return {"error": "Conversation system not available"}
            
        try:
            # Get basic token usage first (this should always work)
            basic_usage = self.interface.get_token_usage()
            
            # Build a basic result structure that doesn't depend on detailed allocations
            result = {
                "categories": {},  # Will populate if available
                "total": self.interface.core.total_tokens_used,
                "max_tokens": getattr(self.interface.core.conversation_system, "max_tokens", 200000)
            }
            
            # Try to get allocations if the method exists
            if hasattr(self.interface.core.conversation_system, "get_current_allocations"):
                try:
                    allocations = self.interface.core.conversation_system.get_current_allocations()
                    result["categories"] = {str(category.name): value for category, value in allocations.items()}
                except Exception as e:
                    log.error(f"Error getting allocations: {e}")
            
            # Try to get raw counts if _token_budgets exists
            result["raw_counts"] = {}
            if hasattr(self.interface.core.conversation_system, "_token_budgets"):
                for category, budget in self.interface.core.conversation_system._token_budgets.items():
                    result["raw_counts"][str(category.name)] = budget.current_tokens
            else:
                # Fall back to basic counts if detailed tracking is unavailable
                result["raw_counts"] = {
                    "PROMPT": basic_usage.get("prompt", 0),
                    "COMPLETION": basic_usage.get("completion", 0),
                    "TOTAL": basic_usage.get("total", 0)
                }
                # Create simplified categories since we don't have detailed ones
                result["categories"] = {
                    "PROMPT": basic_usage.get("prompt", 0) / max(basic_usage.get("total", 1), 1),
                    "COMPLETION": basic_usage.get("completion", 0) / max(basic_usage.get("total", 1), 1)
                }
            
            return result
        except Exception as e:
            return {"error": f"Error getting token allocations: {str(e)}"}
            
    async def show_token_details(self):
        """Show detailed token usage information."""
        # If code editor is visible while showing token details, we might have conflicting UI
        if self.code_editor_visible:
            # Consider toggling it off or showing a message
            log("Code editor is visible while showing token details")
            
        try:
            detailed_data = self.get_detailed_token_data()
            await self.show_detailed_token_data(detailed_data)
        except Exception as e:
            await self.conversation_view.add_message(f"Error showing token details: {str(e)}", "system")
            
    async def show_detailed_token_data(self, token_data: Dict[str, Any]):
        """Display detailed token usage data in the conversation view."""
        if "error" in token_data:
            await self.conversation_view.add_message(f"Error getting token details: {token_data['error']}", "system")
            return
            
        # Extract data
        categories = token_data.get("categories", {})
        raw_counts = token_data.get("raw_counts", {})
        total_tokens = token_data.get("total", 0)
        max_tokens = token_data.get("max_tokens", 0)
        
        # Create markdown table for display
        table_md = "# Token Usage by Category\n\n"
        
        if not categories:
            # Show simplified view if no categories are available
            table_md += "Detailed category information is not available.\n\n"
            table_md += f"Total tokens used: {total_tokens}\n"
            table_md += f"Input tokens: {raw_counts.get('PROMPT', 0)}\n"
            table_md += f"Output tokens: {raw_counts.get('COMPLETION', 0)}\n\n"
        else:
            # Show detailed table if categories are available
            table_md += "| Category | Tokens | % of Total | % of Context |\n"
            table_md += "|----------|--------|------------|-------------|\n"
            
            # Add rows for each category
            for category, percentage in sorted(categories.items(), key=lambda x: x[1], reverse=True):
                token_count = raw_counts.get(category, 0)
                table_md += f"| {category} | {token_count} | {percentage * 100:.1f}% | {(token_count / max_tokens * 100) if max_tokens else 0:.1f}% |\n"
            
            # Add total row
            table_md += f"| **TOTAL** | **{total_tokens}** | **100.0%** | **{(total_tokens / max_tokens * 100) if max_tokens else 0:.1f}%** |\n\n"
        
        # Add visual representation
        table_md += "## Context Window Usage\n\n"
        table_md += f"Total: {total_tokens}/{max_tokens} ({(total_tokens / max_tokens * 100) if max_tokens else 0:.1f}%)\n\n"
        
        # Display the markdown
        await self.conversation_view.add_message(table_md, "system")
        
        # If you want to update the detailed token display, use this instead:
        if hasattr(self, "detailed_token_display"):
            self.detailed_token_display.update_token_data(token_data)

    # Add these action handlers
    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()
        
    def action_save(self) -> None:
        """Save the current conversation."""
        # This will be shown in the status bar
        self.status_bar.update_status("Conversation saved")
        
    def action_help(self) -> None:
        """Show help."""
        asyncio.create_task(self.show_help())
        
    def action_token_details(self) -> None:
        """Show token details."""
        # Make sure we don't have any leftover code trying to use code_editor for token data
        if self.code_editor_visible:
            # If code editor is visible while showing token details, we might have conflicting UI
            log("Code editor is visible while showing token details in action_token_details")
            
        # Use asyncio.create_task to ensure the UI doesn't block
        asyncio.create_task(self.show_token_details())
    
    async def show_help(self) -> None:
        """Show help message."""
        help_text = """
# Penguin AI Assistant Help

- Type a message and press Enter to chat
- Use commands starting with / for special functions
- Press F2 or type `/tokens detail` to see detailed token usage
- Press Ctrl+S to save the conversation
- Press Ctrl+C or Q to quit
        """
        await self.conversation_view.add_message(help_text, "system")

    def extract_code_blocks(self, text: str) -> List[tuple]:
        """Extract code blocks from text."""
        code_blocks = []
        
        # Match markdown code blocks
        pattern = r"```(\w+)?\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        
        for lang, code in matches:
            if not lang:
                lang = "text"
            code_blocks.append((lang, code))
            
        return code_blocks
    
    async def toggle_code_editor(self, visible: bool = None):
        """Toggle the code editor visibility."""
        if visible is None:
            visible = not self.code_editor_visible
            
        self.code_editor_visible = visible
        
        if visible:
            self.code_container.styles.display = "block"
            # Adjust the layout
            self.query_one("#conversation-container").styles.width = "2fr"
            self.code_container.styles.width = "1fr"
        else:
            self.code_container.styles.display = "none"
            # Reset the layout
            self.query_one("#conversation-container").styles.width = "1fr"
        
        # Force refresh
        self.refresh()
    
    def action_toggle_code_editor(self) -> None:
        """Action to toggle code editor."""
        asyncio.create_task(self.toggle_code_editor())

async def run_tui(core: PenguinCore):
    """Run the Textual UI."""
    app = PenguinTUI(core)
    await app.run_async()

# Add this for direct testing
if __name__ == "__main__":
    import sys
    from penguin.core import PenguinCore
    
    async def test_main():
        # Initialize core
        core = await PenguinCore.create(enable_cli=False)
        # Run the TUI
        await run_tui(core)
    
    asyncio.run(test_main())