import asyncio
import os
import re # Added for code block detection
import sys
from typing import List, Optional, Dict, Any, Union, TYPE_CHECKING, Callable, Awaitable
from datetime import datetime # Added for instanceof checks
import logging
from dataclasses import dataclass

# Removed Typer for CLIRenderer module
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.progress import Progress, BarColumn, TextColumn
from rich.table import Table
from rich.syntax import Syntax # Added for code highlighting
from rich.markdown import Markdown # Added for markdown rendering
import rich.box # Added for table box style
from rich.live import Live # type: ignore
from rich.layout import Layout

# Add project root to sys.path - This might not be needed if ui.py is part of the package
# and imported correctly by the main CLI. For now, let's assume direct imports work
# or the main CLI handles path adjustments.
# PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
# sys.path.insert(0, PROJECT_ROOT)

# Imports for type hinting if CLIRenderer interacts with them, otherwise not needed here.
# from penguin.chat.interface import PenguinInterface
if TYPE_CHECKING:
    from penguin.core import PenguinCore # For type hinting
    from penguin.chat.interface import PenguinInterface # For type hinting
from penguin.system.state import Message, MessageCategory, Session as ConversationSession # type: ignore

# Configuration for code block detection and styling
# REMOVED: from penguin.config import ( # type: ignore
#     CODE_BLOCK_DELIMITER_START,
#     CODE_BLOCK_DELIMITER_END,
#     CODE_BLOCK_THEME,
# )

# Define these constants directly in ui.py as they are UI-specific
CODE_BLOCK_DELIMITER_START = "```"
CODE_BLOCK_DELIMITER_END = "```"
CODE_BLOCK_THEME = "monokai" # A common Rich theme for code

# --- Constants for Styling and Code Block Detection (adapted from old cli.py) ---

# Regex to find ```lang\ncode\n``` blocks or ```\ncode\n```
# Group 1: Optional language, Group 2: Code content
CODE_BLOCK_PATTERNS = re.compile(r"```(\w+)?\s*\n(.*?)\n```", re.DOTALL)

# Mapping for display names (can be expanded)
LANGUAGE_DISPLAY_NAMES = {
    "python": "Python",
    "javascript": "JavaScript",
    "html": "HTML",
    "css": "CSS",
    "json": "JSON",
    "yaml": "YAML",
    "bash": "Bash",
    "shell": "Shell",
    "sql": "SQL",
    "markdown": "Markdown",
    "text": "Text",
    None: "Code", # Default if no language specified
}

# Theme colors for different message roles/elements
THEME_COLORS = {
    "user": "cyan",
    "assistant": "green",
    "system": "yellow",
    "error": "bold red",
    "tool_code": "blue",
    "tool_result": "magenta",
    "default": "dim",
    "code_border": "dim blue",
    "response_panel": "cyan",
    "stats_panel": "green",
    "conversation_panel": "blue",
    "message_panel_user": "cyan",
    "message_panel_assistant": "green",
    "message_panel_system": "yellow",
    "message_panel_tool": "blue", # For tool calls/results if needed later
    "message_panel_default": "white",
}

logger = logging.getLogger(__name__)

# Define a default theme for messages
MESSAGE_THEME = {
    "message.user.dialog": "cyan",
    "message.user.code": "bold cyan", # Example for user code
    "message.assistant.dialog": "green",
    "message.assistant.code": "bold green", # Example for assistant code
    "message.system.system": "dim",
    "message.system.system_output": "blue",
    "message.system.context": "italic dim", # For context file messages
    "message.system.system_prompt": "italic dim", # For the main system prompt
    "message.system.error": "bold red",
    "message.system.unknown": "dim yellow", # Fallback
    "message.default.default": "white", # Fallback
}

# Define theme mapping constants
ROLE_THEME_MAP = {
    "user": "user",
    "assistant": "assistant",
    "system": "system",
    "unknown": "default"
}

