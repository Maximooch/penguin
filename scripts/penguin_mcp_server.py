#!/usr/bin/env python3
"""Run Penguin as an MCP stdio server exposing safe read-only tools."""

from __future__ import annotations

import argparse
import sys

from penguin.config import config
from penguin.integrations.mcp.server import (
    MCPServerUnavailableError,
    build_penguin_mcp_server,
    configure_stdio_logging,
)
from penguin.tools.tool_manager import ToolManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Penguin's MCP stdio server.")
    parser.add_argument("--name", default="penguin", help="MCP server name")
    parser.add_argument(
        "--allow-tool",
        action="append",
        default=None,
        help="Tool/pattern to expose; repeatable. Defaults to safe read-only tools.",
    )
    parser.add_argument(
        "--deny-pattern",
        action="append",
        default=None,
        help="Tool/pattern to deny; repeatable. Defaults deny dangerous tools.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_stdio_logging()
    tool_manager = ToolManager(config, lambda *_args, **_kwargs: None, fast_startup=True)
    server = build_penguin_mcp_server(
        tool_manager,
        name=args.name,
        allow_tools=args.allow_tool,
        deny_patterns=args.deny_pattern,
    )
    try:
        server.run("stdio")
    except MCPServerUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
