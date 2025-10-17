"""MCP integration package for Penguin.

Contains server and client adapters for exposing Penguin tools via the
Model Context Protocol and consuming remote MCP servers as virtual tools.
"""

from .adapter import MCPAdapter, MCPToolImplementation
from .echo import start_server

__all__ = ["MCPAdapter", "MCPToolImplementation", "start_server"] 