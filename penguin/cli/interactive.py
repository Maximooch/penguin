"""Interactive Rich CLI application and terminal lifecycle ownership."""

from __future__ import annotations

import asyncio
import datetime
import logging
import os
import re
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import rich
from prompt_toolkit.formatted_text import HTML
from rich.console import Console as RichConsole
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from penguin.cli.display_manager import DisplayManager
from penguin.cli.event_manager import EventManager
from penguin.cli.events import EventBus, EventType
from penguin.cli.interface import PenguinInterface
from penguin.cli.presentation import CLI_PANEL_PADDING, print_ascii_banner
from penguin.cli.renderer import RenderStyle, UnifiedRenderer
from penguin.cli.session_manager import SessionManager
from penguin.cli.streaming_display import StreamingDisplay
from penguin.cli.streaming_manager import StreamingManager
from penguin.system.conversation_menu import ConversationMenu
from penguin.utils.logs import setup_logger

__all__ = ["PenguinCLI"]

logger = logging.getLogger(__name__)


class PenguinCLI:
    USER_COLOR = "grey"
    PENGUIN_COLOR = "blue"
    TOOL_COLOR = "yellow"
    RESULT_COLOR = "green"
    CODE_COLOR = "bright_blue"
    PENGUIN_EMOJI = "🐧"
    FILE_READ_ACTIONS = {"read_file", "read", "cat", "view", "enhanced_read"}
    LARGE_STREAM_RENDER_THRESHOLD = 6000  # characters

    # Language detection and mapping

    # Language detection patterns for auto-detection
    # LANGUAGE_DETECTION_PATTERNS moved to UnifiedRenderer.detect_language()

    # Language display names (for panel titles)
    # LANGUAGE_DISPLAY_NAMES moved to UnifiedRenderer

    def __init__(self, core):
        self.core = core
        self.show_tool_results: bool = bool(getattr(core, "show_tool_results", True))
        self.interface = PenguinInterface(core)
        self.in_247_mode = False
        self.message_count = 0
        self.console = RichConsole()  # Use RichConsole instead of Console
        self.panel_padding = CLI_PANEL_PADDING

        # Initialize unified renderer with borderless style (padding retained, no borders)
        self.renderer = UnifiedRenderer(
            console=self.console,
            style=RenderStyle.BORDERLESS,
            show_timestamps=False,
            show_metadata=False,
            show_tool_results=self.show_tool_results,
            panel_padding=self.panel_padding,
        )

        # Initialize display manager
        self.display_manager = DisplayManager(
            self.console,
            self.renderer,
            self.panel_padding,
        )

        # Initialize new StreamingDisplay for smooth Rich.Live rendering
        self.streaming_display = StreamingDisplay(
            console=self.console,
            panel_padding=self.panel_padding,
            borderless=True,
        )

        # Initialize streaming manager (requires streaming_display)
        self.streaming_manager = StreamingManager(self.streaming_display)

        self.conversation_menu = ConversationMenu(self.console)
        self.core.register_progress_callback(self.on_progress_update)

        # Subscribe to all event types via unified event bus
        self.event_manager = EventManager(self)
        self._event_bus = EventBus.get_sync()
        self._event_bus.subscribe(
            EventType.STREAM_CHUNK.value, self.event_manager.handle_stream_chunk_event
        )
        self._event_bus.subscribe(
            EventType.MESSAGE.value, self.event_manager.handle_message_event
        )
        self._event_bus.subscribe(
            EventType.STATUS.value, self.event_manager.handle_status_event
        )
        self._event_bus.subscribe(
            EventType.TOOL.value, self.event_manager.handle_tool_event
        )
        self._event_bus.subscribe(
            EventType.ERROR.value, self.event_manager.handle_error_event
        )

        # Single Live display for better rendering
        self.live_display = None
        self.streaming_live = None

        # Message tracking to prevent duplication
        self.processed_messages = set()
        self.last_completed_message = ""
        self.last_completed_message_normalized = ""

        # Conversation turn tracking
        self.current_conversation_turn = 0
        self.message_turn_map = {}

        # Buffer for pending system messages (tool results) during streaming
        self.pending_system_messages: List[
            Tuple[str, str]
        ] = []  # List of (content, role)

        # Run mode state
        self.run_mode_active = False
        self.run_mode_status = "Idle"

        self._streaming_started = False
        self._progress_task_id = None

        # Create prompt_toolkit session
        # Initialize session manager
        self.session_manager = SessionManager(
            console=self.console,
            user_color=self.USER_COLOR,
            penguin_color=self.PENGUIN_COLOR,
            cancel_callback=self._cancel_streaming,  # Pass cancel method
        )
        (self.console,)
        (self.USER_COLOR,)
        self.PENGUIN_COLOR

        self.session = self.session_manager.create_prompt_session()

        # NOTE: We intentionally do NOT register a custom SIGINT handler.
        # prompt_toolkit handles Ctrl+C natively by raising KeyboardInterrupt,
        # which our chat_loop's try/except blocks catch appropriately.

        self._streaming_lock = asyncio.Lock()
        self._streaming_session_id = None  # legacy session id (will be removed)
        self._active_stream_id = None  # NEW – authoritative stream identifier from Core
        self._last_processed_turn = None

    def _cancel_streaming(self):
        """Cancel current streaming response from LLM."""
        self.console.print("\n[yellow]⚠️ Response stopped by user[/yellow]")
        self.streaming_manager.safely_stop_progress()
        if hasattr(self, "_streaming_started") and self._streaming_started:
            try:
                self.streaming_manager.finalize_streaming()
            except Exception:
                pass

    def _handle_interrupt(self, sig, frame):
        """Handle SIGINT (Ctrl+C) - clean up progress but let the event loop handle the interrupt."""
        self.streaming_manager.safely_stop_progress()
        # Clean up any streaming in progress
        if hasattr(self, "_streaming_started") and self._streaming_started:
            try:
                self.streaming_manager.finalize_streaming()
            except Exception:
                pass
        # Let the KeyboardInterrupt propagate naturally to be caught by chat_loop's handlers
        raise KeyboardInterrupt

    def _filter_verbose_code_blocks(self, message: str) -> str:
        """Filter verbose code blocks to prevent screen clutter.

        Summarizes <execute> blocks and very long code blocks.
        Returns the filtered message.
        """
        import re

        # Pattern to match <execute> blocks
        execute_pattern = r"<execute>(.*?)</execute>"

        def summarize_execute_block(match):
            code = match.group(1).strip()
            lines = code.split("\n")
            line_count = len(lines)

            # If short, keep as-is
            if line_count <= 5:
                return match.group(0)

            # Create summary
            first_line = lines[0].strip() if lines else ""

            # Extract what the code is doing (heuristic)
            if "import" in first_line.lower():
                action = "importing modules"
            elif "def " in code or "class " in code:
                action = "defining function/class"
            elif "print" in code:
                action = "printing output"
            elif "Path" in code and "write" in code:
                action = "writing to file"
            elif "Path" in code and "read" in code:
                action = "reading file"
            else:
                # Use first meaningful line
                action = first_line[:50] + "..." if len(first_line) > 50 else first_line

            summary = f"[Code: {line_count} lines - {action}]"
            return summary

        # Replace execute blocks with summaries
        filtered = re.sub(
            execute_pattern, summarize_execute_block, message, flags=re.DOTALL
        )

        return filtered

    def _extract_and_display_reasoning(self, message: str) -> str:
        """Extract <details> reasoning blocks and display them in a separate gray panel.

        Returns the message with reasoning blocks removed.
        """
        import re

        # Guard against re-displaying already processed reasoning
        if (
            hasattr(self, "_last_reasoning_extracted")
            and message == self._last_reasoning_extracted
        ):
            return message

        # Pattern to match <details> blocks with reasoning
        details_pattern = r"<details>\s*<summary>🧠[^<]*</summary>\s*(.*?)</details>\s*"

        matches = re.findall(details_pattern, message, re.DOTALL | re.IGNORECASE)

        if matches:
            # Extract reasoning content (everything between summary and </details>)
            reasoning_content = matches[0].strip()

            # Remove markdown formatting from reasoning (**, __, etc.)
            # Handle all markdown bold/italic patterns
            reasoning_text = re.sub(
                r"\*\*\*?(.*?)\*\*\*?", r"\1", reasoning_content
            )  # Remove **bold** and ***bold italic***
            reasoning_text = re.sub(
                r"___(.*?)___", r"\1", reasoning_text
            )  # Remove ___bold italic___
            reasoning_text = re.sub(
                r"__(.*?)__", r"\1", reasoning_text
            )  # Remove __bold__
            reasoning_text = re.sub(
                r"_(.*?)_", r"\1", reasoning_text
            )  # Remove _italic_
            reasoning_text = re.sub(
                r"\n+", " ", reasoning_text
            )  # Collapse newlines to spaces
            reasoning_text = re.sub(
                r"\s+", " ", reasoning_text
            )  # Collapse multiple spaces
            reasoning_text = reasoning_text.strip()

            # Display reasoning in a compact gray panel
            if reasoning_text:
                from rich.text import Text

                # Use dim styling for the entire panel content
                reasoning_display = Text(f"🧠 {reasoning_text}", style="dim italic")
                reasoning_panel = Panel(
                    reasoning_display,
                    title="[dim]Internal Reasoning[/dim]",
                    title_align="left",
                    border_style="dim",
                    width=self.console.width - 8,
                    box=rich.box.SIMPLE,  # Simpler box style
                    padding=(0, 1),  # Minimal padding
                )
                self.console.print(reasoning_panel)

            # Remove the details block from the message
            cleaned_message = re.sub(
                details_pattern, "", message, flags=re.DOTALL | re.IGNORECASE
            )

            # Mark this message as processed to prevent re-display
            self._last_reasoning_extracted = message

            return cleaned_message.strip()

        return message

    def _normalize_message_content(self, content: str) -> str:
        """Normalize assistant content for duplicate detection."""
        if not content:
            return ""
        # Remove collapsible reasoning blocks before comparison
        cleaned = re.sub(
            r"<details>.*?</details>", "", content, flags=re.DOTALL | re.IGNORECASE
        )
        # Normalize whitespace to avoid false mismatches
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def display_message(self, message: str, role: str = "assistant") -> None:
        """Display a message using the unified renderer.

        Args:
            message: Message content to display.
            role: Message role (user, assistant, system, error).
        """
        # Skip if this is a duplicate of a recently processed message
        message_key = f"{role}:{message[:50]}"

        if role in ["assistant", "user"]:
            if (
                message_key in self.processed_messages
                and role == "assistant"
                and message == self.last_completed_message
            ):
                return
        else:
            # Always add to processed messages to prevent future duplicates
            self.processed_messages.add(message_key)
            # Associate with current conversation turn
            self.message_turn_map[message_key] = self.current_conversation_turn
            # Update last completed message for assistant messages
            if role == "assistant":
                self.last_completed_message = message

        # Filter verbose code blocks for assistant messages
        filtered_message = message
        if role == "assistant":
            filtered_message = self._filter_verbose_code_blocks(message)

        # Use unified renderer for all message rendering
        # Render with current style (no special case for welcome message)
        self.display_manager.display_message(filtered_message, role)

    def _create_tool_summary(self, tool_name: str, content: str, metadata: Dict) -> str:
        """
        Create a compact summary for tool results instead of showing full output.

        Args:
            tool_name: Name of the tool
            content: Full tool output
            metadata: Tool metadata

        Returns:
            Compact summary string
        """
        # Extract key info from content
        if "list_files" in tool_name:
            # Count files and directories
            dirs = content.count("DIRECTORIES:")
            files_count = content.count(" bytes)")
            return f"✓ Listed {files_count} files" + (
                f", {dirs} directories" if dirs > 0 else ""
            )

        elif "read" in tool_name or "enhanced_read" in tool_name:
            # Show file path and size
            import re

            match = re.search(r"(\d+) characters", content)
            if match:
                size = match.group(1)
                file_path = metadata.get("file_path", "file")
                return f"✓ Read {file_path} ({size} chars)"
            return "✓ Read file"

        elif "write" in tool_name or "enhanced_write" in tool_name:
            # Show file written
            file_path = metadata.get("file_path", "file")
            lines = content.count("\n")
            return f"✓ Wrote {file_path}" + (f" ({lines} lines)" if lines > 0 else "")

        # For other tools, show nothing (will use default display)
        return ""

    def on_progress_update(
        self, iteration: int, max_iterations: int, message: Optional[str] = None
    ):
        """Handle progress updates without interfering with execution"""
        if not self.streaming_manager.progress and iteration > 0:
            # Only show progress if not already processing
            self.streaming_manager.safely_stop_progress()
            progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                console=self.console,
            )
            progress.start()
            self.streaming_manager.progress = progress
            self._progress_task_id = progress.add_task(
                f"Thinking... (Step {iteration}/{max_iterations})", total=max_iterations
            )

        if self.streaming_manager.progress and self._progress_task_id is not None:
            # Update without completing to prevent early termination
            self.streaming_manager.progress.update(
                self._progress_task_id,
                description=f"{message or 'Processing'} (Step {iteration}/{max_iterations})",
                completed=min(
                    iteration, max_iterations - 1
                ),  # Never mark fully complete
            )
        self._progress_task_id = None

    def _ensure_progress_cleared(self):
        """Make absolutely sure no progress indicator is active before showing input prompt"""
        self.streaming_manager.safely_stop_progress()

        # Force redraw the prompt area
        print("\033[2K", end="\r")  # Clear the current line

    async def chat_loop(self):
        """Main chat loop with execution isolation"""
        # Initialize logging for this session
        timestamp = datetime.datetime.now()
        session_id = timestamp.strftime("%Y%m%d_%H%M")

        # Setup logging for this session
        _session_logger = setup_logger(f"chat_{session_id}.log")  # noqa: F841

        # Display ASCII art banner (printed once per process)
        print_ascii_banner(self.console)

        welcome_message = """

Welcome to Penguin! 

**Quick commands**
- `/help` — Command list
- `/info` — Session and config info
- `/exit` — Quit the chat

**Shortcuts**
- Alt+Enter for new lines
- Enter to submit

"""

        # Render welcome copy without a panel to keep the intro minimal
        try:
            from rich.markdown import Markdown

            self.console.print(Markdown(welcome_message))
        except Exception:
            self.console.print(welcome_message)

        # Track consecutive interrupts for double-Ctrl+C exit
        _consecutive_interrupts = 0

        while True:
            try:
                # Clear any lingering progress bars before showing input
                self._ensure_progress_cleared()

                # Use prompt_toolkit instead of input()
                prompt_html = HTML(f"<prompt>You [{self.message_count}]: </prompt>")
                try:
                    user_input = await self.session.prompt_async(prompt_html)
                    _consecutive_interrupts = 0  # Reset on successful input
                except KeyboardInterrupt:
                    # Ctrl+C during input - cancel current line, don't exit
                    _consecutive_interrupts += 1
                    if _consecutive_interrupts >= 2:
                        self.console.print(
                            "\n[yellow]Double interrupt - exiting...[/yellow]"
                        )
                        break
                    self.console.print(
                        "\n[dim]Ctrl+C pressed. Press again to exit, or type /exit[/dim]"
                    )
                    continue

                if user_input.lower() in ["exit", "quit", "/cancel"]:
                    break

                if not user_input.strip():
                    continue

                # Reset interrupt counter on valid input
                _consecutive_interrupts = 0

                # Increment conversation turn for new user input
                self.current_conversation_turn += 1
                # Reset streaming state
                self.streaming_manager.set_streaming(False)
                self.streaming_manager.streaming_buffer = ""
                self.streaming_manager.streaming_reasoning_buffer = ""
                self.streaming_manager.streaming_role = "assistant"
                self.streaming_manager._active_stream_id = None
                self.last_completed_message = ""
                self.last_completed_message_normalized = ""

                # DON'T display user input here - let event system handle it
                # (Prevents duplicate display: once here, once from Core event)
                # self.display_manager.display_message(user_input, "user")

                # Add user message to processed messages to prevent duplication
                user_msg_key = f"user:{user_input[:50]}"
                self.processed_messages.add(user_msg_key)
                self.message_turn_map[user_msg_key] = self.current_conversation_turn

                # Handle @agent-name syntax for explicit agent invocation
                if user_input.startswith("@"):
                    # Parse @agent-name message
                    parts = user_input[1:].split(" ", 1)
                    target_agent = parts[0].strip()
                    message_content = parts[1].strip() if len(parts) > 1 else ""

                    if not target_agent:
                        self.display_manager.display_message(
                            "Usage: @agent-name <message>", "error"
                        )
                        continue

                    if not message_content:
                        self.display_manager.display_message(
                            f"Please provide a message for @{target_agent}", "error"
                        )
                        continue

                    # Check if agent exists (either as persona or registered agent)
                    personas = {
                        entry.get("name") for entry in self.core.get_persona_catalog()
                    }
                    roster_ids = {
                        entry.get("id") for entry in self.core.get_agent_roster()
                    }

                    if target_agent not in personas and target_agent not in roster_ids:
                        available = sorted(personas | roster_ids - {None})
                        self.display_manager.display_message(
                            f"Unknown agent '@{target_agent}'. Available: {', '.join(available)}",
                            "error",
                        )
                        continue

                    # If it's a persona but not yet spawned, spawn it
                    if target_agent in personas and target_agent not in roster_ids:
                        try:
                            self.core.ensure_agent_conversation(target_agent)
                            # Store persona in conversation metadata
                            conv = (
                                self.core.conversation_manager.get_agent_conversation(
                                    target_agent
                                )
                            )
                            if conv and hasattr(conv, "session") and conv.session:
                                conv.session.metadata["persona"] = target_agent
                            self.display_manager.display_message(
                                f"Spawned agent '{target_agent}' from persona", "system"
                            )
                        except Exception as e:
                            self.display_manager.display_message(
                                f"Failed to spawn agent: {e}", "error"
                            )
                            continue

                    # Send message to the target agent
                    try:
                        success = await self.core.send_to_agent(
                            target_agent, message_content
                        )
                        if success:
                            self.display_manager.display_message(
                                f"Message sent to @{target_agent}", "system"
                            )
                        else:
                            self.display_manager.display_message(
                                f"Failed to send message to @{target_agent}", "error"
                            )
                    except Exception as e:
                        self.display_manager.display_message(
                            f"Error sending to @{target_agent}: {e}", "error"
                        )
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    command_parts = user_input[1:].split(
                        " ", 2
                    )  # Split into max 3 parts
                    command = command_parts[0].lower()

                    # Run handle_command through interface instead of all the individual handlers
                    try:
                        # For /run command, we need special handling for callbacks
                        if command == "run":
                            # Create callbacks for RunMode
                            # Stream callbacks removed - using event system only
                            async def ui_update_callback():
                                # Can be expanded with UI refresh logic if needed
                                pass

                            # Handle through interface
                            response = await self.interface.handle_command(
                                user_input[1:],  # Remove the leading slash
                                runmode_stream_cb=None,
                                runmode_ui_update_cb=ui_update_callback,
                            )
                        elif command == "image":
                            # Explicit handling of /image so we can stream the vision response correctly
                            try:
                                import shlex

                                # Parse arguments: /image <path> [description...]
                                # Use shlex so quoted paths with spaces work correctly.
                                raw = user_input[1:]  # drop leading "/"

                                # Normalize: remove line continuation backslashes
                                raw = raw.replace("\\n", "").replace("\\r\\n", "")

                                # Normalize drag-and-drop input
                                # Remove line continuation backslashes and join multiline paths
                                raw = raw.replace("\\ ", " ")
                                raw = " ".join(raw.split())
                                try:
                                    tokens = shlex.split(raw)
                                except ValueError:
                                    tokens = raw.split()

                                args = tokens[1:] if len(tokens) > 1 else []
                                valid_ext = {
                                    ".png",
                                    ".jpg",
                                    ".jpeg",
                                    ".gif",
                                    ".webp",
                                    ".bmp",
                                }
                                image_paths: List[str] = []
                                description_parts: List[str] = []

                                for token in args:
                                    cleaned = token.strip().strip("'\"")
                                    suffix = Path(cleaned).suffix.lower()
                                    if suffix in valid_ext and os.path.exists(cleaned):
                                        image_paths.append(cleaned)
                                    else:
                                        description_parts.append(token)

                                if not image_paths:
                                    # Ask interactively if no path provided (prompt_toolkit)
                                    try:
                                        prompt_html = HTML(
                                            "<prompt>Drag and drop your image here: </prompt>"
                                        )
                                        prompted = (
                                            (
                                                await self.session.prompt_async(
                                                    prompt_html
                                                )
                                            )
                                            .strip()
                                            .strip("'\"")
                                        )
                                    except KeyboardInterrupt:
                                        self.display_manager.display_message(
                                            "Image input cancelled.", "system"
                                        )
                                        continue
                                    if prompted:
                                        image_paths = [prompted]

                                # Validate the file exists
                                missing = [
                                    p for p in image_paths if not os.path.exists(p)
                                ]
                                if not image_paths or missing:
                                    missing_label = (
                                        ", ".join(missing) if missing else "(none)"
                                    )
                                    self.display_manager.display_message(
                                        f"Image file not found: {missing_label}",
                                        "error",
                                    )
                                    continue

                                description = " ".join(description_parts).strip()
                                if not description:
                                    try:
                                        prompt_html = HTML(
                                            "<prompt>Description (optional): </prompt>"
                                        )
                                        description = (
                                            await self.session.prompt_async(prompt_html)
                                        ).strip()
                                    except KeyboardInterrupt:
                                        description = ""

                                if not description:
                                    description = "Describe this image."

                                # Check config-level vision flag
                                vision_enabled = bool(
                                    getattr(
                                        getattr(self.core, "model_config", None),
                                        "vision_enabled",
                                        False,
                                    )
                                )
                                client_supports = False
                                api_client = getattr(self.core, "api_client", None)
                                handler = getattr(api_client, "client_handler", None)
                                for candidate in (handler, api_client):
                                    if candidate and hasattr(
                                        candidate, "supports_vision"
                                    ):
                                        try:
                                            client_supports = bool(
                                                candidate.supports_vision()
                                            )
                                        except Exception:
                                            client_supports = False

                                if image_paths and not (
                                    vision_enabled or client_supports
                                ):
                                    self.display_manager.display_message(
                                        "Vision is disabled for the current model. "
                                        "Enable `model.vision_enabled` or switch to a vision-capable model.",
                                        "error",
                                    )
                                    continue

                                # Check actual model capability from OpenRouter specs
                                model_id = getattr(
                                    getattr(self.core, "model_config", None),
                                    "model",
                                    "",
                                )
                                try:
                                    from penguin.llm.model_config import (
                                        ModelSpecsService,
                                    )

                                    specs_service = ModelSpecsService()
                                    specs = await specs_service.get_specs(model_id)
                                    if specs and not specs.supports_vision:
                                        self.display_manager.display_message(
                                            f"⚠️  Warning: Model `{model_id}` does not report vision support "
                                            f"in OpenRouter. The image may be ignored or cause an error.",
                                            "system",
                                        )
                                except Exception as spec_err:
                                    logger.debug(
                                        f"Could not check model specs: {spec_err}"
                                    )

                                # Send the message through the standard interface path so all
                                # normal streaming / action-result handling is reused
                                response = await self.interface.process_input(
                                    {"text": description, "image_paths": image_paths},
                                    stream_callback=None,
                                )

                                # Finalise any streaming still active
                                if (
                                    hasattr(self, "_streaming_started")
                                    and self._streaming_started
                                ):
                                    self.streaming_manager.finalize_streaming()

                                # Display any action results (e.g. vision-tool output)
                                if (
                                    isinstance(response, dict)
                                    and "action_results" in response
                                ):
                                    for result in response["action_results"]:
                                        if isinstance(result, dict):
                                            if "action" not in result:
                                                result["action"] = "unknown"
                                            if "result" not in result:
                                                result["result"] = (
                                                    "(No output available)"
                                                )
                                            if "status" not in result:
                                                result["status"] = "completed"
                                            self.display_manager.display_action_result(
                                                result
                                            )
                                        else:
                                            self.display_manager.display_message(
                                                str(result), "system"
                                            )
                            except Exception as e:
                                self.display_manager.display_message(
                                    f"Error processing image command: {e!s}", "error"
                                )
                                self.display_manager.display_message(
                                    traceback.format_exc(), "error"
                                )
                            continue  # Skip default command processing for /image
                        else:
                            # Regular command handling
                            response = await self.interface.handle_command(
                                user_input[1:]
                            )

                        # Display response based on its type
                        if isinstance(response, dict):
                            # Handle error responses
                            if "error" in response:
                                self.display_manager.display_message(
                                    response["error"], "error"
                                )

                            # Handle specialized displays FIRST (before generic status)
                            # These have both data and status, show the rich display
                            elif "checkpoints" in response:
                                self.session_manager.display_checkpoints_response(
                                    response
                                )

                            elif "truncations" in response:
                                self.session_manager.display_truncations_response(
                                    response
                                )

                            elif (
                                "token_usage" in response
                                or "token_usage_detailed" in response
                            ):
                                self.session_manager.display_token_usage_response(
                                    response
                                )

                            # Handle conversation list
                            elif "conversations" in response:
                                conversation_summaries = response["conversations"]
                                selected_id = (
                                    self.conversation_menu.select_conversation(
                                        conversation_summaries
                                    )
                                )
                                if selected_id:
                                    load_result = await self.interface.handle_command(
                                        f"chat load {selected_id}"
                                    )
                                    if "status" in load_result:
                                        self.display_manager.display_message(
                                            load_result["status"], "system"
                                        )
                                    elif "error" in load_result:
                                        self.display_manager.display_message(
                                            load_result["error"], "error"
                                        )

                            # Handle list command response
                            elif "projects" in response and "tasks" in response:
                                self.display_manager.display_list_response(response)

                            # Handle model list
                            elif "models_list" in response:
                                models = response["models_list"]
                                models_msg = "Available models:\n"
                                for model in models:
                                    current_marker = (
                                        "→ " if model.get("current", False) else "  "
                                    )
                                    models_msg += f"{current_marker}{model.get('name')} ({model.get('provider')})\n"
                                self.display_manager.display_message(
                                    models_msg, "system"
                                )

                            # Handle generic status messages LAST (fallback)
                            elif "status" in response:
                                self.display_manager.display_message(
                                    response["status"], "system"
                                )

                            # Handle help messages
                            elif "help" in response:
                                help_header = response.get("help", "Available Commands")
                                commands = response.get("commands", [])
                                # Display help without extra indentation
                                self.console.print(
                                    Panel(
                                        f"{help_header}\n\n" + "\n".join(commands),
                                        title="🐧 Help",
                                        border_style="blue",
                                        padding=(1, 2),
                                    )
                                )

                            # Handle conversation list
                            elif "conversations" in response:
                                conversation_summaries = response["conversations"]
                                selected_id = (
                                    self.conversation_menu.select_conversation(
                                        conversation_summaries
                                    )
                                )
                                if selected_id:
                                    load_result = await self.interface.handle_command(
                                        f"chat load {selected_id}"
                                    )
                                    if "status" in load_result:
                                        self.display_manager.display_message(
                                            load_result["status"], "system"
                                        )
                                    elif "error" in load_result:
                                        self.display_manager.display_message(
                                            load_result["error"], "error"
                                        )

                            # Handle token usage display (enhanced)
                            elif (
                                "token_usage" in response
                                or "token_usage_detailed" in response
                            ):
                                self.session_manager.display_token_usage_response(
                                    response
                                )

                            # Handle checkpoints list display
                            elif "checkpoints" in response:
                                self.session_manager.display_checkpoints_response(
                                    response
                                )

                            # Handle truncations display
                            elif "truncations" in response:
                                self.session_manager.display_truncations_response(
                                    response
                                )

                            # Handle model list
                            elif "models_list" in response:
                                models = response["models_list"]
                                models_msg = "Available models:\n"
                                for model in models:
                                    current_marker = (
                                        "→ " if model.get("current", False) else "  "
                                    )
                                    models_msg += f"{current_marker}{model.get('name')} ({model.get('provider')})\n"
                                self.display_manager.display_message(
                                    models_msg, "system"
                                )

                            # Handle list command response
                            elif "projects" in response and "tasks" in response:
                                self.display_manager.display_list_response(response)
                    except Exception as e:
                        self.display_manager.display_message(
                            f"Error executing command: {e!s}", "error"
                        )
                        self.display_manager.display_message(
                            traceback.format_exc(), "error"
                        )

                    continue  # Back to prompt after command processing

                # Process normal message input through interface
                try:
                    # Show brief "Thinking..." - will be stopped by event system when streaming starts
                    # Using transient Progress that auto-cleans up
                    thinking_progress = Progress(
                        SpinnerColumn(),
                        TextColumn("[dim]Thinking...[/dim]"),
                        console=self.console,
                        transient=True,  # Auto-disappears
                    )
                    thinking_progress.start()
                    thinking_progress.add_task("", total=None)

                    # Store ref so event handler can stop it before streaming
                    self._thinking_progress = thinking_progress

                    try:
                        # Process user message through interface
                        response = await self.interface.process_input(
                            {"text": user_input},
                            stream_callback=None,  # Events handle streaming display
                        )
                    finally:
                        # Always clean up thinking indicator
                        if hasattr(self, "_thinking_progress"):
                            try:
                                self._thinking_progress.stop()
                            except Exception:
                                pass
                            delattr(self, "_thinking_progress")

                    # Assistant responses (streaming or not) are now delivered via Core events.
                    # Therefore, avoid printing them directly here to prevent duplicates.
                    # Action results will still be handled below.

                    # Make sure to finalize any streaming that might still be in progress
                    if hasattr(self, "_streaming_started") and self._streaming_started:
                        self.streaming_manager.finalize_streaming()

                    # Action results are now handled via the event system (SYSTEM_OUTPUT category)
                    # No need to display them here - that would cause duplication
                    # Commenting out to prevent duplicate display:
                    #
                    # if isinstance(response, dict) and "action_results" in response:
                    #     for result in response["action_results"]:
                    #         self.display_manager.display_action_result(result)

                    # If the response itself is a string (unlikely but possible), display it.
                    elif isinstance(response, str):
                        self.display_manager.display_message(response)

                except (KeyboardInterrupt, asyncio.CancelledError):
                    # Handle interrupt during processing - don't exit, just cancel current operation
                    self.console.print("\n[yellow]Processing interrupted[/yellow]")
                    self.streaming_manager.safely_stop_progress()
                    # Cleanup any streaming in progress
                    if hasattr(self, "_streaming_started") and self._streaming_started:
                        self.streaming_manager.finalize_streaming()
                    # Don't raise - continue to next prompt iteration
                    continue
                except Exception as e:
                    self.display_manager.display_message(
                        f"Error processing input: {e!s}", "error"
                    )
                    self.display_manager.display_message(
                        traceback.format_exc(), "error"
                    )
                finally:
                    # Always clean up progress display and streaming
                    self.streaming_manager.safely_stop_progress()
                    if hasattr(self, "_streaming_started") and self._streaming_started:
                        self.streaming_manager.finalize_streaming()

                # Save conversation after each message exchange
                self.message_count += 1
                try:
                    if (
                        hasattr(self, "core")
                        and self.core
                        and hasattr(self.core, "conversation_manager")
                    ):
                        self.core.conversation_manager.save()
                        logger.debug(
                            f"Conversation saved after message {self.message_count}"
                        )
                except Exception as save_err:
                    logger.warning(f"Failed to save conversation: {save_err}")

            except (KeyboardInterrupt, asyncio.CancelledError):
                # Fallback handler - use double-interrupt pattern
                _consecutive_interrupts += 1
                if _consecutive_interrupts >= 2:
                    self.console.print(
                        "\n[yellow]Double interrupt - exiting...[/yellow]"
                    )
                    break
                self.console.print("\n[yellow]⚠️ Response stopped by user[/yellow]")
                self.streaming_manager.safely_stop_progress()
                if hasattr(self, "_streaming_started") and self._streaming_started:
                    self.streaming_manager.finalize_streaming()
                continue

            except Exception as e:
                self.display_manager.display_message(f"Chat loop error: {e!s}", "error")
                logger.error(f"Chat loop error: {traceback.format_exc()}")

        # Final save before exit to ensure all messages are persisted
        try:
            if (
                hasattr(self, "core")
                and self.core
                and hasattr(self.core, "conversation_manager")
            ):
                self.core.conversation_manager.save()
                logger.info("Final conversation save on exit")
        except Exception as save_err:
            logger.warning(f"Failed to save conversation on exit: {save_err}")

        self.console.print("\nGoodbye! 👋")

    def _finalize_streaming(self):
        """Finalize streaming and clean up the StreamingDisplay"""
        # Stop the StreamingDisplay
        try:
            self.streaming_manager.finalize_streaming()
        except Exception as e:
            logger.error(f"Error stopping streaming display: {e}")

        # Legacy cleanup for backward compatibility
        if hasattr(self, "streaming_live") and self.streaming_live:
            try:
                self.streaming_live.stop()
                self.streaming_live = None
            except:
                pass  # Suppress any errors during cleanup

        self._streaming_started = False
        self._streaming_session_id = None
        self._active_stream_id = None

    def set_streaming(self, enabled: bool = True) -> None:
        """
        Force streaming mode on or off directly through the API client
        """
        if hasattr(self.core, "model_config") and self.core.model_config is not None:
            self.core.model_config.streaming_enabled = enabled
            print(f"[DEBUG] Set streaming_enabled={enabled} in core.model_config")

        if hasattr(self.core, "api_client") and self.core.api_client is not None:
            if hasattr(self.core.api_client, "model_config"):
                self.core.api_client.model_config.streaming_enabled = enabled
                print(
                    f"[DEBUG] Set streaming_enabled={enabled} in api_client.model_config"
                )

        print(f"[DEBUG] Streaming mode {'enabled' if enabled else 'disabled'}")

    def switch_client_preference(self, preference: str = "openrouter") -> None:
        """
        Try switching the client preference for testing different backends

        Args:
            preference: "openrouter", "native", or "litellm" (optional extra)
        """
        if hasattr(self.core, "model_config") and self.core.model_config is not None:
            old_preference = self.core.model_config.client_preference
            self.core.model_config.client_preference = preference
            print(
                f"[DEBUG] Changed client_preference from {old_preference} to {preference}"
            )

            # Attempt to reinitialize API client with new preference
            if hasattr(self.core, "api_client") and self.core.api_client is not None:
                try:
                    from penguin.llm.api_client import APIClient

                    self.core.api_client = APIClient(self.core.model_config)
                    self.core.api_client.set_system_prompt(self.core.system_prompt)
                    print(
                        f"[DEBUG] Reinitialized API client with preference {preference}"
                    )
                except Exception as e:
                    print(f"[ERROR] Failed to reinitialize API client: {e}")
