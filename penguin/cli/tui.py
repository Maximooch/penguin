from __future__ import annotations
import asyncio
import logging
import traceback
from typing import Any, Dict, Optional, List

# Textual imports
from textual.app import App, ComposeResult # type: ignore
from textual.containers import Container, VerticalScroll # type: ignore
from textual.reactive import reactive # type: ignore

# Header / Footer / Input etc. are always present. Expander was introduced in
# Textual 0.8x – older installs may not export it which raises an ImportError
# during dynamic attribute lookup. We therefore attempt the import lazily and
# fall back to a sentinel so the rest of the code can degrade gracefully.

# Standard Textual widgets always present
from textual.widgets import Header, Footer, Input, Static, Markdown as TextualMarkdown, Collapsible, Button # type: ignore
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
import json
import signal
import shlex
import re
import time
import shutil

# Project imports
from penguin.core import PenguinCore
from penguin.cli.interface import PenguinInterface
from penguin.cli.widgets import ToolExecutionWidget, StreamingStateMachine, StreamState
from penguin.cli.widgets.unified_display import UnifiedExecution, ExecutionAdapter, ExecutionStatus
from penguin.cli.command_registry import CommandRegistry


class StatusSidebar(Static):
    """Right-docked status sidebar with compact metrics."""

    def __init__(self) -> None:
        super().__init__(id="status-sidebar")
        self._last = {}

    def update_status(self, data: Dict[str, Any]) -> None:
        try:
            # Allow callers to bypass formatting and set raw text
            if data.get("raw"):
                self.update(str(data["raw"]))
                return
            model = data.get("model", "model?")
            cur = data.get("tokens_cur", 0)
            max_t = data.get("tokens_max", 0)
            pct = (cur / max_t * 100) if max_t else 0
            elapsed = data.get("elapsed", 0)
            lines = [
                f"[bold]{model}[/bold]",
                f"tokens: {cur}/{max_t} ({pct:.1f}%)",
                f"⏱ {elapsed:>4}s",
            ]
            self.update("\n".join(lines))
        except Exception:
            pass

class CommandSuggester(Suggester):
    """Provides autocompletion for slash commands using CommandRegistry."""

    def __init__(self, registry: "CommandRegistry"):
        super().__init__()
        self.registry = registry

    async def get_suggestion(self, value: str) -> str | None:
        if not value or not value.startswith("/"):
            return None
        try:
            suggestions = self.registry.get_suggestions(value)
            return suggestions[0] if suggestions else None
        except Exception:
            return None

