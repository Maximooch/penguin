"""Shared Rich presentation primitives for Python CLI surfaces."""

from __future__ import annotations

from typing import Any

__all__ = ["CLI_PANEL_PADDING", "print_ascii_banner"]

CLI_PANEL_PADDING = None

PENGUIN_ASCII_BANNER = r"""
ooooooooo.                                                 o8o              
`888   `Y88.                                               `"'              
 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo  ooo. .oo.   
 888ooo88P'  d88' `88b `888P"Y88b  888' `88b  `888  `888  `888  `888P"Y88b  
 888         888ooo888  888   888  888   888   888   888   888   888   888  
 888         888    .o  888   888  `88bod8P'   888   888   888   888   888  
o888o        `Y8bod8P' o888o o888o `8oooooo.   `V88V"V8P' o888o o888o o888o 
                                   d"     YD                                
                                   "Y88888P'                                
          """

_banner_printed = False


def print_ascii_banner(console: Any, *, force: bool = False) -> None:
    """Print the Penguin banner once per process unless forced."""

    global _banner_printed
    if _banner_printed and not force:
        return
    try:
        from penguin.cli.theme import get_color

        banner_style = get_color("banner", "bold cyan")
    except ImportError:
        banner_style = "bold cyan"
    console.print(PENGUIN_ASCII_BANNER, style=banner_style)
    _banner_printed = True
