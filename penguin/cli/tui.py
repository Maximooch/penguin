from __future__ import annotations
import asyncio
import logging
import traceback
from typing import Any, Dict, Optional

# Textual imports
from textual.app import App, ComposeResult # type: ignore
from textual.containers import Container, VerticalScroll # type: ignore
from textual.reactive import reactive # type: ignore

# Header / Footer / Input etc. are always present. Expander was introduced in
# Textual 0.8x – older installs may not export it which raises an ImportError
# during dynamic attribute lookup. We therefore attempt the import lazily and
# fall back to a sentinel so the rest of the code can degrade gracefully.

# Standard Textual widgets always present
from textual.widgets import Header, Footer, Input, Static, Markdown as TextualMarkdown, Collapsible # type: ignore
from textual.suggester import Suggester # type: ignore

try:
    # Available from Textual ≥ 0.53 (approx). If the current version doesn't
    # have it the except block sets a stub which signals "feature unsupported".
    from textual.widgets import Expander  # type: ignore
except ImportError:  # pragma: no cover – depends on external library version
    Expander = None  # type: ignore[misc, assignment]

# ------------------------------------------------------------------
# Expander fallback for older Textual versions
# ------------------------------------------------------------------
# Textual's built-in `Expander` arrived around 0.81.  On older installs we
# provide a *very* small shim that gives the essentials: a clickable /
# focusable summary line that toggles the visibility of the body Markdown.

# If the above import failed on older Textual versions we expose a
# *minimal* fallback that provides interactive collapse / expand.
except ImportError:  # pragma: no cover – depends on external library version
    Expander = None  # type: ignore[misc, assignment]

# ------------------------------------------------------------------
# Fallback implementation (always defined when Expander is None)
# ------------------------------------------------------------------

if Expander is None:
    class SimpleExpander(Static, can_focus=True):  # type: ignore[misc]
        """Minimal expander for Textual <0.8x.

        • Arrow marker (▶ / ▼) indicates collapsed vs expanded state.
        • `Enter` key or mouse click toggles the body visibility.
        """

        open_state = reactive(False)

        BINDINGS = [("enter", "toggle", "Toggle"), ("space", "toggle", "Toggle"), ("ctrl+r", "toggle", "Toggle")]

        def __init__(self, summary: str, body_md: str, *, open: bool = False):  # noqa: A002 – param name mandated by API
            super().__init__()
            self._summary_text = summary.strip() or "Details"
            self._body_md = body_md
            self.open_state = open

        # --------------------------- Compose ---------------------------
        def compose(self) -> ComposeResult:  # noqa: D401 – framework signature
            # Header line with arrow indicator
            arrow = "▼" if self.open_state else "▶"
            yield Static(f"{arrow} {self._summary_text}", classes="expander-summary")

            # Body (conditionally mounted)
            if self.open_state:
                yield TextualMarkdown(self._body_md, classes="expander-body")

        # ---------------------------- Events ---------------------------
        def on_click(self) -> None:  # Textual will provide the event arg implicitly
            self.action_toggle()

        def action_toggle(self) -> None:  # noqa: D401 – Textual naming
            """Toggle the collapsed / expanded state."""
            self.open_state = not self.open_state

        # ------------------------ Reactive watch -----------------------
        def watch_open_state(self, new_state: bool) -> None:  # noqa: D401
            # Update arrow on summary
            try:
                summary_widget = self.query_one(".expander-summary", Static)
                arrow = "▼" if new_state else "▶"
                summary_widget.update(f"{arrow} {self._summary_text}")
            except Exception:
                pass  # Summary might not exist during early init

            # Mount or remove body widget
            if new_state:
                # If body already present – nothing to do
                if not self.query(".expander-body"):
                    self.mount(TextualMarkdown(self._body_md, classes="expander-body"))
            else:
                for body in self.query(".expander-body"):
                    body.remove()

# Rich imports
from rich.panel import Panel # type: ignore
from rich.text import Text # type: ignore
from rich.console import Group # type: ignore
from rich.markdown import Markdown as RichMarkdown # type: ignore
from rich.syntax import Syntax # type: ignore

# Standard library imports
import os
import signal
import shlex
import re

# Project imports
from penguin.core import PenguinCore
from penguin.cli.interface import PenguinInterface
from penguin.cli.widgets import ToolExecutionWidget, StreamingStateMachine, StreamState
from penguin.cli.widgets.unified_display import UnifiedExecution, ExecutionAdapter, ExecutionStatus
from penguin.cli.command_registry import CommandRegistry


class CommandSuggester(Suggester):
    """Provides autocompletion for slash commands in the TUI."""
    
    def __init__(self):
        super().__init__()
        self.commands = [
            # Chat & Navigation
            "/help",
            "/clear", 
            "/quit",
            "/exit",
            
            # Chat commands
            "/chat list",
            "/chat load",
            "/chat summary",
            
            # RunMode & Tasks
            "/run continuous",
            "/run task",
            "/run stop",
            "/task create",
            "/project create",
            "/list",
            
            # Model & Configuration
            "/models",
            "/model set",
            "/stream on",
            "/stream off",
            "/tokens",
            "/tokens reset",
            "/tokens detail",
            
            # Context
            "/context list",
            "/context load",
            
            # Debug & Development
            "/debug",
            "/debug tokens",
            "/debug stream", 
            "/debug sample",
            "/recover",
        ]
    
    async def get_suggestion(self, value: str) -> str | None:
        """Get completion suggestion for the current input value."""
        if not value.startswith("/"):
            return None
            
        # Find commands that start with the current input
        matches = [cmd for cmd in self.commands if cmd.startswith(value)]
        
        if not matches:
            return None
            
        # Return the first match
        return matches[0]

# Set up logging for debug purposes
logger = logging.getLogger(__name__)

# --- Custom Widgets ---