# Set up logging for debug purposes (file + quiet console)
logger = logging.getLogger(__name__)
if not logger.handlers:
    logger.setLevel(logging.INFO)
    try:
        log_path = os.path.join(os.path.dirname(__file__), "tui_debug.log")
        fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setLevel(logging.WARNING)
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(ch)
    except Exception:
        pass

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
        self._md_cached = None
        self._md_stream = None
        self._pending_update_task = None
        self._last_update_ts = 0.0
        self._prefixed = False
        
        # PERFORMANCE: Chunk buffering for markdown optimization
        self._chunk_buffer: List[str] = []
        self._buffer_size_limit = 500  # Characters before forcing update
        self._last_buffer_flush = 0.0
        self._headline: Optional[str] = None

    def compose(self) -> ComposeResult:
        """Render the message with code fences highlighted."""

        # Streaming path: keep a single Markdown widget and append to it
        # to avoid partial / unparsed markdown during progressive updates.
        try:
            if self.has_class("streaming"):
                text = self._clean_final_content(self.content)
                try:
                    if self.role == "assistant" and getattr(self.app, "_view_mode", "compact") == "compact" and not self._prefixed:
                        text = ("🐧 " + text) if not text.startswith("🐧 ") else text
                        self._prefixed = True
                except Exception:
                    pass
                yield TextualMarkdown(text, classes=f"message-content {self.role}")
                return
        except Exception:
            pass

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
        # Accept optional attributes on <details>, e.g. <details open>
        DETAILS_RE = re.compile(r"<details(\s+[^>]*)?>\s*(<summary>(.*?)</summary>)?(.*?)</details>", re.S)

        pos = 0
        for m in DETAILS_RE.finditer(processed_content):
            before = processed_content[pos:m.start()]
            if before.strip():
                # Trim trailing blanks and apply message-content classes to avoid extra spacing
                yield TextualMarkdown(
                    self._clean_final_content(before),
                    classes=f"message-content {self.role}"
                )

            attrs = m.group(1) or ""
            summary_text = m.group(3) or "Details"
            body_md = m.group(4).strip()
            is_open = "open" in attrs if isinstance(attrs, str) else False

            if Expander is not None:
                # Preferred rich interactive widget when available.
                expander = Expander(summary_text, open=bool(is_open))  # type: ignore[call-arg]
                expander.mount(TextualMarkdown(body_md))
                yield expander
            else:
                # Older Textual – use our minimal interactive fallback.
                yield SimpleExpander(summary_text, body_md, open=bool(is_open))

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
                yield TextualMarkdown(
                    self._clean_final_content(processed_content),
                    classes=f"message-content {self.role}"
                )
            return

        # Compact headline for assistant messages (one-liner, toggles density)
        try:
            if self.role == "assistant" and getattr(self.app, "_view_mode", "compact") == "compact":
                summary = self._compute_headline(self.content)
                # Small clickable header widget that toggles density for this message
                class _HL(Static):
                    can_focus = True
                    def on_click(self) -> None:  # type: ignore[override]
                        try:
                            self.parent.action_toggle_density()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    BINDINGS = [("enter", "toggle", "Toggle"), ("space", "toggle", "Toggle")]
                    def action_toggle(self) -> None:
                        self.on_click()
                yield _HL(Text(summary, style="bold cyan"), classes="msg-head")
        except Exception:
            pass

        # Compact mode: prefix penguin emoji for assistant messages
        try:
            if self.role == "assistant" and getattr(self.app, "_view_mode", "compact") == "compact" and not processed_content.startswith("🐧 "):
                processed_content = f"🐧 {processed_content}"
        except Exception:
            pass

        parts = self.CODE_FENCE.split(processed_content)
        # parts = [before, lang1, code1, after1, lang2, code2, ...]
        if len(parts) == 1:
            # No fenced code detected – heuristic: treat whole block as code if it *looks* like code
            if self._looks_like_code(processed_content):
                # Line numbers only in detailed view
                line_nums = self._is_detailed()
                syntax_obj = Syntax(processed_content.strip(), "python", theme="monokai", line_numbers=line_nums)
                yield Static(syntax_obj, classes="code-block")
            else:
                yield TextualMarkdown(
                    self._clean_final_content(processed_content),
                    classes=f"message-content {self.role}"
                )
            return

        for idx, chunk in enumerate(parts):
            mod = idx % 3
            if mod == 0:
                # narrative segment
                if chunk.strip():
                    yield TextualMarkdown(
                        self._clean_final_content(chunk),
                        classes=f"message-content {self.role}"
                    )
            elif mod == 1:
                # language identifier (may be empty)
                lang = chunk.strip() or "python"  # Default to python if no language specified
                if idx + 1 < len(parts):
                    code = parts[idx + 1]
                    # Clean up the code a bit
                    code = code.strip()
                    if code:
                        try:
                            # Compact view hides line numbers for a cleaner look
                            line_nums = self._is_detailed()
                            # Smarter fencing: try explicit lang, fall back to python → text
                            # Map custom languages
                            actual_lang = (lang or "python").lower()
                            if actual_lang == "actionxml":
                                actual_lang = "xml"

                            # Auto-collapse ActionTag/tool blocks in compact view (except diffs)
                            preview_lines = getattr(self.app, "_tools_preview_lines", 5)
                            should_autocollapse = (
                                getattr(self.app, "_view_mode", "compact") == "compact"
                                and getattr(self.app, "_tools_compact", True)
                                and (lang.lower() == "actionxml" or "<tool" in code or "<execute" in code)
                                and lang.lower() != "diff"
                            )
                            if should_autocollapse:
                                lines = code.splitlines()
                                if len(lines) > preview_lines:
                                    head = "\n".join(lines[:preview_lines])
                                    try:
                                        preview_syntax = Syntax(head, actual_lang, theme="monokai", line_numbers=line_nums)
                                    except Exception:
                                        preview_syntax = Syntax(head, "text", theme="monokai", line_numbers=line_nums)
                                    yield Static(preview_syntax, classes="code-block")
                                    remainder = "\n".join(lines[preview_lines:])
                                    summary = f"Show {len(lines) - preview_lines} more lines…"
                                    body_md = f"```{lang}\n{remainder}\n```"
                                    if Expander is not None:
                                        expander = Expander(summary, open=False)  # type: ignore[call-arg]
                                        expander.mount(TextualMarkdown(body_md))
                                        yield expander
                                    else:
                                        yield SimpleExpander(summary, body_md, open=False)
                                    continue

                            try:
                                syntax_obj = Syntax(code, actual_lang, theme="monokai", line_numbers=line_nums)
                            except Exception:
                                syntax_obj = Syntax(code, "text", theme="monokai", line_numbers=line_nums)
                            yield Static(syntax_obj, classes="code-block")
                        except Exception as e:
                            # Fallback if syntax highlighting fails
                            logger.debug(f"Syntax highlighting failed: {e}")
                            yield TextualMarkdown(f"```{lang}\n{code}\n```")
            else:
                # code segment handled by mod==1
                continue

    def stream_in(self, chunk: str) -> None:
        """Append a chunk of text to the message content with buffering optimization."""
        # Clean up streaming artifacts before adding to content
        cleaned_chunk = self._clean_streaming_artifacts(chunk)
        
        # Emit penguin prefix once in compact mode before first chunk
        try:
            if self.role == "assistant" and getattr(self.app, "_view_mode", "compact") == "compact" and not self._prefixed:
                md = self._get_markdown_widget()
                if md is not None and hasattr(md, "get_stream"):
                    if self._md_stream is None:
                        try:
                            self._md_stream = md.get_stream()
                        except Exception:
                            self._md_stream = None
                    if self._md_stream is not None:
                        self._md_stream.write("🐧 ")
                self.content += "🐧 "
                self._prefixed = True
        except Exception:
            pass
        
        # Update content immediately for accuracy
        self.content += cleaned_chunk
        
        # PERFORMANCE FIX: Buffer chunks to reduce markdown processing frequency
        self._chunk_buffer.append(cleaned_chunk)
        current_buffer_size = sum(len(c) for c in self._chunk_buffer)
        current_time = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
        
        # Flush buffer if it's getting large OR enough time has passed
        should_flush = (
            current_buffer_size >= self._buffer_size_limit or
            (current_time - self._last_buffer_flush) >= 0.2  # 200ms minimum
        )
        
        if should_flush:
            self._flush_chunk_buffer()
        else:
            # Just schedule a throttled update without immediate processing
            self._schedule_markdown_update(min_interval=0.3)  # Increase interval during heavy streaming

    def _flush_chunk_buffer(self) -> None:
        """Flush buffered chunks to markdown widget for better performance."""
        if not self._chunk_buffer:
            return
            
        # Process accumulated chunks at once
        buffered_content = ''.join(self._chunk_buffer)
        self._chunk_buffer.clear()
        self._last_buffer_flush = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
        
        # Prefer Textual Markdown streaming API when available
        try:
            md = self._get_markdown_widget()
            if md is not None and hasattr(md, "get_stream"):
                if self._md_stream is None:
                    try:
                        self._md_stream = md.get_stream()  # type: ignore[attr-defined]
                    except Exception:
                        self._md_stream = None
                if self._md_stream is not None:
                    try:
                        self._md_stream.write(buffered_content)
                        return  # Streaming API handled it
                    except Exception:
                        self._md_stream = None
            
            # Fallback: schedule a regular markdown update
            self._schedule_markdown_update()
        except Exception:
            # If all else fails, schedule an update
            self._schedule_markdown_update()
    
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

    def _get_markdown_widget(self):
        if self._md_cached is not None:
            return self._md_cached
        try:
            self._md_cached = self.query_one(TextualMarkdown)
        except Exception:
            self._md_cached = None
        return self._md_cached

    def _schedule_markdown_update(self, min_interval: float = 0.18) -> None:
        try:
            loop = asyncio.get_event_loop()
            now = loop.time()
            
            # Cancel existing task if it's still pending
            if self._pending_update_task is not None and not self._pending_update_task.done():
                self._pending_update_task.cancel()
                self._pending_update_task = None
            
            if self._pending_update_task is None and (now - self._last_update_ts) >= min_interval:
                self._pending_update_task = loop.create_task(self._flush_markdown_update())
            elif self._pending_update_task is None:
                delay = max(0.0, min_interval - (now - self._last_update_ts))
                self._pending_update_task = loop.create_task(self._flush_markdown_update(delay))
        except Exception:
            # Don't let markdown scheduling issues crash the app
            pass

    async def _flush_markdown_update(self, delay: float = 0.0) -> None:
        try:
            if delay > 0.0:
                await asyncio.sleep(delay)
            md = self._get_markdown_widget()
            if md is not None:
                md.update(self.content)
            self._last_update_ts = asyncio.get_event_loop().time()
        except Exception:
            pass
        finally:
            self._pending_update_task = None
    
    def _clean_final_content(self, content: str) -> str:
        """Final cleanup of complete streamed content."""
        if not content:
            return content
            
        import re
        
        # Preserve <details> blocks as-is; the compose() method converts them to interactive widgets.
        
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
        
        # PERFORMANCE FIX: Flush any remaining buffered chunks before finalizing
        self._flush_chunk_buffer()
        
        # Cancel any pending markdown update tasks to prevent crashes
        if hasattr(self, '_pending_update_task') and self._pending_update_task is not None:
            if not self._pending_update_task.done():
                self._pending_update_task.cancel()
            self._pending_update_task = None
        
        # Final cleanup of the complete content
        self.content = self._clean_final_content(self.content)
        
        # Update the markdown widget with cleaned content
        try:
            if self._md_stream is not None:
                try:
                    self._md_stream.stop()
                except Exception:
                    pass
                finally:
                    self._md_stream = None
            md = self._get_markdown_widget()
            if md is not None:
                md.update(self.content)
        except Exception:
            pass

        # ---------------------------------------------
        # Post-processing: ensure reasoning is properly formatted
        # ---------------------------------------------
        # Note: With the new streaming approach, reasoning should already be 
        # properly formatted in <details> blocks during streaming, so we skip
        # most of the old post-processing logic to avoid interference.
        try:
            # Only do minimal cleanup if reasoning wasn't handled during streaming
            if "<details>" not in self.content and "> " in self.content:
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
                    # Build collapsible markdown block (fallback for non-streaming case)
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
        # Legacy heuristic fallback disabled for streaming approach
        # ------------------------------------------------------------------
        # The old heuristic approach has been replaced with real-time streaming
        # of reasoning tokens, so this fallback is no longer needed.
        # Finally, recompose contents so <details> blocks become interactive Expanders
        try:
            self._rebuild_contents()
        except Exception:
            pass

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
            # No traditional expander found, try to toggle reasoning via content manipulation
            self._toggle_reasoning_content()

    # --------- Helpers ---------
    def _is_detailed(self) -> bool:
        """Return True if this message should render in detailed density.

        Checks a per-message override first, then falls back to the app's
        global view mode. Safe on older Textual versions and during early mount.
        """
        try:
            override = getattr(self, "_override_detailed", None)
            if override is not None:
                return bool(override)
            app_mode = getattr(self.app, "_view_mode", "compact")
            return app_mode == "detailed"
        except Exception:
            return False

    def _is_compact(self) -> bool:
        try:
            return not self._is_detailed()
        except Exception:
            return True

    def _rebuild_contents(self) -> None:
        """Recompose children to apply density changes (e.g., line numbers)."""
        try:
            # Remove existing children and re-yield from compose()
            for ch in list(self.children):
                ch.remove()
            # Compose returns a generator; mount each produced widget
            for widget in self.compose():
                self.mount(widget)
        except Exception:
            # Fall back to forcing markdown update if present
            try:
                md = self.query_one(TextualMarkdown)
                md.update(self.content)
            except Exception:
                pass
    def _compute_headline(self, text: str) -> str:
        base = text.strip().splitlines()
        if not base:
            return "Penguin"
        first = base[0].strip()
        # Remove leading emoji/prefix
        if first.startswith("🐧 "):
            first = first[2:].strip()
        # Keep short
        if len(first) > 80:
            first = first[:77] + "…"
        return first or "Penguin"

    def action_toggle_density(self) -> None:
        try:
            app = getattr(self, 'app', None)
            if not app:
                return
            # Store per-message override flag on self
            current = getattr(self, '_override_detailed', None)
            if current is None:
                # If app is compact, expand just this message to detailed; else collapse
                app_compact = getattr(app, '_view_mode', 'compact') == 'compact'
                self._override_detailed = app_compact
            else:
                self._override_detailed = not current
            # Rebuild contents so Syntax blocks can pick up line-number changes
            self._rebuild_contents()
        except Exception:
            pass


    def _toggle_reasoning_content(self) -> None:
        """Toggle reasoning content visibility by modifying the content directly."""
        try:
            markdown_widget = self.query_one(TextualMarkdown)
            current_content = self.content
            
            import re
            
            # Check if we have a details block with reasoning
            if '<details>' in current_content and '</details>' in current_content:
                # Find and toggle the details block
                details_pattern = r'<details([^>]*)>\s*(<summary>.*?</summary>)\s*(.*?)</details>'
                
                def toggle_details(match):
                    attrs = match.group(1)
                    summary = match.group(2)
                    body = match.group(3).strip()
                    
                    # Check if it's a reasoning block
                    if '🧠' in summary:
                        # Toggle by adding/removing 'open' attribute
                        if 'open' not in attrs:
                            # Currently closed, open it
                            return f'<details open>\n{summary}\n\n{body}\n</details>'
                        else:
                            # Currently open, close it
                            return f'<details>\n{summary}\n\n{body}\n</details>'
                    return match.group(0)  # Return unchanged if not reasoning
                
                new_content = re.sub(details_pattern, toggle_details, current_content, flags=re.DOTALL)
                
                if new_content != current_content:
                    self.content = new_content
                    markdown_widget.update(self.content)
                    return
            
            # Fallback (non-destructive): if no <details>, do nothing to avoid content loss
            # We no longer try to rewrite blockquote reasoning, which was destructive.
                
        except Exception:
            # No reasoning content to toggle or error occurred
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

        # Pending image attachments (paths) captured from input path detection
        self._pending_attachments: list[str] = []

        # Status micro-row state
        self._latest_token_usage: Dict[str, Any] = {}
        self._app_start_ts: float = time.time()
        self._status_task: Optional[asyncio.Task] = None
        self._pending_response: bool = False
        self._spinner_index: int = 0
        self._status_visible: bool = True

        # Preferences (theme/layout) persisted across sessions
        self._prefs_path: str = os.path.expanduser("~/.penguin/tui_prefs.yml")
        self._theme_name: str = "ocean"  # ocean | nord | dracula
        self._layout_mode: str = "flat"   # flat | boxed
        self._view_mode: str = "compact"  # compact | detailed
        # Compact tool display controls
        self._tools_compact: bool = True
        self._tools_preview_lines: int = 10

        # Scrolling performance controls
        self._autoscroll: bool = True
        self._scroll_request_task: Optional[asyncio.Task] = None
        self._scroll_debounce_ms: int = 180  # ~5-8 FPS scroll updates
        self._stream_update_min_interval: float = 0.22
        self._linkify_on_finalization: bool = True
        self._message_area_ref: Optional[VerticalScroll] = None
        self._status_bar_ref: Optional[Static] = None
        self._trim_notice_added: bool = False
        self._older_messages_cache: list[dict] = []  # [{'role': str, 'content': str}]
        self._show_older_btn: Optional[Button] = None

        # Coalesced sidebar status
        self._last_status_payload: Optional[Dict[str, Any]] = None

    # -------------------------
    # Utilities
    # -------------------------
    def _prune_trailing_blank_messages(self, max_check: int = 5) -> None:
        """Remove up to max_check trailing ChatMessage widgets that are visually empty.

        A message is considered empty if its raw `content` is only whitespace
        (after stripping newlines), which avoids large blank areas between
        the tool card and the next message.
        """
        try:
            message_area = self.query_one("#message-area", VerticalScroll)
            # Work on a snapshot of children to avoid iterator invalidation
            children = list(message_area.children)
            removed = 0
            for w in reversed(children[-max_check:]):
                if isinstance(w, ChatMessage):
                    raw = getattr(w, "content", "")
                    if raw and raw.strip() == "":
                        w.remove()
                        removed += 1
                    elif not raw:
                        w.remove()
                        removed += 1
                    else:
                        break
            if removed:
                self.debug_messages.append(f"Pruned {removed} blank message(s)")
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        # Apply theme/layout classes before composing children
        self._load_prefs()
        self._apply_theme_class()
        self._apply_layout_class()
        yield Header()
        with Container(id="main-container"):
            with Container(id="center-pane"):
                yield VerticalScroll(id="message-area")
                yield Input(
                    placeholder="Type your message... (/help for commands, Tab for autocomplete)", 
                    id="input-box"
                )
            yield StatusSidebar()
        yield Static(id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """Called when the app is mounted."""
        try:
            self._status_bar_ref = self.query_one("#status-bar", Static)
            self._status_bar_ref.update(self.status_text)
            self._message_area_ref = self.query_one("#message-area", VerticalScroll)
            # Mount a Show Older loader button at the top of the message area
            try:
                self._show_older_btn = Button("Show older…", id="show-older")
                # Insert as the first child so older messages appear after it
                self._message_area_ref.mount(self._show_older_btn)
                # Hide if no cache present
                self._show_older_btn.display = False
            except Exception:
                pass
        except Exception:
            pass
        self.query_one(Input).focus()
        asyncio.create_task(self.initialize_core())
        # Start micro status updater
        self._status_task = asyncio.create_task(self._update_status_loop())

    def add_message(self, content: str, role: str) -> ChatMessage:
        """Helper to add a new message widget to the display."""
        # Trim excessive leading / trailing blank lines to avoid large visual gaps
        try:
            content = re.sub(r"^\n{2,}", "\n", content)
        except Exception:
            pass
        content = content.strip("\n")

        area = self._message_area_ref or self.query_one("#message-area", VerticalScroll)
        new_message = ChatMessage(content, role)
        # Append new messages at the end to keep chronological order (oldest at top, newest at bottom)
        area.mount(new_message)
        self._maybe_trim_messages(area)
        # Request a debounced scroll to bottom to avoid layout thrash
        self._request_scroll_to_bottom()
        return new_message

    def _scroll_to_bottom(self) -> None:
        """Scroll the message area to the bottom without animation."""
        try:
            area = self._message_area_ref or self.query_one("#message-area", VerticalScroll)
            area.scroll_end(animate=False)  # immediate jump
        except Exception:
            pass

    def _request_scroll_to_bottom(self) -> None:
        """Debounce scroll-to-bottom requests to reduce reflow during streaming."""
        try:
            # Respect autoscroll flag
            if not getattr(self, "_autoscroll", True):
                return
            loop = asyncio.get_event_loop()
            # Cancel any pending request
            if self._scroll_request_task and not self._scroll_request_task.done():
                self._scroll_request_task.cancel()
            # Schedule a new one
            async def _do_scroll_after_delay(delay_ms: int) -> None:
                try:
                    await asyncio.sleep(max(0.0, delay_ms / 1000.0))
                    self._scroll_to_bottom()
                except Exception:
                    pass
            self._scroll_request_task = loop.create_task(_do_scroll_after_delay(self._scroll_debounce_ms))
        except Exception:
            # Fallback to immediate scroll on error
            self._scroll_to_bottom()

    def _is_near_bottom(self, threshold_px: int = 32) -> bool:
        """Best-effort check if message area is near the bottom.

        Returns True on uncertainty to avoid surprising behavior.
        """
        try:
            message_area = self._message_area_ref or self.query_one("#message-area", VerticalScroll)
            virtual_size = getattr(message_area, "virtual_size", None)
            scroll_offset = getattr(message_area, "scroll_offset", None)
            size = getattr(message_area, "size", None)
            if virtual_size and scroll_offset and size:
                remaining = getattr(virtual_size, "height", 0) - (getattr(scroll_offset, "y", 0) + getattr(size, "height", 0))
                return remaining <= max(0, threshold_px)
        except Exception:
            pass
        return True
    
    def _format_system_output(self, action_name: str, result_str: str, max_lines: int = 20) -> str:
        """Format tool / action output.

        - Compact view: show fenced text. If longer than max_lines, include a
          preview and a <details> block with the remainder. No extra headers.
        - Detailed view: show full output with a small header line.
        """
        view = getattr(self, "_view_mode", "compact")
        compact_tools = getattr(self, "_tools_compact", True)
        if compact_tools:
            max_lines = getattr(self, "_tools_preview_lines", max_lines)
        lines = result_str.splitlines()

        if view != "compact" and not compact_tools:
            # Detailed: full output with best-effort language fence
            def _guess_lang(s: str) -> str | None:
                snippet = s.strip()[:400]
                if re.search(r"^\s*(from\s+\w+\s+import|import\s+\w+|def\s+\w+\(|class\s+\w+|if __name__ == '__main__')", snippet, re.M):
                    return "python"
                if snippet.startswith("{") or snippet.startswith("["):
                    return "json"
                return None
            lang = _guess_lang(result_str)
            fence = f"```{lang}\n" if lang else "```\n"
            return f"{fence}{result_str}\n```"

        # Compact:
        if len(lines) <= max_lines or not compact_tools:
            # Compact short block
            def _guess_lang(s: str) -> str | None:
                snippet = s.strip()[:400]
                if re.search(r"^\s*(from\s+\w+\s+import|import\s+\w+|def\s+\w+\(|class\s+\w+|if __name__ == '__main__')", snippet, re.M):
                    return "python"
                if snippet.startswith("{") or snippet.startswith("["):
                    return "json"
                return None
            lang = _guess_lang(result_str)
            fence = f"```{lang}\n" if lang else "```\n"
            return f"{fence}{result_str}\n```"

        preview = "\n".join(lines[:max_lines])
        remainder = "\n".join(lines[max_lines:])
        def _guess_lang(s: str) -> str | None:
            snippet = s.strip()[:400]
            # Custom ActionTag format
            if re.search(r"<(/)?(execute|execute_command|apply_diff|enhanced_\w+|tool|action)[^>]*>", snippet):
                return "actionxml"
            if re.search(r"^\s*(from\s+\w+\s+import|import\s+\w+|def\s+\w+\(|class\s+\w+|if __name__ == '__main__')", snippet, re.M):
                return "python"
            if re.search(r"\bfunction\s+\w+\s*\(|console\.log\(|=>\s*\w*\(", snippet):
                return "javascript"
            if snippet.startswith("{") or snippet.startswith("["):
                return "json"
            if re.search(r"^\s*#\!/?\w*sh", snippet) or re.search(r"\b(set -e|#!/bin/sh|#!/usr/bin/env bash)\b", snippet):
                return "sh"
            if re.search(r"^\[.*\]\s*$", snippet, re.M) and re.search(r"^\w+\s*=\s*", snippet, re.M):
                return "toml"
            if re.search(r"^(\+\+\+|---|@@) ", snippet, re.M):
                return "diff"
            return None
        lang = _guess_lang(result_str)
        fence = f"```{lang}\n" if lang else "```\n"
        content = f"{fence}{preview}\n```\n\n"
        content += "<details>\n"
        content += f"<summary>Show {len(lines) - max_lines} more lines…</summary>\n\n"
        fence_full = f"```{lang}\n" if lang else "```\n"
        content += f"{fence_full}{remainder}\n```\n\n"
        content += "</details>"
        return content

    async def initialize_core(self) -> None:
        """Initialize the PenguinCore and interface."""
        try:
            self.status_text = "Initializing Penguin Core..."
            # Print versions to help debug Textual-related layout issues
            try:
                import textual  # type: ignore
                import rich  # type: ignore
                logger.debug(f"Textual version: {getattr(textual, '__version__', 'unknown')}")
                logger.debug(f"Rich version: {getattr(rich, '__version__', 'unknown')}")
            except Exception:
                pass
            self.core = await PenguinCore.create(fast_startup=True, show_progress=False)
            
            self.status_text = "Setting up interface..."
            self.core.register_ui(self.handle_core_event)
            self.debug_messages.append("Registered UI event handler with core")
            
            self.interface = PenguinInterface(self.core)
            
            # Initialize command registry
            self.status_text = "Loading commands..."
            self.command_registry = CommandRegistry()
            # Attach registry-backed suggester
            try:
                input_widget = self.query_one(Input)
                input_widget.suggester = CommandSuggester(self.command_registry)
            except Exception:
                pass
            
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
                bar = self._status_bar_ref or self.query_one("#status-bar", Static)
                bar.update(f"[dim]{status}[/dim]")
        except Exception:
            pass

    async def _update_status_loop(self) -> None:
        while True:
            try:
                sidebar = self.query_one(StatusSidebar)
                # For now, keep the sidebar visible when explicitly enabled,
                # regardless of compact/detailed, to aid testing across terminals.
                visible = getattr(self, "_status_visible", True)
                sidebar.display = visible
                if visible:
                    # Pre-stream waiting animation (before first chunk arrives)
                    if getattr(self, "_pending_response", False) and self.current_streaming_widget is None:
                        frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
                        self._spinner_index = (self._spinner_index + 1) % len(frames)
                        spinner = frames[self._spinner_index]
                        payload = {"raw": f"{spinner} waiting for response..."}
                        if payload != getattr(self, "_last_status_payload", None):
                            sidebar.update_status(payload)
                            self._last_status_payload = payload
                        await asyncio.sleep(0.1)
                        continue
                    elapsed = int(asyncio.get_event_loop().time() - getattr(self, "_stream_start_time", 0)) if self.current_streaming_widget else int(time.time() - self._app_start_ts)
                    model = None
                    if self.core and getattr(self.core, "model_config", None):
                        model = getattr(self.core.model_config, "model", None)
                    tokens = self.interface.get_token_usage() if self.interface else {}
                    cur = tokens.get("current_total_tokens", 0)
                    max_t = tokens.get("max_tokens", 0)
                    payload = {"model": model or "model?", "tokens_cur": cur, "tokens_max": max_t, "elapsed": elapsed}
                    if payload != getattr(self, "_last_status_payload", None):
                        sidebar.update_status(payload)
                        self._last_status_payload = payload
            except Exception:
                # keep loop resilient
                pass
            await asyncio.sleep(1.0)

    async def _handle_status_show(self) -> None:
        self._status_visible = True
        self.add_message("Status sidebar shown.", "system")

    async def _handle_status_hide(self) -> None:
        self._status_visible = False
        self.add_message("Status sidebar hidden.", "system")

    async def _handle_status_toggle(self) -> None:
        self._status_visible = not getattr(self, "_status_visible", True)
        self.add_message(f"Status sidebar {'shown' if self._status_visible else 'hidden'}.", "system")

    async def handle_core_event(self, event_type: str, data: Any) -> None:
        """Handle events from PenguinCore with performance optimizations."""
        # PERFORMANCE FIX: Reduce logging overhead during heavy streaming
        if event_type == "stream_chunk":
            try:
                is_final = bool(data.get("is_final", False))
            except Exception:
                is_final = False
            # Only log every 100th chunk or final to reduce overhead
            if is_final or (getattr(self, "_stream_chunk_count", 0) % 100 == 0):
                logger.debug(f"TUI handle_core_event {event_type} chunk #{getattr(self, '_stream_chunk_count', 0)}")
        else:
            logger.debug(f"TUI handle_core_event {event_type}")
        
        # PERFORMANCE FIX: Reduce debug message overhead during streaming
        try:
            # Only keep last 50 debug messages to prevent memory bloat
            if len(self.debug_messages) > 50:
                self.debug_messages = self.debug_messages[-25:]  # Keep last 25
            
            # Simplified debug logging for stream chunks
            if event_type == "stream_chunk":
                # Don't add debug message for every chunk - too expensive
                pass  
            else:
                self.debug_messages.append(f"Event: {event_type} ({str(data)[:100]}...)" if len(str(data)) > 100 else f"Event: {event_type}")
            
            if event_type == "message":
                # A message event means Core has started working; if it's an assistant
                # reply and streaming hasn't begun yet, mark pending for spinner.
                try:
                    role_peek = data.get("role", "")
                    if role_peek == "assistant" and self.current_streaming_widget is None:
                        self._pending_response = True
                except Exception:
                    pass
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
                    # Avoid leading newlines that create visual gaps
                    content = content.lstrip("\n")
                    self.add_message(content, "system")
                else:
                    # Avoid leading newlines that create visual gaps
                    content = content.lstrip("\n")
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
                    self._pending_response = False  # stop spinner
                    
                    # Initialize reasoning content accumulator and tracking
                    self._reasoning_content = ""
                    self._reasoning_details_started = False
                    
                    # Start stream timeout monitor
                    self._stream_timeout_task = asyncio.create_task(self._monitor_stream_timeout())

                if self.current_streaming_widget and chunk:
                    self._stream_chunk_count += 1
                    
                    # PERFORMANCE FIX: Reduce time-checking overhead - only check every 50th chunk
                    if self._stream_chunk_count % 50 == 0:
                        current_time = asyncio.get_event_loop().time()
                        if hasattr(self, '_stream_start_time'):
                            stream_duration = current_time - self._stream_start_time
                            # Detect potential hang (no final chunk after reasonable time)
                            if stream_duration > 30 and not is_final:
                                self.debug_messages.append(f"Long stream detected: {stream_duration:.1f}s, {self._stream_chunk_count} chunks")
                    
                    if not is_final:
                        # Handle different message types
                        if message_type == "reasoning":
                            # PERFORMANCE FIX: Only update sidebar every 5th reasoning chunk
                            if self._stream_chunk_count % 5 == 0:
                                try:
                                    sidebar = self.query_one(StatusSidebar)
                                    dots = ("…" * ((self._stream_chunk_count % 3) + 1))
                                    sidebar.update_status({"raw": f"🧠 reasoning{dots}"})
                                except Exception:
                                    pass  # Don't let sidebar issues stall streaming
                            
                            # Stream reasoning tokens in real-time with details block
                            self._reasoning_content += chunk
                            
                            # Create or update the reasoning details block
                            if not self._reasoning_details_started:
                                # Start the reasoning details block
                                reasoning_header = "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
                                self.current_streaming_widget.stream_in(reasoning_header)
                                self._reasoning_details_started = True
                            
                            # Stream the reasoning chunk directly inside the details block
                            # The blockquote formatting will be handled by the Textual markdown renderer
                            self.current_streaming_widget.stream_in(chunk)
                        else:
                            # Stream assistant content directly  
                            # If we were streaming reasoning, close the details block first
                            if self._reasoning_details_started and message_type != "reasoning":
                                self.current_streaming_widget.stream_in("\n\n</details>\n\n")
                                self._reasoning_details_started = False
                            
                            self.current_streaming_widget.stream_in(chunk)
                            # Keep the latest buffer for deduplication against upcoming message event
                            self.last_finalized_content = self.current_streaming_widget.content
                            # PERFORMANCE FIX: Reduce scroll frequency to improve performance
                            if (self._stream_chunk_count % 20) == 0:  # Increased from 10 to 20
                                self._request_scroll_to_bottom()
                
                if is_final and self.current_streaming_widget:
                    # Cancel timeout monitor
                    if self._stream_timeout_task:
                        self._stream_timeout_task.cancel()
                        self._stream_timeout_task = None
                    
                    # Finalize the message
                    stream_duration = asyncio.get_event_loop().time() - getattr(self, '_stream_start_time', 0)
                    self.debug_messages.append(f"Stream completed: {stream_duration:.1f}s, {self._stream_chunk_count} chunks")
                    
                    # Close reasoning details block if still open
                    if hasattr(self, '_reasoning_details_started') and self._reasoning_details_started:
                        self.current_streaming_widget.stream_in("\n\n</details>\n\n")
                        self._reasoning_details_started = False
                    
                    # Clear sidebar banner
                    try:
                        self.query_one(StatusSidebar).update_status({"raw": ""})
                    except Exception:
                        pass
                    
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
                    self._request_scroll_to_bottom()
                    self._pending_response = False

            elif event_type == "action":
                # Render action in XML-like tag form (compact look)
                action_name = data.get("type", "unknown")
                params = str(data.get("params", ""))
                md = f"```text\n<{action_name}>{params}</{action_name}>\n```"
                self.add_message(md, "system")

            elif event_type == "action_result":
                result_str = data.get("result", "")
                status = data.get("status", "completed")
                if status == "error":
                    self.add_message(f"```text\n{result_str}\n```", "system")
                else:
                    self.add_message(self._format_system_output("Action", result_str), "system")
                self._prune_trailing_blank_messages()

            elif event_type == "tool_call":
                tool_name = data.get("name", "unknown")
                tool_args = data.get("arguments", {})
                args_s = json.dumps(tool_args, indent=2, ensure_ascii=False) if isinstance(tool_args, (dict, list)) else str(tool_args)
                md = f"```text\n<tool name=\"{tool_name}\">\n{args_s}\n</tool>\n```"
                msg = self.add_message(md, "system")
                try:
                    msg.add_class("tool-call")
                except Exception:
                    pass
            
            elif event_type == "tool_result":
                result_str = data.get("result", "")
                action_name = data.get("action_name", "unknown")
                status = data.get("status", "completed")
                if status == "error":
                    msg = self.add_message(f"```text\n{result_str}\n```", "system")
                else:
                    msg = self.add_message(self._format_system_output(action_name, result_str), "system")
                try:
                    msg.add_class("tool-result")
                except Exception:
                    pass
                self._prune_trailing_blank_messages()

            elif event_type == "error":
                # Render errors as simple markdown instead of a widget in compact mode
                error_msg = data.get("message", "Unknown error")
                context = data.get("context", None)
                content = "**Error:**\n\n```text\n" + str(error_msg) + "\n" + (str(context) if context else "") + "\n```"
                self.add_message(content, "system")

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
                self._request_scroll_to_bottom()
                
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
            self._request_scroll_to_bottom()
            
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
        
        # First pass: detect and stage any image paths in the input
        user_input_raw = event.value
        user_input = self._detect_and_stage_attachments(user_input_raw).strip()
        if not user_input:
            # Allow sending only attachments (no text)
            if not self._pending_attachments:
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
        
        # Display user message immediately for better UX (show attachments chip)
        display_text = user_input
        if self._pending_attachments:
            chip = ", ".join(os.path.basename(p) for p in self._pending_attachments)
            display_text = (display_text + "\n" if display_text else "") + f"[attachments: {chip}]"
        if display_text:
            self.add_message(display_text, "user")

        if user_input.startswith("/"):
            # Clear conversation list when executing other commands
            self._conversation_list = None
            # Handle commands with enhanced support
            await self._handle_command(user_input[1:])
            return

        # Clear conversation list when sending regular messages
        self._conversation_list = None
        self.status_text = "Penguin is thinking..."
        # Build payload with optional image attachments
        payload: Dict[str, Any] = {'text': user_input}
        if self._pending_attachments:
            # Support multiple images by sending the first (current interface supports single image_path)
            # For now, send one-by-one; future: extend interface/core to accept a list
            first = self._pending_attachments[0]
            payload['image_path'] = first
            
        # CRITICAL FIX: Run processing in background to prevent TUI freeze
        # Don't await - let it run asynchronously so TUI stays responsive
        asyncio.create_task(self._process_input_background(payload))
        
        # Clear attachments after send
        self._pending_attachments.clear()

    async def _process_input_background(self, payload: Dict[str, Any]) -> None:
        """
        Process input in background to prevent TUI freeze.
        
        This method runs asynchronously without blocking the main TUI event loop,
        allowing users to interact with the interface (including cancellation)
        while the LLM processes their request.
        """
        try:
            # Process the input through interface
            await self.interface.process_input(payload)
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
            # Prefer registry-based routing when available
            if self.command_registry:
                cmd_obj, args_dict = self.command_registry.parse_input(command)
                if cmd_obj:
                    handler = cmd_obj.handler or ""
                    # TUI-local handlers
                    if handler in ("_show_enhanced_help", "action_clear_log", "action_quit", "action_show_debug", "_force_stream_recovery", "_handle_image", "_attachments_clear", "_handle_theme_list", "_handle_theme_set", "_handle_layout_set", "_handle_layout_get", "_handle_status_show", "_handle_status_hide", "_handle_status_toggle"):
                        if handler == "_show_enhanced_help":
                            await self._show_enhanced_help()
                        elif handler == "action_clear_log":
                            self.action_clear_log()
                        elif handler == "action_quit":
                            self.action_quit()
                        elif handler == "action_show_debug":
                            self.action_show_debug()
                        elif handler == "_force_stream_recovery":
                            await self._force_stream_recovery()
                        elif handler == "_handle_image":
                            await self._handle_image_command(args_dict)
                        elif handler == "_attachments_clear":
                            self._pending_attachments.clear()
                            self.add_message("Attachments cleared.", "system")
                        elif handler == "_handle_theme_list":
                            await self._handle_theme_list()
                        elif handler == "_handle_theme_set":
                            await self._handle_theme_set(args_dict)
                        elif handler == "_handle_layout_set":
                            await self._handle_layout_set(args_dict)
                        elif handler == "_handle_layout_get":
                            await self._handle_layout_get()
                        elif handler == "_handle_view_set":
                            await self._handle_view_set(args_dict)
                        elif handler == "_handle_view_get":
                            await self._handle_view_get()
                        elif handler == "_handle_status_show":
                            await self._handle_status_show()
                        elif handler == "_handle_status_hide":
                            await self._handle_status_hide()
                        elif handler == "_handle_status_toggle":
                            await self._handle_status_toggle()
                        return

                    # Otherwise, delegate to interface; rebuild command string
                    tokens: list[str] = []
                    if cmd_obj.parameters:
                        for p in cmd_obj.parameters:
                            if p.name in args_dict and args_dict[p.name] is not None:
                                val = str(args_dict[p.name])
                                if " " in val:
                                    val = f'"{val}"'
                                tokens.append(val)
                    built = cmd_obj.name + (" " + " ".join(tokens) if tokens else "")
                    if cmd_obj.name == "diff":
                        await self._handle_diff(args_dict)
                        return
                    if cmd_obj.name == "tools compact on":
                        self._tools_compact = True
                        self.add_message("Tool outputs: compact ON", "system")
                        return
                    if cmd_obj.name == "tools compact off":
                        self._tools_compact = False
                        self.add_message("Tool outputs: compact OFF", "system")
                        return
                    if cmd_obj.name == "tools preview":
                        try:
                            n = int(str(args_dict.get("lines", "20")))
                            self._tools_preview_lines = max(5, min(200, n))
                            self.add_message(f"Tool preview lines set to {self._tools_preview_lines}.", "system")
                        except Exception:
                            self.add_message("Usage: /tools preview <lines>", "error")
                        return
                    if cmd_obj.name.startswith("run ") or cmd_obj.name == "run":
                        response = await self.interface.handle_command(
                            built,
                            runmode_stream_cb=self._handle_runmode_stream,
                            runmode_ui_update_cb=self._handle_runmode_ui_update,
                        )
                    else:
                        response = await self.interface.handle_command(built)
                    await self._display_command_response(response)
                    return

            # Fallback to legacy path
            parts = command.split(" ", 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            # Fallback handling for view commands to avoid registry issues
            if cmd == "view":
                sub = args.split(" ", 1)[0] if args else "get"
                if sub == "set":
                    mode = args.split(" ", 1)[1] if " " in args else ""
                    await self._handle_view_set({"mode": mode})
                    return
                else:
                    await self._handle_view_get()
                    return
            if cmd == "help":
                await self._show_enhanced_help()
                return
            if cmd == "clear":
                self.action_clear_log()
                return
            if cmd in ("quit", "exit"):
                self.action_quit()
                return
            if cmd == "debug":
                if args:
                    # Inline runtime tuning fast-path: /debug throttle <ms>, /debug scroll <ms>, /debug linkify on|off
                    tokens = args.split()
                    if tokens and tokens[0] in ("throttle", "scroll", "linkify"):
                        payload: Dict[str, Any] = {"action": tokens[0]}
                        if tokens[0] == "linkify" and len(tokens) > 1:
                            payload["value"] = tokens[1]
                        if tokens[0] in ("throttle", "scroll") and len(tokens) > 1:
                            payload["ms"] = tokens[1]
                        await self._handle_debug_tuning(payload)
                        return
                    response = await self.interface.handle_command(command)
                    await self._display_command_response(response)
                else:
                    self.action_show_debug()
                return
            if cmd == "recover":
                await self._force_stream_recovery()
                return
            if cmd == "run":
                response = await self.interface.handle_command(
                    command,
                    runmode_stream_cb=self._handle_runmode_stream,
                    runmode_ui_update_cb=self._handle_runmode_ui_update,
                )
            else:
                response = await self.interface.handle_command(command)
            await self._display_command_response(response)
        except Exception as e:
            error_msg = f"Error handling command /{command}: {e}"
            logger.error(error_msg, exc_info=True)
            self.add_message(error_msg, "error")

    async def _handle_image_command(self, args: Dict[str, Any]) -> None:
        """Handle /image path [description] with drag-and-drop support."""
        try:
            image_path = str(args.get("path", "")).strip().strip("'\"")
            description = str(args.get("description", "")).strip()

            # If path is missing, prompt the user via a simple input
            if not image_path:
                # Allow drag-and-drop into terminal-like prompt
                self.add_message("Drag and drop an image path, then press Enter:", "system")
                return

            if not os.path.exists(image_path):
                self.add_message(f"Image file not found: {image_path}", "error")
                return

            if not description:
                description = ""

            # Send through interface like CLI does, relying on core to process image
            if self.interface:
                await self.interface.process_input({"text": description, "image_path": image_path})
                self.add_message(f"Image sent: {os.path.basename(image_path)}", "system")
        except Exception as e:
            self.add_message(f"Error handling image: {e}", "error")

    async def _handle_diff(self, args: Dict[str, Any]) -> None:
        """Handle /diff a b using difftastic if available, else git diff or diff.
        Renders the stdout as a fenced text block (auto-collapsed in compact mode).
        """
        try:
            a = str(args.get("a", "")).strip()
            b = str(args.get("b", "")).strip()
            if not a or not b:
                self.add_message("Usage: /diff <a> <b>", "error")
                return
            # Determine available tool
            tool = None
            for candidate in ("difft", "difftastic", "git", "diff"):
                if shutil.which(candidate):
                    tool = candidate
                    break
            if tool is None:
                self.add_message("No diff tool found (tried: difft/difftastic/git/diff)", "error")
                return
            # Build command
            if tool in ("difft", "difftastic"):
                cmd = [tool, "--background=dark", a, b]
            elif tool == "git":
                cmd = ["git", "--no-pager", "diff", "--", a, b]
            else:
                cmd = ["diff", "-u", a, b]
            # Run non-interactively
            import subprocess
            try:
                out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            except subprocess.CalledProcessError as e:
                out = e.output or "(no output)"
            # Format and display
            view = getattr(self, "_view_mode", "compact")
            fenced = f"```text\n{out}\n```"
            if view == "compact" and out.count("\n") > 60:
                head = "\n".join(out.splitlines()[:40])
                tail = "\n".join(out.splitlines()[-20:])
                body = f"```text\n{head}\n...\n{tail}\n```\n\n<details>\n<summary>Show full diff…</summary>\n\n```text\n{out}\n```\n\n</details>"
                self.add_message(body, "system")
            else:
                self.add_message(fenced, "system")
        except Exception as e:
            self.add_message(f"Diff error: {e}", "error")

    def _detect_and_stage_attachments(self, text: str) -> str:
        """Detect file paths for images in input text and stage them as attachments.
        Returns text with paths removed when staged successfully.
        """
        if not text:
            return text
        # Accept common image extensions
        valid_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        tokens = text.split()
        kept_tokens: list[str] = []
        staged: list[str] = []
        for tok in tokens:
            # Strip quotes
            cleaned = tok.strip('"\'')
            _, ext = os.path.splitext(cleaned)
            if ext.lower() in valid_ext and os.path.exists(cleaned):
                staged.append(cleaned)
            else:
                kept_tokens.append(tok)
        if staged:
            self._pending_attachments.extend(staged)
            self.add_message(f"Staged attachment(s): {', '.join(os.path.basename(p) for p in staged)}", "system")
            return " ".join(kept_tokens)
        return text
    
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
        
        # Optional detailed token usage
        if "token_usage_detailed" in response:
            await self._display_token_usage(response["token_usage_detailed"])
    
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
        try:
            if self.command_registry:
                help_md = self.command_registry.get_help_text()
                self.add_message(help_md, "system")
                return
        except Exception:
            pass
        self.add_message("Type /help for available commands. Use Tab for autocomplete.", "system")

    # ---------------------------
    # Debug runtime tuning hooks
    # ---------------------------
    async def _handle_debug_tuning(self, args: Dict[str, Any]) -> None:
        try:
            action = str(args.get("action", "")).strip().lower()
            if action == "throttle":
                try:
                    ms = float(str(args.get("ms", "")))
                    self._stream_update_min_interval = max(0.05, ms / 1000.0)
                    self.add_message(f"Stream throttle set to {self._stream_update_min_interval*1000:.0f}ms.", "system")
                except Exception:
                    self.add_message("Usage: /debug throttle <ms>", "error")
            elif action == "scroll":
                try:
                    ms = int(str(args.get("ms", "")))
                    self._scroll_debounce_ms = max(20, min(500, ms))
                    self.add_message(f"Scroll debounce set to {self._scroll_debounce_ms}ms.", "system")
                except Exception:
                    self.add_message("Usage: /debug scroll <ms>", "error")
            elif action == "linkify":
                val = str(args.get("value", "")).strip().lower()
                if val in ("on", "true", "1"):
                    self._linkify_on_finalization = True
                elif val in ("off", "false", "0"):
                    self._linkify_on_finalization = False
                else:
                    self.add_message("Usage: /debug linkify [on|off]", "error")
                    return
                self.add_message(f"Linkify on finalization set to {self._linkify_on_finalization}.", "system")
            else:
                self.add_message("Usage: /debug [throttle|scroll|linkify] ...", "system")
        except Exception as e:
            self.add_message(f"Debug tuning error: {e}", "error")

    # ---------------------------
    # Theme & Layout management
    # ---------------------------
    def _load_prefs(self) -> None:
        try:
            import yaml  # type: ignore
            if os.path.exists(self._prefs_path):
                with open(self._prefs_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                self._theme_name = str(data.get("theme", self._theme_name))
                self._layout_mode = str(data.get("layout", self._layout_mode))
                self._view_mode = str(data.get("view", self._view_mode))
        except Exception:
            pass

    def _save_prefs(self) -> None:
        try:
            import yaml  # type: ignore
            os.makedirs(os.path.dirname(self._prefs_path), exist_ok=True)
            with open(self._prefs_path, "w", encoding="utf-8") as f:
                yaml.safe_dump({"theme": self._theme_name, "layout": self._layout_mode, "view": self._view_mode}, f)
        except Exception:
            pass

    def _apply_theme_class(self) -> None:
        try:
            target = getattr(self, "screen", None) or self
            # Remove any prior theme classes
            for cls in ("theme-ocean", "theme-nord", "theme-dracula"):
                try:
                    target.remove_class(cls)  # type: ignore[attr-defined]
                except Exception:
                    pass
            # Map names
            name = self._theme_name.lower()
            if name in ("ocean", "deep-ocean", "default"):
                try:
                    target.add_class("theme-ocean")  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif name == "nord":
                try:
                    target.add_class("theme-nord")  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif name == "dracula":
                try:
                    target.add_class("theme-dracula")  # type: ignore[attr-defined]
                except Exception:
                    pass
            else:
                try:
                    target.add_class("theme-ocean")  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass

    def _apply_layout_class(self) -> None:
        try:
            target = getattr(self, "screen", None) or self
            for cls in ("layout-flat", "layout-boxed"):
                try:
                    target.remove_class(cls)  # type: ignore[attr-defined]
                except Exception:
                    pass
            if self._layout_mode.lower() == "boxed":
                try:
                    target.add_class("layout-boxed")  # type: ignore[attr-defined]
                except Exception:
                    pass
            else:
                try:
                    target.add_class("layout-flat")  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass

    async def _handle_theme_list(self) -> None:
        themes = ["ocean", "nord", "dracula"]
        msg = "**Available themes:**\n\n" + "\n".join(f"- {t}{' (current)' if t==self._theme_name else ''}" for t in themes)
        self.add_message(msg, "system")

    async def _handle_theme_set(self, args: Dict[str, Any]) -> None:
        name = str(args.get("theme_name", "")).strip().lower()
        if name not in ("ocean", "nord", "dracula", "deep-ocean", "default"):
            self.add_message(f"Unknown theme '{name}'. Try /theme list.", "error")
            return
        # Normalize
        self._theme_name = "ocean" if name in ("deep-ocean", "default") else name
        self._apply_theme_class()
        self._save_prefs()
        self.add_message(f"Theme set to {self._theme_name}.", "system")

    async def _handle_layout_set(self, args: Dict[str, Any]) -> None:
        mode = str(args.get("mode", "")).strip().lower()
        if mode not in ("flat", "boxed"):
            self.add_message("Unknown layout. Use 'flat' or 'boxed'.", "error")
            return
        self._layout_mode = mode
        self._apply_layout_class()
        self._save_prefs()
        self.add_message(f"Layout set to {mode}.", "system")

    async def _handle_layout_get(self) -> None:
        self.add_message(f"Current layout: {self._layout_mode}.", "system")

    async def _handle_view_set(self, args: Dict[str, Any]) -> None:
        mode = str(args.get("mode", "")).strip().lower()
        if mode not in ("compact", "detailed"):
            self.add_message("Unknown view. Use 'compact' or 'detailed'.", "error")
            return
        self._view_mode = mode
        self._save_prefs()
        self.add_message(f"View set to {mode}.", "system")

    async def _handle_view_get(self) -> None:
        self.add_message(f"Current view: {self._view_mode}.", "system")

    async def show_help(self) -> None:
        """Display the structured help message."""
        await self._show_enhanced_help()

    def action_quit(self) -> None:
        """Quit the application."""
        self.exit()

    async def on_status_message(self, event: StatusMessage) -> None:  # Textual auto dispatch
        bar = self._status_bar_ref or self.query_one("#status-bar", Static)
        bar.update(event.text)
        await asyncio.sleep(1.5)
        bar.update("")

    # -------------------------
    # Helpers: trim old messages
    # -------------------------
    def _maybe_trim_messages(self, area: Optional[VerticalScroll] = None, keep_last: int = 300) -> None:
        try:
            area_ref = area or self._message_area_ref or self.query_one("#message-area", VerticalScroll)
            msgs = [w for w in area_ref.children if isinstance(w, ChatMessage)]
            if len(msgs) > keep_last:
                excess = len(msgs) - keep_last
                for w in msgs[:excess]:
                    try:
                        # Cache removed content for on-demand load
                        self._older_messages_cache.append({
                            "role": getattr(w, "role", "assistant"),
                            "content": getattr(w, "content", ""),
                        })
                    except Exception:
                        pass
                    w.remove()
                # Reveal loader if older messages exist
                if self._show_older_btn:
                    self._show_older_btn.display = len(self._older_messages_cache) > 0
                if not self._trim_notice_added:
                    area_ref.mount(Static("[dim]Older messages trimmed to keep UI responsive.[/dim]"))
                    self._trim_notice_added = True
        except Exception:
            pass

    # -------------------------
    # Load older messages on demand
    # -------------------------
    def _load_older_messages(self, batch: int = 50) -> None:
        try:
            if not self._older_messages_cache:
                if self._show_older_btn:
                    self._show_older_btn.display = False
                return
            area = self._message_area_ref or self.query_one("#message-area", VerticalScroll)
            btn = self._show_older_btn
            # Take the last N (oldest-first preserved below)
            n = max(1, min(batch, len(self._older_messages_cache)))
            slice_items = self._older_messages_cache[-n:]
            # Remove from cache
            del self._older_messages_cache[-n:]
            # Mount in chronological order after the loader button
            for msg in slice_items:
                cm = ChatMessage(str(msg.get("content", "")), str(msg.get("role", "assistant")))
                if btn and btn in area.children:
                    area.mount(cm, after=btn)
                else:
                    area.mount(cm)
            # Hide the loader if cache is empty
            if self._show_older_btn:
                self._show_older_btn.display = len(self._older_messages_cache) > 0
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:  # type: ignore[override]
        try:
            if event.button.id == "show-older":
                self._load_older_messages(batch=50)
        except Exception:
            pass

class TUI:
    """Entry point for the Textual UI."""
    
    @staticmethod
    def run():
        """Run the Textual application."""
        os.environ['PENGUIN_TUI_MODE'] = '1'
        # Configure root logging to file, keep console quiet to avoid TUI flicker
        try:
            root = logging.getLogger()
            # Remove existing handlers to avoid duplicate writes
            for h in list(root.handlers):
                root.removeHandler(h)
            root.setLevel(logging.INFO)
            log_path = os.path.join(os.path.dirname(__file__), "tui_debug.log")
            fhd = logging.FileHandler(log_path, mode="a", encoding="utf-8")
            fhd.setLevel(logging.DEBUG)
            fhd.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            root.addHandler(fhd)
            # Console handler only for errors to keep terminal clean
            chd = logging.StreamHandler()
            chd.setLevel(logging.ERROR)
            chd.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
            root.addHandler(chd)
            # Silence noisy third-party loggers
            for noisy in ("httpx", "urllib3", "openai", "litellm", "penguin.llm.openrouter_gateway"):
                try:
                    logging.getLogger(noisy).setLevel(logging.ERROR)
                except Exception:
                    pass
        except Exception:
            pass
        # Best-effort: ensure CSS resource exists; if missing, disable CSS to avoid crash
        try:
            # Allow override via env to disable CSS on problematic terminals
            if os.environ.get('PENGUIN_TUI_NO_CSS') == '1' or os.environ.get('PENGUIN_TUI_DISABLE_CSS') == '1':
                PenguinTextualApp.CSS_PATH = None
            
            try:
                from importlib import resources as _res  # py3.9+
                has_css = False
                try:
                    # Deprecated in 3.11 but still available; robust across versions
                    has_css = _res.is_resource('penguin.cli', 'tui.css')  # type: ignore[attr-defined]
                except Exception:
                    # Fallback: attempt to read the resource
                    with _res.open_text('penguin.cli', 'tui.css') as _f:  # type: ignore[attr-defined]
                        has_css = bool(_f.read(1) or True)
                if not has_css:
                    PenguinTextualApp.CSS_PATH = None  # Disable external CSS load
            except Exception:
                # If importlib.resources isn't available or any error occurs, keep defaults
                pass
        except Exception:
            pass
        app = PenguinTextualApp()
        try:
            # Run without DevTools to keep the UI clean
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
    # Configure both console + rolling file logs (debug_log_<n>.txt)
    # import os as _os
    # import time as _time

    # def _next_log_filename(prefix: str = "debug_log_", ext: str = ".txt", directory: str = ".") -> str:
    #     for i in range(1, 1000):
    #         candidate = _os.path.join(directory, f"{prefix}{i}{ext}")
    #         if not _os.path.exists(candidate):
    #             return candidate
    #     # Fallback to timestamp if too many files
    #     return _os.path.join(directory, f"{prefix}{int(_time.time())}{ext}")

    # _log_path = _next_log_filename()

    # _root = logging.getLogger()
    # _root.setLevel(logging.DEBUG)
    # # Reset any prior basicConfig
    # for h in list(_root.handlers):
    #     _root.removeHandler(h)

    # _fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    # _console = logging.StreamHandler()
    # # Keep console quieter; detailed logs go to file
    # _console.setLevel(logging.INFO)
    # _console.setFormatter(_fmt)

    # _file = logging.FileHandler(_log_path, mode="w")
    # _file.setLevel(logging.DEBUG)
    # _file.setFormatter(_fmt)

    # _root.addHandler(_console)
    # _root.addHandler(_file)

    # logging.getLogger(__name__).info(f"Writing debug log to: {_log_path}")
    TUI.run() 