"""
Smooth streaming display inspired by Kimi-CLI.

This module provides flicker-free streaming output using Rich.Live,
replacing the previous streaming implementation with a cleaner, more
performant approach.

Key Features:
- Rich.Live for smooth updates without flickering
- Tool execution indicators during streaming
- Status messages and progress display
- Separate rendering for reasoning and content
- Automatic cleanup and finalization
"""

import logging
import re
from typing import Optional

import rich.box

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

logger = logging.getLogger(__name__)


_BLANK_BOX = rich.box.Box("\n".join(["    "] * 8))


class StreamingDisplay:
    """Manages live streaming display with Rich.Live"""

    def __init__(
        self,
        console: Optional[Console] = None,
        panel_padding: Optional[tuple[int, int]] = None,
        borderless: bool = False,
    ):
        """
        Initialize streaming display.

        Args:
            console: Rich Console instance (creates new one if not provided)
        """
        self.console = console or Console()
        self.panel_padding: Optional[tuple[int, int]] = panel_padding
        self.borderless: bool = borderless
        self.live: Optional[Live] = None
        self.current_message: list = []
        self.current_tool: Optional[str] = None
        self.status: Optional[str] = None
        self.reasoning_buffer: str = ""
        self.content_buffer: str = ""
        self.is_active = False
        self.role = "assistant"

        # Configuration
        self.refresh_rate = 10  # updates per second
        self.show_cursor = True  # Show typing cursor during streaming

    def _strip_finish_response_tags(self, text: str) -> str:
        """Remove finish_response markers from streaming content."""
        if not isinstance(text, str):
            return text
        return re.sub(r'<finish_response>.*?</finish_response>', '', text, flags=re.DOTALL | re.IGNORECASE)

    def _pad(self, default: tuple[int, int]) -> tuple[int, int]:
        """Return override padding when provided."""
        return self.panel_padding if self.panel_padding is not None else default

    def _box(self):
        """Return box style, blank when borderless."""
        return _BLANK_BOX if self.borderless else None

    def start_message(self, role: str = "assistant"):
        """
        Start displaying a new streaming message.

        Args:
            role: Message role (assistant, system, etc.)
        """
        if self.is_active:
            logger.warning(
                "Starting new message while previous message is still active"
            )
            self.stop()

        self.current_message = []
        self.content_buffer = ""
        self.reasoning_buffer = ""
        self.current_tool = None
        self.status = None
        self.role = role
        self.is_active = True

        # Create and start Live display
        self.live = Live(
            self._build_display(),
            console=self.console,
            refresh_per_second=self.refresh_rate,
            auto_refresh=True,
            transient=False,  # Keep display visible after stop
        )
        self.live.start()

    def append_text(self, text: str, is_reasoning: bool = False):
        """
        Append text to current message.

        Args:
            text: Text chunk to append
            is_reasoning: Whether this is reasoning content (displayed separately)
        """
        if not self.is_active:
            logger.warning("append_text called but streaming is not active")
            return

        if is_reasoning:
            self.reasoning_buffer += text
        else:
            self.content_buffer += text
            self.current_message.append(text)

        # Update Live display
        if self.live:
            try:
                self.live.update(self._build_display())
            except Exception as e:
                logger.error(f"Failed to update Live display: {e}")

    def set_tool(self, tool_name: str):
        """
        Set current tool being executed.

        Args:
            tool_name: Name of the tool being executed
        """
        if not self.is_active:
            return

        self.current_tool = tool_name
        if self.live:
            try:
                self.live.update(self._build_display())
            except Exception as e:
                logger.error(f"Failed to update tool display: {e}")

    def clear_tool(self):
        """Clear tool execution indicator"""
        if not self.is_active:
            return

        self.current_tool = None
        if self.live:
            try:
                self.live.update(self._build_display())
            except Exception as e:
                logger.error(f"Failed to clear tool display: {e}")

    def set_status(self, status: str):
        """
        Set status message.

        Args:
            status: Status message to display
        """
        if not self.is_active:
            return

        self.status = status
        if self.live:
            try:
                self.live.update(self._build_display())
            except Exception as e:
                logger.error(f"Failed to update status: {e}")

    def clear_status(self):
        """Clear status message"""
        if not self.is_active:
            return

        self.status = None
        if self.live:
            try:
                self.live.update(self._build_display())
            except Exception as e:
                logger.error(f"Failed to clear status: {e}")

    def stop(self, finalize: bool = True):
        """
        Stop live display.

        Args:
            finalize: Whether to show final formatted version before stopping
        """
        if not self.is_active:
            return

        if self.live:
            if finalize and self.content_buffer:
                # Update one last time with final content
                try:
                    final_display = self._build_final_display()
                    self.live.update(final_display)
                except Exception as e:
                    logger.error(f"Failed to finalize display: {e}")

            try:
                self.live.stop()
            except Exception as e:
                logger.error(f"Failed to stop Live display: {e}")

            self.live = None

        self.is_active = False

    def _build_display(self):
        """Build the current streaming display"""
        parts = []

        # Add status spinner if present
        if self.status:
            status_group = Group(
                Spinner("dots"), Text(f" {self.status}", style="yellow")
            )
            parts.append(
                Panel(
                    status_group,
                    border_style="yellow",
                    padding=self._pad((0, 1)),
                    box=self._box(),
                )
            )

        # Add tool execution indicator
        if self.current_tool:
            tool_text = Text()
            tool_text.append("🔧 ", style="blue")
            tool_text.append("Executing: ", style="blue")
            tool_text.append(self.current_tool, style="bold blue")
            parts.append(
                Panel(
                    tool_text,
                    border_style="blue",
                    padding=self._pad((0, 1)),
                    box=self._box(),
                )
            )

        # Add streaming message content
        if self.content_buffer:
            message_text = self.content_buffer
            message_text = self._strip_finish_response_tags(message_text)

            # Add typing cursor if enabled
            if self.show_cursor and self.is_active:
                message_text += "▊"

            # Render as markdown for better formatting
            try:
                content = (
                    Markdown(message_text) if message_text.strip() else Text("...")
                )
            except Exception:
                content = Text(message_text or "...")

            # Create panel with role-based styling
            border_color = "blue" if self.role == "assistant" else "cyan"
            title = "🐧 Penguin" if self.role == "assistant" else self.role.title()

            parts.append(
                Panel(
                    content,
                    title=title,
                    title_align="left",
                    border_style=border_color,
                    padding=self._pad((1, 2)),
                    box=self._box(),
                )
            )

        return Group(*parts) if parts else Text("...")

    def _build_final_display(self):
        """Build the final formatted display (no cursor, better formatting)"""
        parts = []

        # Display reasoning if present
        if self.reasoning_buffer.strip():
            reasoning_text = Text(f"🧠 {self.reasoning_buffer}", style="dim italic")
            parts.append(
                Panel(
                    reasoning_text,
                    title="[dim]Internal Reasoning[/dim]",
                    title_align="left",
                    border_style="dim",
                    padding=self._pad((0, 1)),
                    box=self._box(),
                )
            )

        # Display main content
        if self.content_buffer:
            cleaned = self._strip_finish_response_tags(self.content_buffer)
            try:
                content = Markdown(cleaned)
            except Exception:
                content = Text(cleaned)

            border_color = "blue" if self.role == "assistant" else "cyan"
            title = "🐧 Penguin" if self.role == "assistant" else self.role.title()

            parts.append(
                Panel(
                    content,
                    title=title,
                    title_align="left",
                    border_style=border_color,
                    padding=self._pad((1, 2)),
                    box=self._box(),
                )
            )

        return Group(*parts) if parts else Text("")

    def get_content(self) -> str:
        """Get the accumulated content"""
        return self.content_buffer

    def get_reasoning(self) -> str:
        """Get the accumulated reasoning content"""
        return self.reasoning_buffer

    def reset(self):
        """Reset all buffers and state"""
        if self.is_active:
            self.stop(finalize=False)

        self.current_message = []
        self.content_buffer = ""
        self.reasoning_buffer = ""
        self.current_tool = None
        self.status = None
        self.is_active = False