class CLIRenderer:
    """Handles all Rich-based rendering for the CLI"""
    
    def __init__(self, console: Console, core: "PenguinCore"):
        """
        Initialize the renderer with a console object and a core instance.
        Subscribes to Core events for UI updates.
        
        Args:
            console: Rich console for rendering
            core: PenguinCore instance to subscribe to
        """
        logger.debug("Initializing CLIRenderer")
        self.console = console
        self.core = core
        
        # Streaming state - simplified
        self.streaming_message_data = {}
        self.is_streaming = False
        
        # UI display controls
        self.show_context_messages: bool = False
        self.is_runmode_live: bool = False
        self.current_model: str = "Unknown model"
        self.max_message_lines: int = 25

        # Live display reference (set by CLI)
        self.live_display: Optional[Live] = None
        
        # Token usage tracking
        self.token_stats: Dict[str, Any] = {}
        self.api_cost_placeholder: str = "$0.0000 (est.)"
        self.token_usage_data: Optional[Dict[str, Any]] = None
        
        # Initialize progress bar for token usage
        self.progress = Progress(
            TextColumn("[bold blue]Context Usage:[/] {task.fields[completed_text]} ({task.percentage:>3.1f}%) "),
            BarColumn(bar_width=None),
            TextColumn("{task.fields[total_text]}"),
            expand=True,
            transient=False
        )
        self.context_task_id = self.progress.add_task(
            "usage", total=1.0, completed=0.0,
            completed_text="0k", total_text="0k", visible=False
        )

        # Initialize category table
        self.category_token_table = Table(show_header=False, box=None, padding=(0,0), expand=True)
        self.category_token_table.add_column("Category", style="dim", ratio=1, overflow="fold", no_wrap=True)
        self.category_token_table.add_column("Tokens", style="dim", justify="right", ratio=1, no_wrap=True)

        # Create main layout
        self.layout = self._create_layout()
        
        # Messages cache from conversation manager
        self.conversation_messages: List[Dict[str, Any]] = []
        
        # Register with Core for events
        if self.core:
            # Register the synchronous wrapper instead of the async method
            self.core.register_ui(self.handle_event_sync)
            logger.debug("Registered with Core for UI events")
        
        # Call update once to build initial state
        self.update_token_stats(None)
        logger.debug("CLIRenderer initialization complete")

    async def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Handle events from Core and update UI accordingly.
        
        Args:
            event_type: Type of event (e.g., "stream_chunk", "token_update")
            data: Event data
        """
        logger.debug(f"Received event: {event_type}")
        
        try:
            if event_type == "stream_chunk":
                await self._handle_stream_event(data)
            elif event_type == "token_update":
                self._handle_token_event(data)  # This is synchronous
            elif event_type == "message":
                await self._handle_message_event(data)
            elif event_type == "status":
                await self._handle_status_event(data)
            elif event_type == "error":
                await self._handle_error_event(data)
            else:
                logger.warning(f"Unknown event type: {event_type}")
            
            # Update the live display if available
            self._update_live_display()
                
        except Exception as e:
            logger.error(f"Error handling event {event_type}: {str(e)}", exc_info=True)

    # Add a synchronous wrapper for handle_event to support direct calls
    def handle_event_sync(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Synchronous wrapper for handle_event that launches the async version.
        Used when Core calls this method directly (non-async context).
        """
        # Create a coroutine and run it to completion
        try:
            coro = self.handle_event(event_type, data)
            # Run the coroutine in a way that depends on the current event loop state
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already in an event loop, so create a task
                    asyncio.create_task(coro)
                else:
                    # No running event loop, run the coroutine directly
                    asyncio.run(coro)
            except RuntimeError:
                # No event loop exists yet, create a new one
                asyncio.run(coro)
        except Exception as e:
            logger.error(f"Error in handle_event_sync: {str(e)}", exc_info=True)
            # Still try to update the UI if possible
            if event_type == "token_update":
                # Try to handle token updates directly as they're important for UI
                self._handle_token_event(data)
                self._update_live_display()

    async def _handle_stream_event(self, data: Dict[str, Any]) -> None:
        """Handle streaming chunks from Core."""
        is_final = data.get("is_final", False)
        
        if is_final:
            # Stream is over. The temporary panel will be removed on the next render.
            self.is_streaming = False
            self.streaming_message_data = {}  # Clear the data
            # Force update to show final state
            self._update_live_display()
        else:
            # Stream is active. Update the data for the temporary panel.
            self.is_streaming = True
            self.streaming_message_data = {
                "role": data.get("role", "assistant"),
                "content": data.get("content_so_far", ""),  # Use the full content from Core
                "category": MessageCategory.DIALOG,
                "timestamp": datetime.now().isoformat(),
                "metadata": data.get("metadata", {"is_streaming": True})
            }
            # Force update to show streaming content immediately
            self._update_live_display()
        
        # No need to refresh cache here. The "message" event after finalization will handle it.

    def _handle_token_event(self, data: Dict[str, Any]) -> None:
        """Handle token usage updates."""
        try:
            # Log token data for debugging
            logger.debug(f"Received token event with data: {data}")
            
            # Directly update token stats
            self.token_usage_data = data
            self.update_token_stats(data)
            
            # Update display
            self._update_live_display()
        except Exception as e:
            logger.error(f"Error handling token event: {e}", exc_info=True)

    async def _handle_message_event(self, data: Dict[str, Any]) -> None:
        """Handle new message events."""
        # Messages are added to conversation manager by Core
        # Just refresh our local cache
        self._refresh_message_cache()

    async def _handle_status_event(self, data: Dict[str, Any]) -> None:
        """Handle status update events."""
        status_type = data.get("status_type", "")
        
        # Special handling for RunMode status updates
        if "runmode" in status_type.lower() or "task" in status_type.lower():
            self.is_runmode_live = True
        
        # Refresh message cache as status might include new messages
        self._refresh_message_cache()

    async def _handle_error_event(self, data: Dict[str, Any]) -> None:
        """Handle error events."""
        error_msg = data.get("message", "Unknown error")
        details = data.get("details", "")
        
        # Temporarily show error directly in console for critical errors
        self.console.print(self.render_error(error_msg, details=details))
        
        # Refresh message cache as error might have been added as message
        self._refresh_message_cache()

    def _refresh_message_cache(self) -> None:
        """Refresh the local cache of conversation messages from Core."""
        try:
            if self.core and hasattr(self.core, 'conversation_manager'):
                cm = self.core.conversation_manager
                if hasattr(cm, 'conversation') and cm.conversation:
                    if hasattr(cm.conversation, 'session') and cm.conversation.session:
                        # Convert ConversationManager Message objects to dicts
                        old_count = len(self.conversation_messages)
                        self.conversation_messages = []
                        for msg in cm.conversation.session.messages:
                            self.conversation_messages.append({
                                "role": msg.role,
                                "content": msg.content,
                                "category": msg.category,
                                "timestamp": msg.timestamp,
                                "metadata": msg.metadata if hasattr(msg, 'metadata') else {}
                            })
                        new_count = len(self.conversation_messages)
                        logger.debug(f"Refreshed message cache: {old_count} -> {new_count} messages")
        except Exception as e:
            logger.error(f"Error refreshing message cache: {e}", exc_info=True)

    def _update_live_display(self) -> None:
        """Update the live display if available."""
        if self.live_display:
            try:
                renderable = self.get_display_renderable()
                self.live_display.update(renderable)
            except Exception as e:
                logger.error(f"Error updating live display: {e}", exc_info=True)
                # Try a simpler update if the complex one fails
                try:
                    # Create a simple error message panel as a fallback
                    error_panel = Panel(f"UI update error: {str(e)}", 
                                       title="UI Error", 
                                       border_style="red")
                    self.live_display.update(error_panel)
                except Exception as inner_e:
                    # If even the simple update fails, just log it
                    logger.critical(f"Fatal UI error: {inner_e}", exc_info=True)

    def set_live_display(self, live: Live) -> None:
        """Set the Live display reference for updates."""
        self.live_display = live

    def _create_layout(self) -> Layout:
        """Create the initial layout structure."""
        layout = Layout(name="root")
        
        # Split into main content and footer with better proportions
        layout.split(
            Layout(name="main", ratio=1, minimum_size=10),
            Layout(name="footer", size=6)  # Slightly smaller footer
        )
        
        # Set up for run mode vs regular chat
        layout["main"].split(
            Layout(name="status", size=3, visible=False),  # Hidden by default
            Layout(name="content", ratio=1, minimum_size=8)  # Ensure minimum space for content
        )
        
        return layout

    def _render_text_segment(self, text_content: str) -> List[Any]:
        # This new helper contains the original logic for processing a string
        # (finding code blocks, rendering markdown for parts)
        renderables = []
        last_end = 0

        for match in CODE_BLOCK_PATTERNS.finditer(text_content):
            start, end = match.span()
            lang = match.group(1)
            code = match.group(2)

            if start > last_end:
                preceding_text = text_content[last_end:start].strip()
                if preceding_text:
                    renderables.append(Markdown(preceding_text))
            
            display_lang = LANGUAGE_DISPLAY_NAMES.get(lang, lang.capitalize() if lang else "Code")
            syntax = Syntax(code, lexer=lang if lang else "text", theme="default", line_numbers=True, word_wrap=True)
            code_panel = Panel(syntax, title=display_lang, border_style=THEME_COLORS.get("code_border", "dim blue"), padding=(0, 1), expand=False)
            renderables.append(code_panel)
            last_end = end

        if last_end < len(text_content):
            remaining_text = text_content[last_end:].strip()
            if remaining_text:
                renderables.append(Markdown(remaining_text))

        if not renderables and text_content: # Whole thing is markdown (no code blocks)
             renderables.append(Markdown(text_content.strip()))
        # Removed the empty text segment case as _render_message_content handles overall empty/waiting states

        return renderables

    def _render_message_content(self, content: Any, role_for_theme: str = "default") -> Group:
        """Renders message content, handling Markdown, code blocks, and multimodal list content."""
        overall_renderables = []

        if isinstance(content, list): # Multimodal content
            for item in content:
                item_type = item.get("type")
                if item_type == "text":
                    text_segment = item.get("text", "")
                    if text_segment: 
                        segment_renderables = self._render_text_segment(text_segment)
                        overall_renderables.extend(segment_renderables)
                elif item_type == "image_url":
                    image_path = item.get("image_path", "unknown image")
                    overall_renderables.append(Text(f"[Image: {image_path}]", style="dim italic"))
                # else: handle other future multimodal types like audio, video etc.
            if not overall_renderables: 
                overall_renderables.append(Text("(Empty or unrenderable multimodal content)", style="dim italic"))
        elif isinstance(content, str): # Existing string content
            string_renderables = self._render_text_segment(content)
            overall_renderables.extend(string_renderables)
            if not overall_renderables and not content: # String content was empty
                 overall_renderables.append(Text("(Waiting for response...)", style="dim italic"))
            elif not overall_renderables and content: # String content not empty but _render_text_segment returned nothing (e.g. just whitespace)
                 overall_renderables.append(Markdown(content.strip())) # Try rendering the stripped original as Markdown

        else: # Fallback for unexpected content type or if content is None/empty after processing
            if not content and not overall_renderables: # Specifically if initial content was None or empty string
                overall_renderables.append(Text("(Waiting for response...)", style="dim italic"))
            elif not overall_renderables: # Content was of an unsupported type, or other empty case
                overall_renderables.append(Text(f"(Unsupported or empty content: type {type(content)})", style="dim italic error"))
            
        return Group(*overall_renderables)

    def _build_conversation_area_content(self) -> Group:
        """
        Build the conversation area content from cached messages.
        Also includes any active streaming message.
        """
        logger.debug("Building conversation area content")
        
        rendered_panels = []
        
        # Filter system/context messages if needed
        # IMPORTANT: System output (tool results) should always be shown!
        filtered_messages = self.conversation_messages
        if not self.show_context_messages:
            filtered_messages = [
                msg for msg in filtered_messages
                if (isinstance(msg.get("category"), MessageCategory) and 
                    msg.get("category") not in [MessageCategory.SYSTEM, MessageCategory.CONTEXT]) or
                   (isinstance(msg.get("category"), str) and 
                    msg.get("category") not in ["SYSTEM", "CONTEXT"]) or
                   # Always show system output messages (tool results)
                   (isinstance(msg.get("category"), MessageCategory) and 
                    msg.get("category") == MessageCategory.SYSTEM_OUTPUT) or
                   (isinstance(msg.get("category"), str) and 
                    msg.get("category") == "SYSTEM_OUTPUT")
            ]
        
        # Render each message as a panel
        for msg in filtered_messages:
            rendered_panels.append(self.render_message_panel(msg))
        
        # Add streaming message if active
        if self.is_streaming and self.streaming_message_data:
            # Add the Penguin cursor to streaming content
            streaming_content = self.streaming_message_data.get("content", "")
            if streaming_content.strip():
                streaming_content += " 🐧"
            else:
                streaming_content = "Thinking... 🐧"
                
            # Create a copy of streaming message data with updated content
            streaming_display_data = self.streaming_message_data.copy()
            streaming_display_data["content"] = streaming_content
            streaming_display_data["metadata"] = {"is_streaming": True}
            
            rendered_panels.append(self.render_message_panel(streaming_display_data))
        
        # Display a compact welcome message if no panels yet
        if not rendered_panels:
            logger.debug("No messages to display, showing welcome message")
            welcome_text = Text("🐧 Welcome to Penguin! Type a message to start chatting.", style="dim")
            rendered_panels = [welcome_text]  # Just text, no panel
        
        logger.debug(f"Rendered {len(rendered_panels)} message panels")
        return Group(*rendered_panels)

    def _safe_format_timestamp(self, timestamp) -> str:
        """Safely format a timestamp of any type (datetime, string, or None) to a readable string."""
        if timestamp is None:
            return ""
        
        # If it's already a datetime object
        if hasattr(timestamp, 'strftime'):
            return timestamp.strftime("%H:%M:%S")
            
        # If it's a string, try to parse it or return as is
        timestamp_str = str(timestamp)
        
        # Check if already in time format
        if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', timestamp_str):
            return timestamp_str
            
        # Try to parse as ISO format
        try:
            dt_obj = datetime.fromisoformat(timestamp_str)
            return dt_obj.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            # If can't parse, return as is
            return timestamp_str

    def _build_token_stats_panel(self) -> Panel:
        """Builds the panel displaying token usage and model stats."""
        # Rebuild category table based on self.token_usage_data
        # Important: Create a *new* Table instance each time to avoid Rich errors with Live updates
        current_category_table = Table(show_header=False, box=None, padding=(0,0), expand=True)
        # Add columns again as it's a new table
        current_category_table.add_column("Category", style="dim", ratio=1, overflow="fold", no_wrap=True)
        current_category_table.add_column("Tokens", style="dim", justify="right", ratio=1, no_wrap=True)

        if self.token_usage_data and not self.token_usage_data.get("error"):
            self.progress.update(self.context_task_id, visible=True)
            current = float(self.token_usage_data.get("current_total_tokens", 0))
            # Ensure maximum is at least 1 and not None/0 to avoid division by zero
            maximum = float(self.token_usage_data.get("max_tokens") or 1)
            maximum = max(maximum, 1.0) # Ensure it's at least 1
            # Ensure current doesn't exceed maximum for progress bar display
            current = min(current, maximum)
            percentage = (current / maximum) if maximum > 0 else 0.0

            self.progress.update(self.context_task_id,
                                 total=maximum, completed=current,
                                 completed_text=f"{current/1000:.1f}k",
                                 total_text=f"{maximum/1000:.1f}k")

            categories_data = self.token_usage_data.get("categories", {})
            # Sort categories alphabetically for consistent display
            sorted_categories = sorted(categories_data.items(), key=lambda item: item[0])
            for cat_name_enum, val in sorted_categories:
                # Use .name attribute if it's an Enum, otherwise use the key directly
                cat_name = cat_name_enum.name if hasattr(cat_name_enum, 'name') else str(cat_name_enum)
                current_category_table.add_row(cat_name.replace("_", " ").title(), f"{val:,}")
            if not categories_data:
                current_category_table.add_row("No category data", "")
        elif self.token_usage_data and self.token_usage_data.get("error"):
            self.progress.update(self.context_task_id, visible=False)
            current_category_table.add_row(f"Error: {self.token_usage_data.get('error', 'Token data unavailable')}", "", style="red")
        else: # Initializing or no data yet
            self.progress.update(self.context_task_id, visible=False)
            current_category_table.add_row("Initializing...", "")

        # Group the progress bar and the category table
        token_stats_elements_group = Group(self.progress, current_category_table)

        quick_stats_text = f"Model: {self.current_model} | Cost: {self.api_cost_placeholder}"
        return Panel(
            Group(token_stats_elements_group, Text(quick_stats_text, style="dim")),
            title="📊 Token & Stats",
            border_style=THEME_COLORS.get("stats_panel", "green"),
            padding=(0, 1) # Minimal vertical padding
        )

    # --- Public methods for the main CLI to call/update state ---
    def set_current_model(self, model_name: str) -> None:
        """Sets the display name for the current model."""
        self.current_model = model_name
        # No need to rebuild panels here; get_display_renderable will do it.

    def update_token_stats(self, usage_data: Optional[Dict[str, Any]]) -> None:
        """Update token usage statistics for display"""
        if usage_data:
            self.token_stats = usage_data
            self.token_usage_data = usage_data

    def get_layout_renderable(self) -> Layout:
        """
        Create a simple layout with just conversation content.
        Input is handled separately via input() calls.
        
        Returns:
            A Rich Layout object with conversation content only
        """
        logger.debug(f"Building layout renderable (RunMode: {self.is_runmode_live})")
        
        # Simple layout - just conversation content
        layout = Layout(name="root")
        
        if self.is_runmode_live:
            # RunMode: status + conversation
            layout.split(
                Layout(name="status", size=3),
                Layout(name="conversation", ratio=1)
            )
            
            # Get the RunMode status from Core
            runmode_status = "RunMode inactive"
            if self.core and hasattr(self.core, 'current_runmode_status_summary'):
                runmode_status = self.core.current_runmode_status_summary
            
            status_panel = Panel(
                Text(runmode_status, justify="left"),
                title="🤖 RunMode Status",
                border_style="yellow",
                expand=True
            )
            
            layout["status"].update(status_panel)
            layout["conversation"].update(self._build_conversation_area_content())
        else:
            # Regular chat: just conversation content
            layout.update(self._build_conversation_area_content())
        
        logger.debug("Layout renderable built successfully")
        return layout

    def get_display_renderable(self) -> Any:
        """Returns the main renderable for the Live display."""
        return self.get_layout_renderable()

    def render_message_panel(self, message_data: Dict[str, Any]) -> Panel:
        """
        Renders a single message into a Rich Panel.
        Handles different roles and formats content with Markdown/code blocks.
        """
        logger.debug(f"Rendering message panel for role: {message_data.get('role', 'unknown')}")
        
        # Extract message data
        role = message_data.get("role", "unknown").lower()
        content = message_data.get("content", "")
        category_name = message_data.get("category", MessageCategory.UNKNOWN.name) # Get category name
        if isinstance(category_name, MessageCategory):
            category_name = category_name.name
        timestamp_str = message_data.get("timestamp", "")
        metadata = message_data.get("metadata", {})

        # Determine panel title and style based on role and category
        panel_title_text = role.capitalize()
        if role == "system" and category_name:
            panel_title_text = f"System ({category_name.replace('_', ' ').title()})"
        elif role == "assistant":
            panel_title_text = "Penguin"
            if metadata.get("tool_name"):
                panel_title_text = f"Penguin (Tool: {metadata.get('tool_name')})"
            elif metadata.get("is_streaming"):
                panel_title_text = "Penguin (streaming)"

        panel_border_style = THEME_COLORS.get(f"message_panel_{role}", THEME_COLORS.get("message_panel_default", "white"))
        if role == "system" and category_name == MessageCategory.ERROR.name:
            panel_border_style = THEME_COLORS.get("error", "bold red")
        
        # Special handling for streaming assistant message
        is_streaming = metadata.get("is_streaming", False)
        text_to_render = content
        if is_streaming and role == "assistant":
            if not text_to_render.strip():
                text_to_render = "Waiting for response... 🐧"
            elif not text_to_render.endswith("🐧"):
                text_to_render += " 🐧"

        rendered_content_group = self._render_message_content(text_to_render, role_for_theme=role)

        # Add timestamp to title if available
        if timestamp_str:
            formatted_time = self._safe_format_timestamp(timestamp_str)
            if formatted_time:
                panel_title_text += f" @ {formatted_time}"

        # Add logging for panels
        logger.debug(f"Creating panel with title: {panel_title_text}, role: {role}, category: {category_name}")

        return Panel(
            rendered_content_group,
            title=panel_title_text,
            border_style=panel_border_style,
            padding=(0,1), # Minimal vertical padding
            expand=True # Allow panel to expand horizontally
        )

    def render_message_list(self, messages: List[Dict[str, Any]], title: str = "Conversation History") -> Panel:
        """Renders a list of messages into a single panel (less used now with live updates)."""
        # This method might be less relevant if get_display_renderable directly builds the conversation.
        # However, it can be kept for specific use cases like a static dump of history.
        if not messages:
            return Panel(Text("No messages in this conversation.", style="dim"), title=title)

        message_renderables = [self.render_message_panel(msg) for msg in messages]
        return Panel(Group(*message_renderables), title=title, border_style=THEME_COLORS.get("conversation_panel", "blue"))

    def render_generic_list_table(self, items: List[Dict[str, Any]], title: str, columns_config: List[Dict[str, Any]]) -> Table:
        """
        Renders a generic list of dictionaries as a Rich Table.

        Args:
            items: A list of dictionaries, where each dictionary represents a row.
            title: The title for the table.
            columns_config: A list of dictionaries, each configuring a column:
                {'header': str, 'key': str, 'style': Optional[str], 
                 'justify': Optional[str ('left', 'center', 'right')],
                 'ratio': Optional[int (for layout)],
                 'overflow': Optional[str ('fold', 'crop', 'ellipsis')],
                 'no_wrap': Optional[bool]}
        """
        if not items:
            return Table(title=f"{title} (No items)", box=rich.box.ROUNDED, show_header=True, padding=(0,1))

        table = Table(title=title, box=rich.box.ROUNDED, show_header=True, padding=(0,1), expand=True)

        for col_conf in columns_config:
            table.add_column(
                col_conf['header'],
                style=col_conf.get('style', ""),
                justify=col_conf.get('justify', 'left'), # type: ignore
                ratio=col_conf.get('ratio'),
                overflow=col_conf.get('overflow', 'fold'), # type: ignore
                no_wrap=col_conf.get('no_wrap', False)
            )
        
        for item in items:
            row_values = []
            for col_conf in columns_config:
                value = item.get(col_conf['key'])
                if isinstance(value, bool): # Nicer display for booleans
                    row_values.append(Text("✔", style="green") if value else Text("✘", style="red"))
                elif value is None:
                    row_values.append(Text("-", style="dim"))
                else:
                    row_values.append(str(value))
            table.add_row(*row_values)
            
        return table
        
    def render_error(self, error_message: str, details: Optional[str] = None) -> Panel:
        """Renders an error message in a styled panel."""
        error_text = Text(error_message, style=THEME_COLORS.get("error", "bold red"))
        if details:
            error_text.append("\n\nDetails:\n", style="bold")
            error_text.append(details, style="") # Default style for details
            
        return Panel(
            error_text, 
            title="❌ Error", 
            border_style=THEME_COLORS.get("error", "bold red"),
            padding=(1,1) # Add some padding for errors
        )

    def reset_response_area(self) -> None:
        """Reset streaming state and other UI state."""
        self.streaming_message_data = {}
        self.is_streaming = False
        logger.debug("Response area reset completed")

    def initialize(self) -> None:
        """
        Initialize the renderer with current conversation state.
        Call this after registering with Core for events.
        """
        # Refresh message cache to get current conversation
        self._refresh_message_cache()
        
        # Set up initial UI state
        if not self.conversation_messages:
            # If no messages, add a welcome message directly
            logger.debug("Adding welcome system message to conversation")
            welcome_data = {
                "role": "system",
                "content": "Welcome to Penguin! Type your message below to chat with the AI assistant.",
                "category": MessageCategory.SYSTEM,
                "timestamp": datetime.now().isoformat()
            }
            self.conversation_messages.append(welcome_data)
        
        # Update token display
        if self.core:
            token_usage = self.core.get_token_usage()
            self.update_token_stats(token_usage)
        
        logger.debug("CLIRenderer initialization complete")


# The Typer app and test execution logic is removed from this file.
# This file now only contains the CLIRenderer class with enhanced rendering capabilities.
# To test this, a separate script (like test_ui.py or the main cli.py)
# would import CLIRenderer, instantiate it, and use its methods.