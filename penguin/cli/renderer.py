"""
Unified Message Renderer for Penguin CLI

This module consolidates all message rendering logic into a single, reusable component.
It eliminates duplication between cli.py, ui.py, and interface.py by providing
a centralized rendering system with consistent formatting.

Key Features:
- Unified code block detection and highlighting
- Consistent panel styling across all contexts
- Markdown rendering with proper formatting
- Multi-modal content support (text, images, etc.)
- Streaming message support with cursor indicators
- Diff detection and formatting
- Language auto-detection
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.table import Table
import rich.box

import logging

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

class RenderStyle(Enum):
    """Rendering style presets"""
    COMPACT = "compact"      # Minimal borders, less padding
    STANDARD = "standard"    # Default Rich styling
    DETAILED = "detailed"    # Extra metadata, timestamps
    STREAMING = "streaming"  # Optimized for streaming updates


# Theme colors for different message types
THEME_COLORS = {
    "user": "cyan",
    "assistant": "blue",
    "system": "yellow",
    "error": "red",
    "tool": "magenta",
    "reasoning": "dim white",
    "code_border": "dim blue",
    "diff_add": "green",
    "diff_remove": "red",
    "context": "dim",
}

# Language display names for code blocks
LANGUAGE_DISPLAY_NAMES = {
    "python": "Python",
    "py": "Python",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "java": "Java",
    "cpp": "C++",
    "c": "C",
    "csharp": "C#",
    "cs": "C#",
    "ruby": "Ruby",
    "rb": "Ruby",
    "go": "Go",
    "rust": "Rust",
    "rs": "Rust",
    "php": "PHP",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "kt": "Kotlin",
    "scala": "Scala",
    "r": "R",
    "matlab": "MATLAB",
    "sql": "SQL",
    "bash": "Bash",
    "sh": "Shell",
    "shell": "Shell",
    "powershell": "PowerShell",
    "ps1": "PowerShell",
    "yaml": "YAML",
    "yml": "YAML",
    "json": "JSON",
    "xml": "XML",
    "html": "HTML",
    "css": "CSS",
    "scss": "SCSS",
    "sass": "Sass",
    "markdown": "Markdown",
    "md": "Markdown",
    "latex": "LaTeX",
    "tex": "LaTeX",
    "dockerfile": "Dockerfile",
    "docker": "Docker",
    "makefile": "Makefile",
    "make": "Makefile",
    "cmake": "CMake",
    "diff": "Diff",
    "patch": "Patch",
    "toml": "TOML",
    "ini": "INI",
    "conf": "Config",
    "nginx": "Nginx",
    "apache": "Apache",
    "vim": "Vim Script",
    "lua": "Lua",
    "perl": "Perl",
    "pl": "Perl",
    "elixir": "Elixir",
    "ex": "Elixir",
    "erlang": "Erlang",
    "erl": "Erlang",
    "haskell": "Haskell",
    "hs": "Haskell",
    "ocaml": "OCaml",
    "ml": "OCaml",
    "clojure": "Clojure",
    "clj": "Clojure",
    "scheme": "Scheme",
    "lisp": "Lisp",
    "elisp": "Emacs Lisp",
    "julia": "Julia",
    "jl": "Julia",
    "fortran": "Fortran",
    "f90": "Fortran",
    "cobol": "COBOL",
    "pascal": "Pascal",
    "delphi": "Delphi",
    "ada": "Ada",
    "assembly": "Assembly",
    "asm": "Assembly",
    "verilog": "Verilog",
    "vhdl": "VHDL",
    "dart": "Dart",
    "groovy": "Groovy",
    "solidity": "Solidity",
    "sol": "Solidity",
    "terraform": "Terraform",
    "tf": "Terraform",
    "graphql": "GraphQL",
    "gql": "GraphQL",
    "protobuf": "Protocol Buffers",
    "proto": "Protocol Buffers",
    "text": "Text",
    "txt": "Text",
    "plain": "Plain Text",
}

# Regex patterns for code detection
CODE_BLOCK_PATTERN = re.compile(r'```(\w+)?\n(.*?)```', re.DOTALL)
REASONING_PATTERN = re.compile(r'<reasoning>(.*?)</reasoning>', re.DOTALL)
DIFF_MARKERS = re.compile(r'^(diff --git|---|\+\+\+|@@|\+|-)', re.MULTILINE)

# Syntax themes for different languages
SYNTAX_THEMES = {
    "default": "monokai",
    "diff": "monokai",
    "html": "github-dark",
    "xml": "github-dark",
    "bash": "native",
    "shell": "native",
    "sh": "native",
}


# =============================================================================
# UNIFIED RENDERER
# =============================================================================

class UnifiedRenderer:
    """
    Unified message renderer that consolidates all rendering logic.

    This class provides a single interface for rendering messages,
    code blocks, panels, and other UI elements consistently across
    the entire CLI application.
    """

    def __init__(self,
                 console: Optional[Console] = None,
                 style: RenderStyle = RenderStyle.STANDARD,
                 show_timestamps: bool = True,
                 show_metadata: bool = False,
                 width: Optional[int] = None):
        """
        Initialize the unified renderer.

        Args:
            console: Rich console instance (creates new if None)
            style: Rendering style preset
            show_timestamps: Whether to show timestamps in messages
            show_metadata: Whether to show message metadata
            width: Maximum width for panels (uses console width if None)
        """
        self.console = console or Console()
        self.style = style
        self.show_timestamps = show_timestamps
        self.show_metadata = show_metadata
        self.width = width or (self.console.width - 8)

        # Cache for language detection
        self._lang_cache = {}

    # =========================================================================
    # MAIN RENDERING METHODS
    # =========================================================================

    def render_message(self,
                      content: Union[str, List[Dict], Dict],
                      role: str = "assistant",
                      timestamp: Optional[Union[str, datetime]] = None,
                      metadata: Optional[Dict] = None,
                      as_panel: bool = True) -> Union[Panel, Group]:
        """
        Render a complete message with proper formatting.

        Args:
            content: Message content (string, multimodal list, or dict)
            role: Message role (user, assistant, system, etc.)
            timestamp: Optional timestamp
            metadata: Optional metadata dict
            as_panel: Whether to wrap in a Panel

        Returns:
            Rendered Panel or Group of renderables
        """
        # Handle different content types
        if isinstance(content, dict):
            # Extract from dict format
            actual_content = content.get("content", "")
            role = content.get("role", role)
            timestamp = content.get("timestamp", timestamp)
            metadata = content.get("metadata", metadata) or {}
        else:
            actual_content = content
            metadata = metadata or {}

        # Process reasoning blocks if present
        actual_content, reasoning = self.extract_reasoning(actual_content)

        # Build the message renderables
        renderables = []

        # Add reasoning panel if present (before main content)
        if reasoning:
            renderables.append(self.render_reasoning(reasoning))

        # Render main content
        content_group = self.render_content(actual_content, role)
        renderables.append(content_group)

        # Create final group
        message_group = Group(*renderables) if len(renderables) > 1 else renderables[0]

        # Wrap in panel if requested
        if as_panel:
            return self.create_message_panel(
                message_group,
                role=role,
                timestamp=timestamp,
                metadata=metadata
            )

        return message_group

    def render_content(self,
                       content: Union[str, List[Dict]],
                       role: str = "default") -> Group:
        """
        Render message content, handling text, code blocks, and multimodal content.

        Args:
            content: Content to render
            role: Role for theme selection

        Returns:
            Group of rendered elements
        """
        renderables = []

        if isinstance(content, list):
            # Multimodal content
            for item in content:
                item_type = item.get("type")
                if item_type == "text":
                    text_content = item.get("text", "")
                    if text_content:
                        renderables.extend(self._render_text_segment(text_content))
                elif item_type == "image_url":
                    image_path = item.get("image_path", "unknown image")
                    renderables.append(Text(f"[Image: {image_path}]", style="dim italic"))
                elif item_type == "tool_result":
                    # Handle tool results specially
                    tool_renderables = self.render_tool_result(item)
                    renderables.extend(tool_renderables)
                else:
                    # Unknown type
                    renderables.append(Text(f"[{item_type}: {item}]", style="dim"))

            if not renderables:
                renderables.append(Text("(Empty multimodal content)", style="dim italic"))

        elif isinstance(content, str):
            # String content
            renderables.extend(self._render_text_segment(content))

            if not renderables and not content:
                renderables.append(Text("(Waiting for response...)", style="dim italic"))
            elif not renderables and content:
                # Content was just whitespace
                renderables.append(Markdown(content.strip()))

        else:
            # Unsupported content type
            renderables.append(Text(f"(Unsupported content type: {type(content)})", style="dim italic"))

        return Group(*renderables)

    def _render_text_segment(self, text: str) -> List[Any]:
        """
        Render a text segment, detecting and formatting code blocks.

        Args:
            text: Text to render

        Returns:
            List of renderables
        """
        if not text:
            return []

        renderables = []
        last_end = 0

        # Find all code blocks
        for match in CODE_BLOCK_PATTERN.finditer(text):
            start, end = match.span()
            language = match.group(1) or ""
            code = match.group(2)

            # Add text before code block
            if start > last_end:
                preceding_text = text[last_end:start].strip()
                if preceding_text:
                    renderables.append(Markdown(preceding_text))

            # Render code block
            code_panel = self.render_code_block(code, language)
            renderables.append(code_panel)
            last_end = end

        # Add remaining text
        if last_end < len(text):
            remaining_text = text[last_end:].strip()
            if remaining_text:
                renderables.append(Markdown(remaining_text))

        # If no code blocks found, render as markdown
        if not renderables and text.strip():
            renderables.append(Markdown(text.strip()))

        return renderables

    # =========================================================================
    # CODE RENDERING
    # =========================================================================

    def render_code_block(self,
                         code: str,
                         language: str = "",
                         title: Optional[str] = None,
                         line_numbers: bool = True) -> Panel:
        """
        Render a code block with syntax highlighting.

        Args:
            code: Code to render
            language: Programming language
            title: Optional panel title
            line_numbers: Whether to show line numbers

        Returns:
            Panel containing highlighted code
        """
        # Clean up code
        code = code.strip()
        if not code:
            return Panel(Text("(Empty code block)", style="dim italic"))

        # Auto-detect language if needed
        if not language or language == "text":
            language = self.detect_language(code)

        # Check if it's a diff
        if language in ["text", ""] and self.is_diff(code):
            language = "diff"

        # Get display name
        display_name = LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize() if language else "Code")

        # Get appropriate theme
        theme = SYNTAX_THEMES.get(language, SYNTAX_THEMES["default"])

        # Create syntax object
        syntax = Syntax(
            code,
            lexer=language if language else "text",
            theme=theme,
            line_numbers=line_numbers,
            word_wrap=True
        )

        # Create panel
        panel_title = title or f"📋 {display_name}"
        return Panel(
            syntax,
            title=panel_title,
            title_align="left",
            border_style=THEME_COLORS.get("code_border", "dim blue"),
            padding=(0, 1) if self.style == RenderStyle.COMPACT else (1, 2),
            expand=False
        )

    def detect_language(self, code: str) -> str:
        """
        Auto-detect the programming language from code content.

        Args:
            code: Code to analyze

        Returns:
            Detected language identifier
        """
        # Check cache first
        cache_key = hash(code[:500])  # Use first 500 chars for cache key
        if cache_key in self._lang_cache:
            return self._lang_cache[cache_key]

        # Language detection patterns
        patterns = [
            (r'^\s*import\s+\w+|^\s*from\s+\w+\s+import|^\s*def\s+\w+|^\s*class\s+\w+', 'python'),
            (r'^\s*function\s+\w+|^\s*const\s+\w+\s*=|^\s*let\s+\w+\s*=|^\s*var\s+\w+\s*=|\$\(|=>', 'javascript'),
            (r'^\s*interface\s+\w+|^\s*type\s+\w+\s*=|^\s*enum\s+\w+', 'typescript'),
            (r'^\s*public\s+class|^\s*private\s+\w+|^\s*protected\s+\w+|System\.out\.println', 'java'),
            (r'^\s*#include\s*<|^\s*using\s+namespace|^\s*int\s+main\s*\(|std::', 'cpp'),
            (r'^\s*func\s+\w+|^\s*package\s+\w+|^\s*import\s+"', 'go'),
            (r'^\s*fn\s+\w+|^\s*let\s+mut\s+|^\s*impl\s+\w+|^\s*pub\s+\w+', 'rust'),
            (r'^\s*def\s+\w+|^\s*class\s+\w+|^\s*module\s+\w+|^\s*require\s+', 'ruby'),
            (r'<\?php|^\s*\$\w+\s*=|^\s*echo\s+|^\s*function\s+\w+\s*\(', 'php'),
            (r'^\s*SELECT\s+|^\s*INSERT\s+|^\s*UPDATE\s+|^\s*DELETE\s+|^\s*CREATE\s+TABLE', 'sql'),
            (r'^\s*#!/bin/bash|^\s*#!/bin/sh|^\s*echo\s+|^\s*if\s+\[\[|\s*fi$', 'bash'),
            (r'^\s*\$\w+\s*=|Write-Host|Get-\w+|Set-\w+', 'powershell'),
            (r'^\s*\w+:\s*$|^\s*-\s+\w+:|^\s*\w+:\s*\||^\s*\w+:\s*>', 'yaml'),
            (r'^\s*\{[\s\S]*"[\w-]+"\s*:', 'json'),
            (r'^<\?xml|^<\w+[^>]*>.*</\w+>', 'xml'),
            (r'^<!DOCTYPE html>|^<html|^<head>|^<body>', 'html'),
            (r'^\s*\.\w+\s*\{|^\s*#\w+\s*\{|^\s*\w+\s*\{[\s\S]*\}', 'css'),
            (r'^FROM\s+\w+|^RUN\s+|^CMD\s+|^EXPOSE\s+|^ENV\s+', 'dockerfile'),
            (r'^\s*\w+\s*:=\s*|^\s*\w+\s*\+=\s*|^\s*\.PHONY:', 'makefile'),
        ]

        for pattern, lang in patterns:
            if re.search(pattern, code, re.MULTILINE | re.IGNORECASE):
                self._lang_cache[cache_key] = lang
                return lang

        # Default to text
        self._lang_cache[cache_key] = "text"
        return "text"

    def is_diff(self, text: str) -> bool:
        """
        Check if text looks like a diff/patch.

        Args:
            text: Text to check

        Returns:
            True if text appears to be a diff
        """
        return bool(DIFF_MARKERS.search(text))

    # =========================================================================
    # SPECIAL CONTENT RENDERING
    # =========================================================================

    def render_reasoning(self, reasoning: str) -> Panel:
        """
        Render reasoning content in a special panel.

        Args:
            reasoning: Reasoning text

        Returns:
            Panel with formatted reasoning
        """
        # Use Markdown rendering for reasoning content for proper formatting
        from rich.markdown import Markdown

        return Panel(
            Markdown(reasoning.strip()),
            title="🧠 Reasoning",
            title_align="left",
            border_style=THEME_COLORS["reasoning"],
            padding=(0, 1) if self.style == RenderStyle.COMPACT else (1, 2)
        )

    def render_tool_result(self, result: Dict) -> List[Any]:
        """
        Render tool execution results.

        Args:
            result: Tool result dictionary

        Returns:
            List of renderables for the tool result
        """
        renderables = []

        tool_name = result.get("tool", "Unknown Tool")
        status = result.get("status", "completed")
        output = result.get("output", "")

        # Create tool header
        if status == "error":
            header_style = THEME_COLORS["error"]
            icon = "❌"
        else:
            header_style = THEME_COLORS["tool"]
            icon = "🔧"

        header = Text(f"{icon} {tool_name}", style=header_style)
        renderables.append(header)

        # Render output
        if output:
            if isinstance(output, str) and len(output) > 100:
                # Long output might be code
                lang = self.detect_language(output)
                if lang != "text":
                    renderables.append(self.render_code_block(output, lang, title=f"{tool_name} Output"))
                else:
                    renderables.append(Text(output, style="dim"))
            else:
                renderables.append(Text(str(output), style="dim"))

        return renderables

    def render_streaming_message(self,
                                content: str,
                                role: str = "assistant",
                                show_cursor: bool = True) -> Panel:
        """
        Render a message that's currently streaming.

        Args:
            content: Current streamed content
            role: Message role
            show_cursor: Whether to show streaming cursor

        Returns:
            Panel with streaming message
        """
        # Add cursor if requested
        if show_cursor:
            if content.strip():
                display_content = content + " 🐧"
            else:
                display_content = "Thinking... 🐧"
        else:
            display_content = content or "..."

        # For streaming, use plain Text (no Markdown to avoid broken formatting of incomplete code blocks)
        content_renderable = Text(display_content) if display_content.strip() else Text("Thinking... 🐧", style="dim italic")

        # Create panel with streaming indicator
        return self.create_message_panel(
            content_renderable,
            role=role,
            metadata={"is_streaming": True}
        )

    # =========================================================================
    # PANEL AND FORMATTING HELPERS
    # =========================================================================

    def create_message_panel(self,
                            content: Any,
                            role: str = "assistant",
                            timestamp: Optional[Union[str, datetime]] = None,
                            metadata: Optional[Dict] = None) -> Panel:
        """
        Create a message panel with consistent styling.

        Args:
            content: Content to wrap in panel
            role: Message role for styling
            timestamp: Optional timestamp
            metadata: Optional metadata

        Returns:
            Styled Panel
        """
        # Get role color
        border_style = THEME_COLORS.get(role, "white")

        # Build title
        title_parts = []

        # Add role emoji
        role_emojis = {
            "user": "👤",
            "assistant": "🐧",
            "system": "⚙️",
            "error": "❌",
            "tool": "🔧",
        }
        emoji = role_emojis.get(role, "💬")

        # Use "Penguin" for assistant role, "You" for user, capitalize others
        if role == "assistant":
            display_role = "Penguin"
        elif role == "user":
            display_role = "You"
        else:
            display_role = role.capitalize()
        title_parts.append(f"{emoji} {display_role}")

        # Add timestamp if enabled
        if self.show_timestamps and timestamp:
            formatted_time = self.format_timestamp(timestamp)
            if formatted_time:
                title_parts.append(f"[{formatted_time}]")

        # Add metadata indicators if enabled
        if self.show_metadata and metadata:
            if metadata.get("is_streaming"):
                title_parts.append("(streaming...)")
            if metadata.get("token_count"):
                title_parts.append(f"({metadata['token_count']} tokens)")

        title = " ".join(title_parts)

        # Determine box style based on rendering style
        if self.style == RenderStyle.COMPACT:
            box_style = rich.box.SIMPLE
        elif self.style == RenderStyle.DETAILED:
            box_style = rich.box.DOUBLE
        else:
            box_style = rich.box.ROUNDED

        # Create panel
        return Panel(
            content,
            title=title,
            title_align="left",
            border_style=border_style,
            width=self.width,
            box=box_style,
            padding=(0, 1) if self.style == RenderStyle.COMPACT else (1, 2)
        )

    def format_timestamp(self, timestamp: Union[str, datetime, None]) -> str:
        """
        Format a timestamp consistently.

        Args:
            timestamp: Timestamp to format

        Returns:
            Formatted timestamp string
        """
        if timestamp is None:
            return ""

        # If it's already a datetime object
        if hasattr(timestamp, 'strftime'):
            return timestamp.strftime("%H:%M:%S")

        # If it's a string, try to parse it
        timestamp_str = str(timestamp)

        # Check if already in time format
        if re.match(r'^\d{1,2}:\d{2}(:\d{2})?$', timestamp_str):
            return timestamp_str

        # Try to parse as ISO format
        try:
            dt_obj = datetime.fromisoformat(timestamp_str)
            return dt_obj.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            return timestamp_str[:8] if len(timestamp_str) > 8 else timestamp_str

    def extract_reasoning(self, content: Union[str, Any]) -> Tuple[Any, Optional[str]]:
        """
        Extract reasoning blocks from content.

        Args:
            content: Content to process

        Returns:
            Tuple of (content without reasoning, reasoning text)
        """
        if not isinstance(content, str):
            return content, None

        match = REASONING_PATTERN.search(content)
        if match:
            reasoning = match.group(1).strip()
            content_without_reasoning = REASONING_PATTERN.sub("", content).strip()
            return content_without_reasoning, reasoning

        return content, None

    # =========================================================================
    # UTILITY RENDERING METHODS
    # =========================================================================

    def render_error(self,
                    error_message: str,
                    details: Optional[str] = None,
                    traceback: Optional[str] = None) -> Panel:
        """
        Render an error message with optional details.

        Args:
            error_message: Main error message
            details: Optional error details
            traceback: Optional traceback

        Returns:
            Error panel
        """
        renderables = []

        # Main error message
        renderables.append(Text(error_message, style="bold red"))

        # Details if provided
        if details:
            renderables.append(Text(f"\nDetails: {details}", style="yellow"))

        # Traceback if provided
        if traceback:
            renderables.append(self.render_code_block(traceback, "python", title="Traceback"))

        return Panel(
            Group(*renderables),
            title="❌ Error",
            title_align="left",
            border_style=THEME_COLORS["error"],
            width=self.width
        )

    def render_list(self,
                   items: List[Any],
                   title: str = "Items",
                   columns: Optional[List[str]] = None) -> Table:
        """
        Render a list of items as a table.

        Args:
            items: Items to render
            title: Table title
            columns: Column names

        Returns:
            Formatted table
        """
        table = Table(title=title, show_header=True, header_style="bold")

        # Auto-detect columns if not provided
        if not columns and items and isinstance(items[0], dict):
            columns = list(items[0].keys())

        # Add columns
        for col in (columns or ["Item"]):
            table.add_column(col)

        # Add rows
        for item in items:
            if isinstance(item, dict):
                row = [str(item.get(col, "")) for col in columns]
            else:
                row = [str(item)]
            table.add_row(*row)

        return table

    def render_status(self,
                     message: str,
                     status_type: str = "info") -> Text:
        """
        Render a status message.

        Args:
            message: Status message
            status_type: Type of status (info, success, warning, error)

        Returns:
            Formatted status text
        """
        status_styles = {
            "info": "blue",
            "success": "green",
            "warning": "yellow",
            "error": "red",
        }

        status_icons = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
        }

        style = status_styles.get(status_type, "white")
        icon = status_icons.get(status_type, "•")

        return Text(f"{icon} {message}", style=style)


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

_renderer_instance: Optional[UnifiedRenderer] = None


def get_renderer(console: Optional[Console] = None, **kwargs) -> UnifiedRenderer:
    """
    Get or create the singleton renderer instance.

    Args:
        console: Optional console to use
        **kwargs: Additional renderer configuration

    Returns:
        UnifiedRenderer singleton instance
    """
    global _renderer_instance

    if _renderer_instance is None:
        _renderer_instance = UnifiedRenderer(console=console, **kwargs)

    return _renderer_instance


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def render_message(content: Any, role: str = "assistant", **kwargs) -> Panel:
    """Convenience function to render a message using the default renderer."""
    renderer = get_renderer()
    return renderer.render_message(content, role, **kwargs)


def render_code(code: str, language: str = "", **kwargs) -> Panel:
    """Convenience function to render a code block."""
    renderer = get_renderer()
    return renderer.render_code_block(code, language, **kwargs)


def render_error(error_message: str, **kwargs) -> Panel:
    """Convenience function to render an error."""
    renderer = get_renderer()
    return renderer.render_error(error_message, **kwargs)


def render_streaming(content: str, role: str = "assistant", **kwargs) -> Panel:
    """Convenience function to render streaming content."""
    renderer = get_renderer()
    return renderer.render_streaming_message(content, role, **kwargs)