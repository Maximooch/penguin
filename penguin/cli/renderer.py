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
import hashlib
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

# Box style with no visible borders (4 spaces per required segment, 8 rows)
BORDERLESS_BOX = rich.box.Box("\n".join(["    "] * 8))


# =============================================================================
# CONFIGURATION
# =============================================================================

class RenderStyle(Enum):
    """Rendering style presets"""
    BORDERLESS = "borderless"  # No borders, keep padding for readability
    MINIMAL = "minimal"      # No panels, just headers (best for copy/paste)
    COMPACT = "compact"      # Minimal borders, less padding
    STANDARD = "standard"    # Default Rich styling
    DETAILED = "detailed"    # Extra metadata, timestamps
    STREAMING = "streaming"  # Optimized for streaming updates


# Theme colors for different message types
# Load from centralized theme module for configurable colors
def _get_theme_colors() -> Dict[str, str]:
    """Get theme colors from centralized theme module."""
    try:
        from penguin.cli.theme import get_theme_colors
        return get_theme_colors()
    except ImportError:
        # Fallback if theme module not available
        return {
            "user": "cyan",
            "assistant": "#5F87FF",
            "system": "yellow",
            "error": "red",
            "tool": "magenta",
            "reasoning": "dim white",
            "code_border": "dim #5F87FF",
            "diff_add": "green",
            "diff_remove": "red",
            "context": "dim",
        }

# Initialize THEME_COLORS - will be refreshed on first use
THEME_COLORS = _get_theme_colors()

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

# Regex patterns for internal markers to filter
INTERNAL_MARKERS_PATTERNS = [
    re.compile(r'<execute>.*?</execute>', re.DOTALL),
    re.compile(r'<system-reminder>.*?</system-reminder>', re.DOTALL),
    re.compile(r'<internal>.*?</internal>', re.DOTALL),
    re.compile(r'<enhanced_read>.*?</enhanced_read>', re.DOTALL),
    re.compile(r'<enhanced_write>.*?</enhanced_write>', re.DOTALL),
    re.compile(r'<finish_response>.*?</finish_response>', re.DOTALL | re.IGNORECASE),
    # Filter tool result output that appears in assistant messages
    re.compile(r'^enhanced_read: \[Tool Result\].*?(?=\n\n|\Z)', re.MULTILINE | re.DOTALL),
    re.compile(r'^execute: \[Tool Result\].*?(?=\n\n|\Z)', re.MULTILINE | re.DOTALL),
    re.compile(r'^[a-z_]+: \[Tool Result\].*?(?=\n\n|\Z)', re.MULTILINE | re.DOTALL),  # Generic tool results
    # Filter standalone action format markers (actionxml, python on own lines)
    re.compile(r'^actionxml\s*$', re.MULTILINE),
    re.compile(r'^python\s*$', re.MULTILINE),
    # Filter decorative elements that LLM adds to its own responses
    re.compile(r'^[─━]{20,}$', re.MULTILINE),  # Horizontal rules (long lines of ─ or ━)
    re.compile(r'^[┏┗┃━\s]+$', re.MULTILINE),  # Box drawing lines (top/bottom borders)
    re.compile(r'┃\s*┃', re.DOTALL),  # Empty box content (just side borders)
]

