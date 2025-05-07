"""Tools module for Penguin system."""

from .core.support import (
    create_file,
    create_folder,
    encode_image_to_base64,
    find_file,
    list_files,
    read_file,
    write_to_file,
)
from .tool_manager import ToolManager

# from .code_visualizer import CodeVisualizer
# from .visualize import visualize

# Import the new PyDoll browser tools
from penguin.tools.pydoll_tools import (
    pydoll_browser_manager, 
    PyDollBrowserNavigationTool, 
    PyDollBrowserInteractionTool, 
    PyDollBrowserScreenshotTool,
    initialize_browser as initialize_pydoll_browser
)

# Keep existing imports
from penguin.tools.browser_tools import (
    browser_manager,
    initialize_browser,
    BrowserNavigationTool,
    BrowserInteractionTool,
    BrowserScreenshotTool
)

from penguin.tools.registry import ToolRegistry

__all__ = [
    "ToolManager",
    "ToolRegistry",
    "browser_manager",
    "initialize_browser",
    "BrowserNavigationTool",
    "BrowserInteractionTool",
    "BrowserScreenshotTool",
    # Add PyDoll browser tools
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
