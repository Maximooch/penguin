"""Tools module for Penguin system."""

# Only import the essential ToolManager class directly
# Other imports will be lazy-loaded when needed
from .tool_manager import ToolManager

# DO NOT directly import other modules or classes here - they should be lazy loaded
# Keep the list of exports so the API remains the same
__all__ = [
    "ToolManager",
    "ToolRegistry",
    "browser_manager",
    "initialize_browser",
    "BrowserNavigationTool",
    "BrowserInteractionTool",
    "BrowserScreenshotTool",
    # PyDoll browser tools
    "pydoll_browser_manager",
    "initialize_pydoll_browser",
    "PyDollBrowserNavigationTool",
    "PyDollBrowserInteractionTool",
    "PyDollBrowserScreenshotTool",
    "create_folder",
    "create_file",
    "write_to_file",
    "read_file",
    "list_files",
    "encode_image_to_base64",
    "find_file",
]

# Lazy loading mechanism for tool imports
def __getattr__(name):
    """Lazily import tools when they're first accessed."""
    if name in __all__:
        if name == "ToolRegistry":
            from .registry import ToolRegistry
            return ToolRegistry
        elif name in ["create_folder", "create_file", "write_to_file", "read_file", "list_files", "encode_image_to_base64", "find_file"]:
            from .core.support import (
                create_folder, create_file, write_to_file, read_file, 
                list_files, encode_image_to_base64, find_file
            )
            return locals()[name]
        elif name in ["browser_manager", "initialize_browser", "BrowserNavigationTool", "BrowserInteractionTool", "BrowserScreenshotTool"]:
            from .browser_tools import (
                browser_manager, initialize_browser, 
                BrowserNavigationTool, BrowserInteractionTool, BrowserScreenshotTool
            )
            return locals()[name]
        elif name in ["pydoll_browser_manager", "initialize_pydoll_browser", "PyDollBrowserNavigationTool", "PyDollBrowserInteractionTool", "PyDollBrowserScreenshotTool"]:
            from .pydoll_tools import (
                pydoll_browser_manager, initialize_pydoll_browser,
                PyDollBrowserNavigationTool, PyDollBrowserInteractionTool, PyDollBrowserScreenshotTool
            )
            return locals()[name]
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