TOOL_RESULT_MARKERS_PATTERNS = [
    re.compile(
        r'<list_files_filtered>.*?(?:</list_files_filtered>|</>)',
        re.DOTALL,
    ),
]

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
                 show_tool_results: bool = True,
                 width: Optional[int] = None,
                 filter_internal_markers: bool = True,
                 deduplicate_messages: bool = True,
                 max_blank_lines: int = 2,
                 panel_padding: Optional[Tuple[int, int]] = None):
        """
        Initialize the unified renderer.

        Args:
            console: Rich console instance (creates new if None)
            style: Rendering style preset
            show_timestamps: Whether to show timestamps in messages
            show_metadata: Whether to show message metadata
            width: Maximum width for panels (uses console width if None)
            filter_internal_markers: Whether to filter internal implementation markers
            deduplicate_messages: Whether to detect and skip duplicate messages
            max_blank_lines: Maximum consecutive blank lines allowed
            panel_padding: Override panel padding (tuple of (vertical, horizontal))
        """
        self.console = console or Console()
        self.style = style
        self.show_timestamps = show_timestamps
        self.show_metadata = show_metadata
        self.show_tool_results = bool(show_tool_results)
        self.width = width or (self.console.width - 8)
        self.filter_internal_markers = filter_internal_markers
        self.deduplicate_messages = deduplicate_messages
        self.max_blank_lines = max_blank_lines
        self.panel_padding: Optional[Tuple[int, int]] = panel_padding

        # Cache for language detection
        self._lang_cache = {}

        # Deduplication tracking
        self._last_message_hash = None
        self._message_history = []  # Store last N message hashes

    def _get_panel_padding(self, default: Optional[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        """Resolve panel padding with optional override."""
        return self.panel_padding if self.panel_padding is not None else default

    def _get_box_style(self, default_box):
        """Return borderless box when requested."""
        return BORDERLESS_BOX if self.style == RenderStyle.BORDERLESS else default_box

    def _is_finish_response_echo(self, text: str) -> bool:
        """Detect finish_response tool echoes to suppress from user-facing transcript."""
        normalized = text.strip().lower()
        if not normalized:
            return False
        return normalized.startswith("finish_response") or normalized.startswith("✓ finish_response") or normalized.startswith("response complete")

    def _strip_finish_response_tags(self, text: str) -> str:
        """Remove finish_response tags/echoes from free-form text."""
        if not isinstance(text, str):
            return text
        return re.sub(r'<finish_response>.*?</finish_response>', '', text, flags=re.DOTALL | re.IGNORECASE)

    def set_show_tool_results(self, enabled: bool) -> None:
        """Toggle rendering of tool result blocks."""
        self.show_tool_results = bool(enabled)

    # =========================================================================
    # MAIN RENDERING METHODS
    # =========================================================================

    def render_message(self,
                      content: Union[str, List[Dict], Dict],
                      role: str = "assistant",
                      timestamp: Optional[Union[str, datetime]] = None,
                      metadata: Optional[Dict] = None,
                      as_panel: bool = True) -> Union[Panel, Group, None]:
        """
        Render a complete message with proper formatting.

        Args:
            content: Message content (string, multimodal list, or dict)
            role: Message role (user, assistant, system, etc.)
            timestamp: Optional timestamp
            metadata: Optional metadata dict
            as_panel: Whether to wrap in a Panel

        Returns:
            Rendered Panel or Group of renderables, or None if duplicate
        """
        # Check for duplicates first
        if self.is_duplicate(content):
            return None

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

        # Filter internal markers if string content
        if isinstance(actual_content, str):
            actual_content = self.filter_content(actual_content)
            actual_content = self._strip_finish_response_tags(actual_content)
            # Skip auto-finish system echoes (finish_response tool confirmations)
            if role == "system":
                if self._is_finish_response_echo(actual_content):
                    logger.debug("Suppressing finish_response system message")
                    return None

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

        # Wrap in panel if requested AND not in MINIMAL mode
        if as_panel and self.style != RenderStyle.MINIMAL:
            return self.create_message_panel(
                message_group,
                role=role,
                timestamp=timestamp,
                metadata=metadata
            )
        elif as_panel and self.style == RenderStyle.MINIMAL:
            # MINIMAL mode: just add a simple header instead of panel
            return self.create_minimal_message(
                message_group,
                role=role,
                timestamp=timestamp
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
                    text_content = self.filter_content(item.get("text", ""))
                    text_content = self._strip_finish_response_tags(text_content)
                    if role == "system" and self._is_finish_response_echo(text_content):
                        logger.debug("Suppressing finish_response system message (multimodal)")
                        continue
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

            # Render code block (skip if empty or just comments/whitespace)
            stripped_code = code.strip()
            if stripped_code and not self._is_trivial_code(stripped_code):
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
                         line_numbers: bool = True) -> Union[Panel, Group]:
        """
        Render a code block with syntax highlighting.

        Args:
            code: Code to render
            language: Programming language
            title: Optional panel title
            line_numbers: Whether to show line numbers

        Returns:
            Panel containing highlighted code, or Group for MINIMAL mode
        """
        # Clean up code
        code = code.strip()
        if not code:
            if self.style == RenderStyle.MINIMAL:
                return Text("(Empty code block)", style="dim italic")
            return Panel(
                Text("(Empty code block)", style="dim italic"),
                padding=self._get_panel_padding((1, 1)),
                box=self._get_box_style(rich.box.ROUNDED),
            )

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

        # MINIMAL mode: no panel, just simple header + code (no extra spacing)
        if self.style == RenderStyle.MINIMAL:
            # Simple one-line header for code blocks
            header = Text(f"[{display_name}]", style="dim")
            return Group(header, syntax)

        # Panel mode for other styles
        panel_title = title or f"📋 {display_name}"
        return Panel(
            syntax,
            title=panel_title,
            title_align="left",
            border_style=THEME_COLORS.get("code_border", "dim blue"),
            padding=self._get_panel_padding(
                (0, 1) if self.style == RenderStyle.COMPACT else (1, 2)
            ),
            box=self._get_box_style(rich.box.ROUNDED),
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

    def _is_trivial_code(self, code: str) -> bool:
        """
        Check if code block is trivial (just comments, empty, or placeholder).

        Args:
            code: Code to check

        Returns:
            True if code is trivial and should be skipped
        """
        # Remove all whitespace and common comment patterns
        cleaned = re.sub(r'#.*$', '', code, flags=re.MULTILINE)  # Python/shell comments
        cleaned = re.sub(r'//.*$', '', cleaned, flags=re.MULTILINE)  # C-style comments
        cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)  # Block comments
        cleaned = cleaned.strip()

        # If nothing left, it's trivial
        return len(cleaned) == 0

    # =========================================================================
    # SPECIAL CONTENT RENDERING
    # =========================================================================

    def render_reasoning(self, reasoning: str) -> Union[Panel, Group]:
        """
        Render reasoning content in a special panel.

        Args:
            reasoning: Reasoning text

        Returns:
            Panel with formatted reasoning, or Group for MINIMAL mode
        """
        # Use Markdown rendering for reasoning content for proper formatting
        from rich.markdown import Markdown

        if self.style == RenderStyle.MINIMAL:
            # MINIMAL mode: just content (gray/dim text), no header or panel
            content = Text(reasoning.strip(), style="dim")  # Gray dim text
            return content
        else:
            # Panel mode for other styles
            return Panel(
                Markdown(reasoning.strip()),
                title="🧠 Reasoning",
                title_align="left",
                border_style=THEME_COLORS["reasoning"],
                padding=self._get_panel_padding(
                    (0, 1) if self.style == RenderStyle.COMPACT else (1, 2)
                ),
                box=self._get_box_style(rich.box.ROUNDED),
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
        if self.style == RenderStyle.BORDERLESS:
            box_style = BORDERLESS_BOX
        elif self.style == RenderStyle.COMPACT:
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
            padding=self._get_panel_padding(
                (0, 1) if self.style == RenderStyle.COMPACT else (1, 2)
            )
        )

    def create_minimal_message(self,
                              content: Any,
                              role: str = "assistant",
                              timestamp: Optional[Union[str, datetime]] = None) -> Group:
        """
        Create a minimal message with just a header (no panel borders).

        Args:
            content: Content to display
            role: Message role
            timestamp: Optional timestamp

        Returns:
            Group with header + content
        """
        # Role emojis and names
        role_info = {
            "user": ("👤", "You"),
            "assistant": ("🐧", "Penguin"),
            "system": ("⚙️", "System"),
            "error": ("❌", "Error"),
            "tool": ("🔧", "Tool"),
        }
        emoji, display_name = role_info.get(role, ("💬", role.capitalize()))

        # Build header
        header_parts = [f"{emoji} {display_name}:"]
        if self.show_timestamps and timestamp:
            formatted_time = self.format_timestamp(timestamp)
            if formatted_time:
                header_parts.append(f"[{formatted_time}]")

        header_text = " ".join(header_parts)

        # Create header with color
        border_style = THEME_COLORS.get(role, "white")
        header = Text(header_text, style=f"bold {border_style}")

        # Return header + content WITHOUT extra blank line spacing
        return Group(header, content)

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
    # CONTENT FILTERING AND DEDUPLICATION
    # =========================================================================

    def filter_content(self, content: str) -> str:
        """
        Filter internal implementation markers from content.

        Args:
            content: Content to filter

        Returns:
            Filtered content with internal markers removed
        """
        if not self.filter_internal_markers or not isinstance(content, str):
            return content

        filtered = content

        # First pass: Remove complete box structures with titles
        # Pattern: ┏━━━┓ with title in ┃ ┃ and ┗━━━┛
        filtered = re.sub(
            r'┏[━]+┓\n┃[^\n]*┃\n┗[━]+┛\n?',
            '',
            filtered
        )

        # Second pass: Apply all other patterns
        for pattern in INTERNAL_MARKERS_PATTERNS:
            filtered = pattern.sub('', filtered)

        if not self.show_tool_results:
            for pattern in TOOL_RESULT_MARKERS_PATTERNS:
                filtered = pattern.sub('', filtered)

        # Clean up excessive whitespace left by filtering
        # Replace multiple consecutive newlines with max allowed
        filtered = re.sub(r'\n{3,}', '\n' * (self.max_blank_lines + 1), filtered)

        return filtered.strip()

    def get_content_hash(self, content: Union[str, Any]) -> str:
        """
        Generate a hash for content to detect duplicates.

        Args:
            content: Content to hash

        Returns:
            MD5 hash of content
        """
        import hashlib

        # Convert content to string representation
        if isinstance(content, str):
            content_str = content
        elif isinstance(content, dict):
            content_str = str(content.get("content", ""))
        elif isinstance(content, list):
            content_str = "".join(str(item) for item in content)
        else:
            content_str = str(content)

        # Aggressive normalization to catch near-duplicates
        normalized = content_str.lower()  # Case-insensitive
        normalized = re.sub(r'[^\w\s]', '', normalized)  # Remove punctuation
        normalized = re.sub(r'\s+', ' ', normalized).strip()  # Normalize whitespace

        return hashlib.md5(normalized.encode()).hexdigest()

    def is_duplicate(self, content: Union[str, Any]) -> bool:
        """
        Check if content is a duplicate of recently rendered messages.

        Args:
            content: Content to check

        Returns:
            True if content is a duplicate
        """
        if not self.deduplicate_messages:
            return False

        content_hash = self.get_content_hash(content)

        # Check against ALL recent history (expanded from 5 to 20 messages for better detection)
        if content_hash in self._message_history:
            logger.debug(f"Skipping duplicate message (hash: {content_hash[:8]}...)")
            return True

        # Update history
        self._message_history.append(content_hash)
        self._last_message_hash = content_hash

        # Keep history bounded (increased from 10 to 50 for better duplicate detection)
        if len(self._message_history) > 50:
            self._message_history = self._message_history[-50:]

        return False

    def should_add_separator(self, prev_role: Optional[str], curr_role: str) -> bool:
        """
        Determine if a blank line separator is needed between messages.

        Args:
            prev_role: Role of previous message (None if no previous message)
            curr_role: Role of current message

        Returns:
            True if separator should be added
        """
        if prev_role is None:
            return False

        # Add separator on major transitions
        # Don't add separator between consecutive system messages
        if prev_role == "system" and curr_role == "system":
            return False

        # Don't add separator between consecutive tool messages
        if prev_role == "tool" and curr_role == "tool":
            return False

        # Add separator when transitioning from assistant to system
        if prev_role == "assistant" and curr_role == "system":
            return True

        # Add separator when transitioning from system to user
        if prev_role == "system" and curr_role == "user":
            return True

        # Add separator when transitioning from assistant to user
        if prev_role == "assistant" and curr_role == "user":
            return True

        # Default: no separator for compact display
        return False

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
            width=self.width,
            padding=self._get_panel_padding((1, 1)),
            box=self._get_box_style(rich.box.ROUNDED),
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
