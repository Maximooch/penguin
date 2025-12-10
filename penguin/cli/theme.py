"""
Theme configuration for Penguin CLI.

This module provides centralized theme color management, loading colors from
config.yml with fallback defaults. Using hex colors (e.g., "#5F87FF") ensures
consistent appearance across different terminal emulators.

Usage:
    from penguin.cli.theme import get_theme_colors, get_color

    # Get all theme colors
    colors = get_theme_colors()

    # Get a specific color with fallback
    assistant_color = get_color("assistant")
"""

from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

# Default theme colors
# Using hex codes for colors that need cross-terminal consistency
# Named colors (cyan, yellow, etc.) work well but may vary between terminals
DEFAULT_THEME_COLORS: Dict[str, str] = {
    "user": "cyan",
    "assistant": "#5F87FF",  # True blue - consistent across terminals
    "system": "yellow",
    "error": "red",
    "tool": "magenta",
    "reasoning": "dim white",
    "code_border": "dim #5F87FF",
    "diff_add": "green",
    "diff_remove": "red",
    "context": "dim",
    "banner": "bold #00D7FF",  # Bright cyan for ASCII banner
    "penguin_name": "#5F87FF",  # Color for "Penguin" branding text
    # Panel colors
    "response_panel": "cyan",
    "stats_panel": "green",
    "conversation_panel": "#5F87FF",
    # Message panel colors
    "message_panel_user": "grey",
    "message_panel_assistant": "green",
    "message_panel_system": "yellow",
    "message_panel_tool": "#5F87FF",
    "message_panel_default": "white",
}

# Cache for loaded theme
_theme_cache: Optional[Dict[str, str]] = None


def _load_theme_from_config() -> Dict[str, str]:
    """Load theme colors from config.yml, merging with defaults."""
    global _theme_cache

    if _theme_cache is not None:
        return _theme_cache

    # Start with defaults
    theme = DEFAULT_THEME_COLORS.copy()

    try:
        from penguin.config import load_config
        config = load_config()

        # Get theme.colors from config
        theme_config = config.get("theme", {})
        colors_config = theme_config.get("colors", {})

        if colors_config:
            # Merge config colors with defaults (config takes precedence)
            for key, value in colors_config.items():
                if value:  # Only override if value is not empty
                    theme[key] = value
                    logger.debug(f"Theme color '{key}' set to '{value}' from config")
    except Exception as e:
        logger.debug(f"Could not load theme from config, using defaults: {e}")

    _theme_cache = theme
    return theme


def get_theme_colors() -> Dict[str, str]:
    """Get the current theme colors dictionary.

    Returns:
        Dictionary mapping color names to Rich color values.
        Values can be color names ("cyan") or hex codes ("#5F87FF").
    """
    return _load_theme_from_config()


def get_color(name: str, fallback: Optional[str] = None) -> str:
    """Get a specific theme color by name.

    Args:
        name: The color name (e.g., "assistant", "user", "banner")
        fallback: Fallback color if name not found. Defaults to "white".

    Returns:
        The color value (Rich color name or hex code)
    """
    colors = get_theme_colors()
    return colors.get(name, fallback or "white")


def refresh_theme() -> None:
    """Clear the theme cache to reload from config.

    Call this if config has been updated and you need to reload colors.
    """
    global _theme_cache
    _theme_cache = None


def get_bold_color(name: str) -> str:
    """Get a theme color with bold modifier.

    Args:
        name: The color name

    Returns:
        The color value prefixed with "bold " if not already bold
    """
    color = get_color(name)
    if color.startswith("bold "):
        return color
    return f"bold {color}"


# Convenience constants for direct import
# These are evaluated at import time with defaults
# For dynamic config-based colors, use get_color() instead
USER_COLOR = DEFAULT_THEME_COLORS["user"]
ASSISTANT_COLOR = DEFAULT_THEME_COLORS["assistant"]
SYSTEM_COLOR = DEFAULT_THEME_COLORS["system"]
ERROR_COLOR = DEFAULT_THEME_COLORS["error"]
TOOL_COLOR = DEFAULT_THEME_COLORS["tool"]
BANNER_COLOR = DEFAULT_THEME_COLORS["banner"]