class ChatMessage(Static, can_focus=True):
    """A widget to display a single chat message.

    • Focusable so user can select with keyboard (Tab / ↑ ↓).
    • Press **c** to copy full plain-text content to clipboard.
    """

    # Enhanced regex – captures optional language identifier (can include hyphens / digits) on the same line
    # and tolerates both LF and CRLF newlines.  Example matches:
    #   ```python\nprint("hi")\n```
    #   ```\r\ncode\r\n```
    # Also handle cases where there's no newline after the language identifier
    CODE_FENCE = re.compile(r"```([^\n`]*?)[\r\n]*(.*?)```", re.S)
    BINDINGS = [("c", "copy", "Copy to clipboard"), ("ctrl+r", "toggle_expander", "Toggle reasoning")]  # visible in footer

    def __init__(self, content: str, role: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.content = content
        self.role = role

    def compose(self) -> ComposeResult:
        """Render the message with code fences highlighted."""

        # Pre-process bespoke tags (<execute>, <execute_command>, etc.) → fenced code
        processed_content = self.content
        
        # Debug: Log the original content to see what we're getting
        if "<execute" in processed_content or "```" in processed_content:
            logger.debug(f"ChatMessage original content (first 500 chars): {processed_content[:500]}")
        
        # Try to handle both execute tags and already-formatted code blocks
        def format_execute_block(match):
            code = match.group(1)
            # Try to detect and fix common formatting issues
            # Fix missing spaces after imports
            code = re.sub(r'import(\w)', r'import \1', code)
            code = re.sub(r'from(\w)', r'from \1', code)
            # Fix comments that got concatenated
            code = re.sub(r'([^#\n])#', r'\1\n#', code)
            # Try to add newlines before common Python keywords if they're missing
            code = re.sub(r'([;\}])([a-z])', r'\1\n\2', code)
            return f"```python\n{code}\n```"
        
        processed_content = re.sub(r"<execute(?:_command|_code)?>(.*?)</execute(?:_command|_code)?>", 
                                   format_execute_block, processed_content, flags=re.S)

        # --- Reasoning / Thinking tokens support -----------------------
        # Convert <thinking>...</thinking> blocks into nice markdown block-quotes
        # so they render in a dim grey style. We prefix each line with '> ' so
        # Rich / Textual Markdown renders it as a quoted block.
        def _convert_thinking(match: re.Match) -> str:
            raw = match.group(1).strip("\n")
            if not raw:
                return ""
            # Prefix each line with '> '
            quoted_lines = ["> " + ln for ln in raw.splitlines()]
            return "\n" + "\n".join(quoted_lines) + "\n"

        processed_content = re.sub(r"<thinking>(.*?)</thinking>", _convert_thinking, processed_content, flags=re.S)
        # ----------------------------------------------------------------

        # --- Convert HTML <details>/<summary> blocks into Textual Expanders ---
        DETAILS_RE = re.compile(r"<details>\s*(<summary>(.*?)</summary>)?(.*?)</details>", re.S)

        pos = 0
        for m in DETAILS_RE.finditer(processed_content):
            before = processed_content[pos:m.start()]
            if before.strip():
                yield TextualMarkdown(before)

            summary_text = m.group(2) or "Details"
            body_md = m.group(3).strip()

            if Expander is not None:
                # Preferred rich interactive widget when available.
                expander = Expander(summary_text, open=False)  # type: ignore[call-arg]
                expander.mount(TextualMarkdown(body_md))
                yield expander
            else:
                # Older Textual – use our minimal interactive fallback.
                yield SimpleExpander(summary_text, body_md, open=False)

            pos = m.end()

        # Remainder after last details block
        remainder = processed_content[pos:]
        if remainder.strip():
            processed_content = remainder
        else:
            processed_content = ""

        # If we already yielded widgets for details, and no remainder, return early
        if pos > 0:
            if processed_content:
                # There was some trailing text outside details block(s)
                yield TextualMarkdown(processed_content)
            return

        # Role label
        if self.role == "user":
            label_text = Text("You", style="bold cyan")
        elif self.role == "assistant":
            label_text = Text("Penguin", style="bold green")
        else:
            label_text = Text(self.role.capitalize(), style="bold yellow")

        yield Static(label_text, classes="message-label")

        parts = self.CODE_FENCE.split(processed_content)
        # parts = [before, lang1, code1, after1, lang2, code2, ...]
        if len(parts) == 1:
            # No fenced code detected – heuristic: treat whole block as code if it *looks* like code
            if self._looks_like_code(processed_content):
                syntax_obj = Syntax(processed_content.strip(), "python", theme="monokai", line_numbers=False)
                yield Static(syntax_obj, classes="code-block")
            else:
                yield TextualMarkdown(processed_content, classes=f"message-content {self.role}")
            return

        for idx, chunk in enumerate(parts):
            mod = idx % 3
            if mod == 0:
                # narrative segment
                if chunk.strip():
                    yield TextualMarkdown(chunk)
            elif mod == 1:
                # language identifier (may be empty)
                lang = chunk.strip() or "python"  # Default to python if no language specified
                if idx + 1 < len(parts):
                    code = parts[idx + 1]
                    # Clean up the code a bit
                    code = code.strip()
                    if code:
                        try:
                            syntax_obj = Syntax(code, lang, theme="monokai", line_numbers=True)
                            yield Static(syntax_obj, classes="code-block")
                        except Exception as e:
                            # Fallback if syntax highlighting fails
                            logger.debug(f"Syntax highlighting failed: {e}")
                            yield TextualMarkdown(f"```{lang}\n{code}\n```")
            else:
                # code segment handled by mod==1
                continue

    def stream_in(self, chunk: str) -> None:
        """Append a chunk of text to the message content."""
        # Clean up streaming artifacts before adding to content
        cleaned_chunk = self._clean_streaming_artifacts(chunk)
        self.content += cleaned_chunk
        # Query the Markdown widget and update it
        try:
            markdown_widget = self.query_one(TextualMarkdown)
            markdown_widget.update(self.content)
        except Exception as e:
            logger.error(f"Error updating markdown widget: {e}")
    
    def _clean_streaming_artifacts(self, chunk: str) -> str:
        """Clean up common streaming artifacts from different providers."""
        if not chunk:
            return chunk
            
        # Remove leading/trailing whitespace while preserving intentional formatting
        cleaned = chunk
        
        # Clean up orphaned block quote markers that aren't part of reasoning
        # This handles cases where > appears at start of lines but isn't reasoning
        lines = cleaned.split('\n')
        processed_lines = []
        
        for line in lines:
            # Skip cleaning if this looks like intentional markdown blockquote
            if line.startswith('> ') and len(line) > 2:
                # Check if this is likely a reasoning token artifact vs intentional quote
                # Reasoning artifacts tend to be short or have specific patterns
                if len(line.strip()) < 3 or line.strip() in ['> ', '>', '> \n']:
                    continue  # Skip likely artifacts
                    
            processed_lines.append(line)
        
        cleaned = '\n'.join(processed_lines)
        
        # Remove common streaming artifacts
        artifacts_to_remove = [
            '\x00',  # Null bytes
            '\ufffd',  # Replacement character
            '\r',  # Carriage returns (keep \n)
        ]
        
        for artifact in artifacts_to_remove:
            cleaned = cleaned.replace(artifact, '')
            
        # Clean up excessive whitespace but preserve paragraph breaks
        # Remove multiple consecutive spaces (but not intentional indentation)
        import re
        cleaned = re.sub(r' {3,}', ' ', cleaned)  # 3+ spaces -> 1 space
        
        # Clean up excessive newlines (more than 2 consecutive)
        cleaned = re.sub(r'\n{4,}', '\n\n\n', cleaned)
        
        return cleaned
    
    def _clean_final_content(self, content: str) -> str:
        """Final cleanup of complete streamed content."""
        if not content:
            return content
            
        import re
        
        # Process HTML details tags since Textual markdown doesn't support them
        content = self._process_details_tags(content)
        
        # Remove orphaned block quote markers that may have been left behind
        lines = content.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Remove lines that are just orphaned block quote markers
            if line.strip() in ['>', '> ', '> \n']:
                continue
                
            # Clean up lines that start with > but have minimal content (likely artifacts)
            if line.startswith('> ') and len(line.strip()) <= 3:
                continue
                
            cleaned_lines.append(line)
        
        content = '\n'.join(cleaned_lines)
        
        # Clean up any remaining streaming artifacts
        content = re.sub(r'\n{3,}', '\n\n', content)  # Max 2 consecutive newlines
        content = re.sub(r' {2,}', ' ', content)      # Max 1 space between words
        
        # Remove trailing whitespace from lines while preserving intentional formatting
        lines = content.split('\n')
        content = '\n'.join(line.rstrip() for line in lines)
        
        return content.strip()
    
    def _process_details_tags(self, content: str) -> str:
        """Convert HTML details tags to markdown-friendly format."""
        import re
        
        # Pattern to match <details><summary>...</summary>content</details>
        details_pattern = r'<details>\s*<summary>([^<]*)</summary>\s*(.*?)</details>'
        
        def replace_details(match):
            summary = match.group(1).strip()
            details_content = match.group(2).strip()
            
            # Remove any existing > prefixes from the content to avoid double-prefixing
            cleaned_content = re.sub(r'^> ', '', details_content, flags=re.MULTILINE)
            
            # Store the original content for toggling
            if not hasattr(self, '_original_reasoning_content'):
                self._original_reasoning_content = cleaned_content
            
            # Create a collapsible section with clear visual indicator
            return f"**{summary}** `[🧠 Reasoning - Press Ctrl+R to toggle]`\n\n> {cleaned_content.replace(chr(10), chr(10) + '> ')}"
        
        # Replace all details tags
        content = re.sub(details_pattern, replace_details, content, flags=re.DOTALL)
        
        return content

    def end_stream(self) -> None:
        """Finalize the stream, perhaps by adding a specific style."""
        self.remove_class("streaming")
        
        # Final cleanup of the complete content
        self.content = self._clean_final_content(self.content)
        
        # Update the markdown widget with cleaned content
        try:
            markdown_widget = self.query_one(TextualMarkdown)
            markdown_widget.update(self.content)
        except Exception as e:
            logger.error(f"Error updating markdown widget during final cleanup: {e}")

        # ---------------------------------------------
        # Post-processing: wrap reasoning in <details>
        # ---------------------------------------------
        try:
            if "<details>" in self.content:
                return  # already wrapped by Core or previous pass

            lines = self.content.splitlines()
            # Extract leading reasoning lines (those beginning with '> ')
            reasoning_lines: list[str] = []
            body_lines: list[str] = []
            collecting_reasoning = True
            for ln in lines:
                if collecting_reasoning and ln.startswith("> "):
                    reasoning_lines.append(ln[2:])  # strip block-quote marker
                else:
                    collecting_reasoning = False
                    body_lines.append(ln)

            if reasoning_lines:
                # Build collapsible markdown block
                details_md = (
                    "<details>\n"
                    "<summary>🧠  Click to show / hide internal reasoning</summary>\n\n"
                    + "\n".join(reasoning_lines)
                    + "\n\n</details>\n\n"
                )
                self.content = details_md + "\n".join(body_lines)

                # Update rendered Markdown widget
                markdown_widget = self.query_one(TextualMarkdown)
                markdown_widget.update(self.content)
        except Exception as e:  # pragma: no cover – defensive
            logger.debug(f"Post-stream reasoning wrap failed: {e}")

        # ------------------------------------------------------------------
        # Heuristic fallback – some providers do NOT tag reasoning chunks.
        # If no '> ' lines were found above, attempt to treat consecutive
        # bold-heading paragraphs (lines starting with '**') at the start of
        # the message as reasoning.
        # ------------------------------------------------------------------
        # DISABLED: This heuristic doesn't work well with Gemini's output format
        # which uses bold headings throughout the response, not just for reasoning
        """
        try:
            if '<details>' not in self.content:
                lines = self.content.splitlines()
                reasoning_lines: list[str] = []
                body_start_index = 0

                # Collect leading bold-heading blocks and any interstitial
                # blank lines until we hit the first non-bold content.
                for idx, ln in enumerate(lines):
                    if ln.startswith("**") or (ln.strip() == "" and reasoning_lines):
                        reasoning_lines.append(ln)
                    elif not reasoning_lines and ln.strip() == "":
                        # Skip leading empty lines before first heading
                        continue
                    else:
                        body_start_index = idx
                        break

                if reasoning_lines:
                    body_lines = lines[body_start_index:]
                    details_md = (
                        "<details>\n"
                        "<summary>🧠  Click to show / hide internal reasoning</summary>\n\n"
                        + "\n".join(reasoning_lines)
                        + "\n\n</details>\n\n"
                    )
                    self.content = details_md + "\n".join(body_lines)
                    markdown_widget = self.query_one(TextualMarkdown)
                    markdown_widget.update(self.content)
        except Exception as e:
            logger.debug(f"Fallback reasoning wrap failed: {e}")
        """

    # --------------------------
    # Copy-to-clipboard support
    # --------------------------
    async def action_copy(self) -> None:  # noqa: D401 – Textual naming convention
        """Copy this message's raw text to the system clipboard (if available)."""
        copied = False
        try:
            import pyperclip  # type: ignore

            pyperclip.copy(self.content)
            copied = True
        except Exception:
            copied = False

        # Notify the main app so status-bar can show feedback
        try:
            self.post_message(StatusMessage("Copied ✅" if copied else "📋 Clipboard unavailable"))
        except Exception:
            pass

    def _looks_like_code(self, text: str) -> bool:
        """Simple heuristic to guess if *text* is code when no fences are present."""
        code_keywords = ["def ", "class ", "import ", "return ", "from ", "for ", "while "]
        if any(kw in text for kw in code_keywords):
            # If more than 40% of lines are indented or end with ':' assume code block
            lines = text.splitlines()
            if not lines:
                return False
            indented = sum(1 for ln in lines if ln.startswith(" ") or ln.startswith("\t"))
            return indented / len(lines) > 0.4 or len(lines) < 4  # small snippets often code
        return False

    # ------------------------------
    # Ctrl+R → toggle first expander
    # ------------------------------
    def action_toggle_expander(self) -> None:  # noqa: D401 – keybinding handler
        """Toggle the first collapsible reasoning block (if any)."""
        try:
            # Try to find traditional expander widgets first
            if Expander is not None:
                exp = self.query_one(Expander)  # type: ignore[arg-type]
                exp.open = not exp.open  # type: ignore[attr-defined]
                return
            else:
                exp = self.query_one(SimpleExpander)
                exp.action_toggle()
                return
        except Exception:
            # No traditional expander found, try to toggle reasoning blockquotes
            pass
        
        # Toggle reasoning blockquotes by modifying content
        try:
            markdown_widget = self.query_one(TextualMarkdown)
            current_content = self.content
            
            # Check if reasoning is currently visible (contains blockquotes after reasoning header)
            if '🧠 Reasoning' in current_content and '> ' in current_content:
                # Hide reasoning by removing blockquotes
                import re
                lines = current_content.split('\n')
                filtered_lines = []
                skip_reasoning = False
                
                for line in lines:
                    if '🧠 Reasoning' in line and 'Press Ctrl+R to toggle' in line:
                        # Replace the toggle indicator to show it's hidden
                        filtered_lines.append(line.replace('🧠 Reasoning - Press Ctrl+R to toggle', '🧠 Reasoning Hidden - Press Ctrl+R to show'))
                        skip_reasoning = True
                    elif skip_reasoning and line.startswith('> '):
                        continue  # Skip reasoning lines
                    elif skip_reasoning and line.strip() == '':
                        continue  # Skip empty lines after reasoning
                    else:
                        skip_reasoning = False
                        filtered_lines.append(line)
                
                self.content = '\n'.join(filtered_lines)
                
            elif '🧠 Reasoning Hidden' in current_content:
                # Show reasoning by restoring from original content
                if hasattr(self, '_original_reasoning_content'):
                    # Restore the full reasoning content
                    restored_reasoning = f"**🧠 Click to show / hide internal reasoning** `[🧠 Reasoning - Press Ctrl+R to toggle]`\n\n> {self._original_reasoning_content.replace(chr(10), chr(10) + '> ')}"
                    # Replace the hidden indicator with the full content
                    self.content = current_content.replace('**🧠 Click to show / hide internal reasoning** `[🧠 Reasoning Hidden - Press Ctrl+R to show]`', restored_reasoning)
                else:
                    # Fallback - just change the indicator
                    self.content = current_content.replace('🧠 Reasoning Hidden - Press Ctrl+R to show', '🧠 Reasoning - Press Ctrl+R to toggle')
                
            markdown_widget.update(self.content)
            
        except Exception:
            # No reasoning content to toggle
            pass

# Simple status message to bubble up to PenguinTextualApp
from textual.message import Message  # after other imports # type: ignore


class StatusMessage(Message):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()


class PenguinTextualApp(App):
    """A Textual-based chat interface for Penguin AI."""
    
    CSS_PATH = "tui.css"
    
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
        ("ctrl+d", "show_debug", "Debug"),
    ]
    
    status_text = reactive("Initializing...")
    
    def __init__(self):
        super().__init__()
        self.core: Optional[PenguinCore] = None
        self.interface: Optional[PenguinInterface] = None
        self.debug_messages: list[str] = []
        self.current_streaming_widget: Optional[ChatMessage] = None
        self.last_finalized_content: Optional[str] = None # For deduplication
        self.dedup_clear_task: Optional[asyncio.Task] = None
        self._runmode_message: Optional[ChatMessage] = None  # For RunMode output
        self._stream_timeout_task: Optional[asyncio.Task] = None  # Stream timeout monitor
        self._stream_start_time: float = 0
        self._stream_chunk_count: int = 0
        self._conversation_list: Optional[list] = None  # For conversation selection
        self._reasoning_content: str = ""  # For accumulating reasoning content during streaming
        self._original_reasoning_content: str = ""  # For storing original reasoning content for toggle
        
        # New: Tool execution tracking
        self._active_tools: Dict[str, ToolExecutionWidget] = {}
        self.command_registry: Optional[CommandRegistry] = None
        self.streaming_state_machine = StreamingStateMachine()

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Container(id="main-container"):
            yield VerticalScroll(id="message-area")
            yield Input(
                placeholder="Type your message... (/help for commands, Tab for autocomplete)", 
                id="input-box",
                suggester=CommandSuggester()
            )
        yield Static(id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.query_one("#status-bar", Static).update(self.status_text)
        self.query_one(Input).focus()
        asyncio.create_task(self.initialize_core())

    def add_message(self, content: str, role: str) -> ChatMessage:
        """Helper to add a new message widget to the display."""
        message_area = self.query_one("#message-area", VerticalScroll)
        new_message = ChatMessage(content, role)
        message_area.mount(new_message)
        # Immediately jump to bottom to avoid animation jitter
        self._scroll_to_bottom()
        return new_message

    def _scroll_to_bottom(self) -> None:
        """Scroll the message area to the bottom without animation."""
        try:
            message_area = self.query_one("#message-area", VerticalScroll)
            message_area.scroll_end(animate=False)  # immediate jump
        except Exception:
            pass
    
    def _format_system_output(self, action_name: str, result_str: str, max_lines: int = 20) -> str:
        """Format system output with expand/collapse for long content."""
        lines = result_str.splitlines()
        
        if len(lines) <= max_lines:
            # Short output, display normally
            return f"✅ Tool `{action_name}` output:\n```text\n{result_str}\n```"
        
        # Long output, use collapsible format
        preview_lines = lines[:max_lines]
        remaining_lines = lines[max_lines:]
        
        preview_text = "\n".join(preview_lines)
        full_text = "\n".join(remaining_lines)
        
        # Create collapsible content
        content = f"✅ Tool `{action_name}` output (showing {max_lines}/{len(lines)} lines):\n"
        content += f"```text\n{preview_text}\n```\n\n"
        content += "<details>\n"
        content += f"<summary>Show {len(remaining_lines)} more lines...</summary>\n\n"
        content += f"```text\n{full_text}\n```\n\n"
        content += "</details>"
        
        return content

    async def initialize_core(self) -> None:
        """Initialize the PenguinCore and interface."""
        try:
            self.status_text = "Initializing Penguin Core..."
            self.core = await PenguinCore.create(fast_startup=True, show_progress=False)
            
            self.status_text = "Setting up interface..."
            self.core.register_ui(self.handle_core_event)
            self.debug_messages.append("Registered UI event handler with core")
            
            self.interface = PenguinInterface(self.core)
            
            # Initialize command registry
            self.status_text = "Loading commands..."
            self.command_registry = CommandRegistry()
            
            self.status_text = "Ready"
            welcome_panel = Panel("🐧 [bold cyan]Penguin AI[/bold cyan] is ready! Type a message or /help. Use Tab for command autocomplete.", title="Welcome", border_style="cyan")
            self.query_one("#message-area").mount(Static(welcome_panel))

        except Exception as e:
            self.status_text = f"Error initializing core: {e}"
            error_panel = Panel(f"[bold red]Fatal Error[/bold red]\n{e}", title="Initialization Failed", border_style="red")
            self.query_one("#message-area").mount(Static(error_panel))
            error_details = traceback.format_exc()
            logger.error(f"TUI initialization error: {error_details}")
            self.debug_messages.append(f"Initialization Error: {error_details}")

    def watch_status_text(self, status: str) -> None:
        """Update the status bar when status_text changes."""
        try:
            if self.is_mounted:
                status_bar = self.query_one("#status-bar", Static)
                status_bar.update(f"[dim]{status}[/dim]")
        except Exception:
            pass

    async def handle_core_event(self, event_type: str, data: Any) -> None:
        logger.debug(f"TUI handle_core_event {event_type} keys={list(data.keys()) if isinstance(data, dict) else 'n/a'}")
        """Handle events from PenguinCore."""
        try:
            self.debug_messages.append(f"Received event: {event_type} with data: {str(data)[:200]}")
            
            if event_type == "message":
                role = data.get("role", "unknown")
                content = data.get("content", "")
                category = data.get("category", "DIALOG")
                
                # Skip user messages that we already displayed
                if role == "user":
                    self.debug_messages.append(f"Skipping user message (already displayed): {content[:50]}...")
                    return
                
                # Check for and prevent rendering of duplicate assistant message post-stream
                if role == "assistant" and content.strip() == (self.last_finalized_content or "").strip():
                    self.last_finalized_content = None # Consume the dedupe key
                    self.debug_messages.append(f"Deduplicated assistant message: {content[:50]}...")
                    return
                
                # Handle system messages – but suppress duplicate "Tool Result" / "Action Result" output
                if role == "system" or category in ("SYSTEM", "SYSTEM_OUTPUT"):
                    lowered = content.lower().lstrip()
                    if lowered.startswith("tool result") or lowered.startswith("action result"):
                        # Already rendered via ToolExecutionWidget – skip duplicate
                        self.debug_messages.append("Skipped duplicate system output message")
                        return
                    # Format other system messages
                    if len(content) > 500:
                        content = self._format_system_output("System", content)
                    self.add_message(content, "system")
                else:
                    self.add_message(content, role)

            elif event_type == "stream_chunk":
                chunk = data.get("chunk", "")
                is_final = data.get("is_final", False)
                stream_id = data.get("stream_id", "default")
                message_type = data.get("message_type", "assistant")

                if not self.current_streaming_widget and chunk:
                    # First chunk of a new stream, create the widget
                    self.current_streaming_widget = self.add_message("", "assistant")
                    self.current_streaming_widget.add_class("streaming")
                    self._stream_start_time = asyncio.get_event_loop().time()
                    self._stream_chunk_count = 0
                    
                    # Initialize reasoning content accumulator
                    self._reasoning_content = ""
                    
                    # Start stream timeout monitor
                    self._stream_timeout_task = asyncio.create_task(self._monitor_stream_timeout())

                if self.current_streaming_widget and chunk:
                    self._stream_chunk_count += 1
                    
                    # Check for potential streaming issues
                    current_time = asyncio.get_event_loop().time()
                    if hasattr(self, '_stream_start_time'):
                        stream_duration = current_time - self._stream_start_time
                        
                        # Detect potential hang (no final chunk after reasonable time)
                        if stream_duration > 30 and not is_final:
                            self.debug_messages.append(f"Long stream detected: {stream_duration:.1f}s, {self._stream_chunk_count} chunks")
                    
                    if not is_final:
                        # Handle different message types
                        if message_type == "reasoning":
                            # Accumulate reasoning content separately
                            self._reasoning_content += chunk
                        else:
                            # Stream assistant content directly
                            self.current_streaming_widget.stream_in(chunk)
                            # Keep the latest buffer for deduplication against upcoming message event
                            self.last_finalized_content = self.current_streaming_widget.content
                            self._scroll_to_bottom()
                
                if is_final and self.current_streaming_widget:
                    # Cancel timeout monitor
                    if self._stream_timeout_task:
                        self._stream_timeout_task.cancel()
                        self._stream_timeout_task = None
                    
                    # Finalize the message
                    stream_duration = asyncio.get_event_loop().time() - getattr(self, '_stream_start_time', 0)
                    self.debug_messages.append(f"Stream completed: {stream_duration:.1f}s, {self._stream_chunk_count} chunks")
                    
                    # Add reasoning content if present
                    if hasattr(self, '_reasoning_content') and self._reasoning_content.strip():
                        reasoning_details = f"<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n{self._reasoning_content.strip()}\n\n</details>\n\n"
                        # Prepend reasoning to the assistant content
                        current_content = self.current_streaming_widget.content
                        self.current_streaming_widget.content = reasoning_details + current_content
                        # Update the markdown widget
                        try:
                            markdown_widget = self.current_streaming_widget.query_one(TextualMarkdown)
                            markdown_widget.update(self.current_streaming_widget.content)
                        except Exception as e:
                            logger.error(f"Error updating markdown widget with reasoning: {e}")
                    
                    # Validate final content
                    final_content = self.current_streaming_widget.content.strip()
                    if not final_content:
                        self.debug_messages.append("Warning: Stream completed with empty content")
                        self.current_streaming_widget.stream_in("[Stream completed with no content]")
                    elif self._detect_incomplete_response(final_content):
                        self.debug_messages.append("Warning: Stream appears to be incomplete")
                        self.current_streaming_widget.stream_in("\n\n[Response may be incomplete - check logs]")
                    
                    self.current_streaming_widget.end_stream()
                    # Buffer already up to date; ensure dedup key is set
                    self.last_finalized_content = self.current_streaming_widget.content
                    
                    self.current_streaming_widget = None
                    # Schedule the dedupe key to be cleared after a short delay
                    self.dedup_clear_task = asyncio.create_task(self._clear_dedup_content())
                    self._scroll_to_bottom()

            elif event_type == "action":
                # Handle XML-style action tags executed by ActionExecutor
                action_name = data.get("type", "unknown")
                action_params = data.get("params", "")
                action_id = data.get("id", None)

                execution = ExecutionAdapter.from_action(action_name, action_params, action_id)
                execution.status = ExecutionStatus.RUNNING

                action_widget = ToolExecutionWidget(execution)
                message_area = self.query_one("#message-area", VerticalScroll)
                message_area.mount(action_widget)

                # Track active execution widgets by ID
                self._active_tools[execution.id] = action_widget
                self._scroll_to_bottom()

            elif event_type == "action_result":
                result_str = data.get("result", "")
                status = data.get("status", "completed")
                action_id = data.get("id", None)

                if action_id in self._active_tools:
                    action_widget = self._active_tools[action_id]
                    # Update status based on result
                    if status == "error":
                        action_widget.update_status(ExecutionStatus.FAILED, error=result_str)
                    else:
                        action_widget.update_status(ExecutionStatus.SUCCESS, result=result_str)

                    # Remove from active tools
                    del self._active_tools[action_id]
                else:
                    # Fallback: show as system message if widget missing
                    if status == "error":
                        content = f"❌ Action failed:\n```\n{result_str}\n```"
                        self.add_message(content, "error")
                    else:
                        content = self._format_system_output("Action", result_str)
                        self.add_message(content, "system")

            elif event_type == "tool_call":
                tool_name = data.get("name", "unknown")
                tool_args = data.get("arguments", {})
                tool_id = data.get("id", None)
                
                # Create unified execution from tool
                execution = ExecutionAdapter.from_tool(tool_name, tool_args, tool_id)
                execution.status = ExecutionStatus.RUNNING
                
                # Create and mount tool execution widget
                tool_widget = ToolExecutionWidget(execution)
                message_area = self.query_one("#message-area", VerticalScroll)
                message_area.mount(tool_widget)
                
                # Track active tool
                self._active_tools[execution.id] = tool_widget
                self._scroll_to_bottom()
            
            elif event_type == "tool_result":
                result_str = data.get("result", "")
                action_name = data.get("action_name", "unknown")
                status = data.get("status", "completed")
                tool_id = data.get("id", None)
                
                # Find the active tool widget
                widget_id = tool_id or action_name
                if widget_id in self._active_tools:
                    tool_widget = self._active_tools[widget_id]
                    
                    # Update status based on result
                    if status == "error":
                        tool_widget.update_status(ExecutionStatus.FAILED, error=result_str)
                    else:
                        tool_widget.update_status(ExecutionStatus.SUCCESS, result=result_str)
                    
                    # Remove from active tools
                    del self._active_tools[widget_id]
                else:
                    # Fallback to old behavior if widget not found
                    if status == "error":
                        content = f"❌ Tool `{action_name}` failed:\n```\n{result_str}\n```"
                        self.add_message(content, "error")
                    else:
                        content = self._format_system_output(action_name, result_str)
                        self.add_message(content, "system")

            elif event_type == "error":
                error_msg = data.get("message", "Unknown error")
                context = data.get("context", None)
                
                # Create error execution widget
                execution = ExecutionAdapter.from_error(error_msg, context)
                error_widget = ToolExecutionWidget(execution)
                
                message_area = self.query_one("#message-area", VerticalScroll)
                message_area.mount(error_widget)
                self._scroll_to_bottom()

        except Exception as e:
            error_msg = f"Error handling core event {event_type}: {e}"
            logger.error(error_msg, exc_info=True)
            self.debug_messages.append(f"Event Handler Error ({event_type}): {e}")
            
            # If streaming was interrupted, clean up
            if event_type == "stream_chunk" and self.current_streaming_widget:
                try:
                    # Cancel timeout monitor
                    if self._stream_timeout_task:
                        self._stream_timeout_task.cancel()
                        self._stream_timeout_task = None
                    
                    self.current_streaming_widget.stream_in(f"\n\n[Stream error: {str(e)}]")
                    self.current_streaming_widget.end_stream()
                    self.current_streaming_widget = None
                except:
                    pass
            
            try:
                self.add_message(error_msg, "error")
            except:
                pass
                
    def _detect_incomplete_response(self, content: str) -> bool:
        """Detect if a response appears to be incomplete."""
        if not content:
            return True
        
        # Check for truncated tool calls - specific patterns from the error
        truncated_tool_patterns = [
            "<pydol",  # Specific truncation seen in logs
            "<execute", "<tool_", "<action_", "<browse",
            "<pydoll_browser_nav", "<pydoll_browser_scr",
            "<pydoll_"
        ]
        
        # Check if content ends with any truncated pattern
        content_lower = content.lower()
        for pattern in truncated_tool_patterns:
            if content_lower.endswith(pattern.lower()):
                return True
            # Also check last 50 characters for mid-response truncation
            if pattern.lower() in content_lower[-50:] and not content_lower.endswith(">"):
                return True
        
        # Check for unmatched angle brackets (tool calls)
        open_brackets = content.count("<")
        close_brackets = content.count(">")
        if open_brackets > close_brackets:
            return True
        
        # Check for incomplete tool call syntax
        incomplete_patterns = [
            "```\n\n<", "```\n<", "</", 
            "*<", ".*<", ") <", ". <"
        ]
        for pattern in incomplete_patterns:
            if pattern in content[-50:]:
                return True
        
        # Check for abrupt endings in the middle of a sentence or tool call
        if content and not content[-1] in '.!?>`\n':
            # If it ends mid-word or with incomplete syntax
            last_chars = content[-20:]
            if any(char in last_chars for char in ['<']) and '>' not in last_chars:
                return True
        
        # Check for common incomplete endings from the logs
        incomplete_endings = [
            "*<pydol", ".*<pydol", ") <pydol", ". <pydol",
            "<pydoll_browser_navigat", "<pydoll_browser_screenshot"
        ]
        for ending in incomplete_endings:
            if content.endswith(ending):
                return True
        
        return False
    
    async def _monitor_stream_timeout(self) -> None:
        """Monitor stream for timeout and handle recovery."""
        try:
            # Wait for reasonable timeout (60 seconds)
            await asyncio.sleep(60)
            
            # If we get here, stream timed out
            if self.current_streaming_widget:
                self.debug_messages.append("Stream timeout detected - forcing completion")
                
                current_content = self.current_streaming_widget.content.strip()
                if self._detect_incomplete_response(current_content):
                    self.current_streaming_widget.stream_in("\n\n[Stream timed out - response may be incomplete]")
                else:
                    self.current_streaming_widget.stream_in("\n\n[Stream completed due to timeout]")
                
                self.current_streaming_widget.end_stream()
                self.last_finalized_content = self.current_streaming_widget.content
                self.current_streaming_widget = None
                self._scroll_to_bottom()
                
        except asyncio.CancelledError:
            # Normal cancellation when stream completes
            pass
        except Exception as e:
            self.debug_messages.append(f"Stream timeout monitor error: {e}")
    
    async def _force_stream_recovery(self) -> None:
        """Manually force recovery of a stuck stream."""
        if self.current_streaming_widget:
            self.debug_messages.append("Manual stream recovery triggered")
            
            # Cancel timeout task if running
            if self._stream_timeout_task:
                self._stream_timeout_task.cancel()
                self._stream_timeout_task = None
            
            # Check if content looks incomplete
            current_content = self.current_streaming_widget.content.strip()
            if self._detect_incomplete_response(current_content):
                self.current_streaming_widget.stream_in("\n\n[Stream manually recovered - response may be incomplete]")
            else:
                self.current_streaming_widget.stream_in("\n\n[Stream manually recovered]")
            
            self.current_streaming_widget.end_stream()
            self.last_finalized_content = self.current_streaming_widget.content
            self.current_streaming_widget = None
            self._scroll_to_bottom()
            
            self.add_message("Stream recovery completed. You can continue the conversation.", "system")
        else:
            self.add_message("No active stream to recover.", "system")
    
    async def _clear_dedup_content(self) -> None:
        """Clear the deduplication key after a delay."""
        await asyncio.sleep(0.5)
        self.last_finalized_content = None

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        if not self.interface:
            self.add_message("Core not initialized yet. Please wait.", "error")
            return
        
        user_input = event.value.strip()
        if not user_input:
            return
        
        event.input.value = ""
        
        # Check if user typed a number to select a conversation
        if hasattr(self, '_conversation_list') and self._conversation_list and user_input.isdigit():
            conv_num = int(user_input)
            if 1 <= conv_num <= len(self._conversation_list):
                selected_conv = self._conversation_list[conv_num - 1]
                # Display selection message
                self.add_message(f"Loading conversation: {selected_conv.title}", "user")
                # Load the conversation
                await self._handle_command(f"chat load {selected_conv.session_id}")
                # Clear the conversation list to prevent accidental selections
                self._conversation_list = None
                return
            else:
                self.add_message(f"Invalid selection. Please choose a number between 1 and {len(self._conversation_list)}", "error")
                return
        
        # Display user message immediately for better UX
        self.add_message(user_input, "user")

        if user_input.startswith("/"):
            # Clear conversation list when executing other commands
            self._conversation_list = None
            # Handle commands with enhanced support
            await self._handle_command(user_input[1:])
            return

        try:
            # Clear conversation list when sending regular messages
            self._conversation_list = None
            self.status_text = "Penguin is thinking..."
            # Core processing is now event-driven, we just kick it off
            await self.interface.process_input({'text': user_input})
            self.status_text = "Ready"
        except Exception as e:
            self.status_text = "Error"
            error_msg = f"Error processing input: {e}"
            logger.error(error_msg, exc_info=True)
            self.add_message(error_msg, "error")

    def action_clear_log(self) -> None:
        """Clear the chat log."""
        message_area = self.query_one("#message-area", VerticalScroll)
        message_area.remove_children()
        self.add_message("Chat cleared.", "system")

    def action_show_debug(self) -> None:
        """Show debug information."""
        if not self.debug_messages:
            content = "No debug messages."
        else:
            content = "## Debug Log (last 20)\n\n" + "\n".join(f"- {msg}" for msg in self.debug_messages[-20:])
        self.add_message(content, "debug")

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands with enhanced support."""
        try:
            # Parse command and arguments
            parts = command.split(" ", 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            
            # Handle built-in TUI commands first
            if cmd == "help":
                await self._show_enhanced_help()
                return
            elif cmd == "clear":
                self.action_clear_log()
                return
            elif cmd == "quit" or cmd == "exit":
                self.action_quit()
                return
            elif cmd == "debug":
                if args:
                    # Handle debug subcommands
                    response = await self.interface.handle_command(command)
                    await self._display_command_response(response)
                else:
                    self.action_show_debug()
                return
            elif cmd == "recover":
                # Manual recovery for stuck streams
                await self._force_stream_recovery()
                return
            
            # For other commands, use the interface with enhanced callbacks
            if cmd == "run":
                # Enhanced run command with UI callbacks
                response = await self.interface.handle_command(
                    command, 
                    runmode_stream_cb=self._handle_runmode_stream,
                    runmode_ui_update_cb=self._handle_runmode_ui_update
                )
            else:
                # Regular command handling
                response = await self.interface.handle_command(command)
            
            # Display response
            await self._display_command_response(response)
            
        except Exception as e:
            error_msg = f"Error handling command /{command}: {e}"
            logger.error(error_msg, exc_info=True)
            self.add_message(error_msg, "error")
    
    async def _handle_runmode_stream(self, content: str) -> None:
        """Handle streaming content from RunMode."""
        try:
            # Add streaming content to a dedicated RunMode message
            if not hasattr(self, '_runmode_message') or self._runmode_message is None:
                self._runmode_message = self.add_message("", "system")
                self._runmode_message.add_class("runmode-output")
            
            self._runmode_message.stream_in(content)
            self._scroll_to_bottom()
        except Exception as e:
            logger.error(f"Error handling RunMode stream: {e}")
    
    async def _handle_runmode_ui_update(self) -> None:
        """Handle UI updates for RunMode status."""
        try:
            if self.interface:
                runmode_status = self.interface.get_runmode_status()
                self.status_text = runmode_status.get("summary", "RunMode active")
        except Exception as e:
            logger.error(f"Error updating RunMode UI: {e}")
    
    async def _display_command_response(self, response: Dict[str, Any]) -> None:
        """Display the response from a command."""
        if response.get("status"):
            self.add_message(response["status"], "system")
        
        if response.get("error"):
            self.add_message(response["error"], "error")
        
        # Handle structured responses (like /list, /tokens, etc.)
        if "conversations" in response:
            await self._display_conversations(response["conversations"])
        
        if "projects" in response or "tasks" in response:
            await self._display_projects_and_tasks(response)
        
        if "token_usage" in response:
            await self._display_token_usage(response["token_usage"])
    
    async def _display_conversations(self, conversations):
        """Display conversation list in a formatted way with numbered selection."""
        if not conversations:
            self.add_message("No conversations found.", "system")
            return
        
        # Store conversations for selection
        self._conversation_list = conversations
        
        content = "**Available Conversations:**\n\n"
        for i, conv in enumerate(conversations, 1):
            content += f"**{i}.** **{conv.title}** ({conv.session_id[:8]}...)\n"
            content += f"    {conv.message_count} messages, last active: {conv.last_active}\n\n"
        
        content += "💡 **To load a conversation:** Type the number (e.g., `1`, `2`, `3`) or `/chat load <session_id>`"
        
        self.add_message(content, "system")
    
    async def _display_projects_and_tasks(self, data):
        """Display projects and tasks in a formatted way."""
        content = "**Projects & Tasks:**\n\n"
        
        if "summary" in data:
            summary = data["summary"]
            content += f"**Summary:** {summary['total_projects']} projects, {summary['total_tasks']} tasks ({summary['active_tasks']} active)\n\n"
        
        if "projects" in data:
            content += "**Projects:**\n"
            for project in data["projects"]:
                content += f"- **{project['name']}** ({project['status']}) - {project['task_count']} tasks\n"
            content += "\n"
        
        if "tasks" in data:
            content += "**Tasks:**\n"
            for task in data["tasks"]:
                content += f"- **{task['title']}** ({task['status']}) - Priority {task['priority']}\n"
        
        self.add_message(content, "system")
    
    async def _display_token_usage(self, usage):
        """Display token usage in a formatted way."""
        current = usage.get("current_total_tokens", 0)
        max_tokens = usage.get("max_tokens", 0)
        percentage = usage.get("percentage", 0)
        
        content = f"**Token Usage:** {current:,} / {max_tokens:,} ({percentage:.1f}%)\n\n"
        
        if "categories" in usage:
            content += "**By Category:**\n"
            for category, count in usage["categories"].items():
                if count > 0:
                    content += f"- {category}: {count:,}\n"
        
        self.add_message(content, "system")
    
    async def _show_enhanced_help(self) -> None:
        """Display enhanced help message with all available commands."""
        help_text = """
**Available Commands:**
*Use Tab key for autocomplete on any command*

**Chat & Navigation:**
- `/help` - Show this help message
- `/clear` - Clear the chat history  
- `/quit` or `/exit` - Exit the application

**RunMode & Tasks:**
- `/run continuous [task]` - Start continuous RunMode
- `/run task [name] [description]` - Run a specific task
- `/run stop` - Stop current RunMode execution
- `/task create "name" "description"` - Create a new task
- `/project create "name" "description"` - Create a new project
- `/list` - Show all projects and tasks

**Model & Configuration:**
- `/models` - Interactive model selection
- `/model set <id>` - Set specific model
- `/stream [on|off]` - Toggle streaming mode
- `/tokens [reset|detail]` - Show or manage token usage

**Conversations & Context:**
- `/chat list` - List available conversations
- `/chat load <id>` - Load a conversation
- `/context list` - List context files
- `/context load <file>` - Load context file

**Debug & Development:**
- `/debug [tokens|stream|sample]` - Debug functions
- `/recover` - Force recovery of stuck streams
        """
        self.add_message(help_text, "system")

    async def show_help(self) -> None:
        """Display the structured help message."""
        await self._show_enhanced_help()

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

    async def on_status_message(self, event: StatusMessage) -> None:  # Textual auto dispatch
        bar = self.query_one("#status-bar", Static)
        bar.update(event.text)
        await asyncio.sleep(1.5)
        bar.update("")

class TUI:
    """Entry point for the Textual UI."""
    
    @staticmethod
    def run():
        """Run the Textual application."""
        os.environ['PENGUIN_TUI_MODE'] = '1'
        app = PenguinTextualApp()
        try:
            app.run()
        finally:
            os.environ.pop('PENGUIN_TUI_MODE', None)
            # Dump debug messages for post-session troubleshooting
            if hasattr(app, 'debug_messages') and app.debug_messages:
                print("\n" + "="*60)
                print("PENGUIN TUI DEBUG LOG")
                print("="*60)
                for i, msg in enumerate(app.debug_messages, 1):
                    print(f"{i:4d}. {msg}")
                print("="*60)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, filename="tui_debug.log")
    TUI.run() 