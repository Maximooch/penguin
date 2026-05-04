#!/usr/bin/env python3
"""Run Penguin as an MCP stdio server exposing safe read-only tools."""

from __future__ import annotations

import argparse
import sys

import asyncio

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
    parser.add_argument(
        "--no-pm-tools",
        action="store_true",
        help="Disable default Penguin PM MCP tools.",
    )
    parser.add_argument(
        "--no-blueprint-tools",
        action="store_true",
        help="Disable default Penguin Blueprint MCP tools.",
    )
    parser.add_argument(
        "--allow-runtime-tools",
        action="store_true",
        help="Expose opt-in RunMode readiness tools. Start/cancel remain unavailable in Slice 3A.",
    )
    parser.add_argument(
        "--minimal-core",
        action="store_true",
        help="Use a bare ToolManager only; PM tools require full PenguinCore.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_stdio_logging()
    core = None
    if args.minimal_core:
        tool_manager = ToolManager(
            config, lambda *_args, **_kwargs: None, fast_startup=True
        )
    else:
        from penguin.core import PenguinCore

        core = asyncio.run(
            PenguinCore.create(show_progress=False, fast_startup=True)
        )
        tool_manager = core.tool_manager

    server = build_penguin_mcp_server(
        tool_manager,
        name=args.name,
        allow_tools=args.allow_tool,
        deny_patterns=args.deny_pattern,
        core=core,
        expose_pm_tools=not args.no_pm_tools,
        expose_blueprint_tools=not args.no_blueprint_tools,
        expose_runtime_tools=args.allow_runtime_tools,
    )
    try:
        server.run("stdio")
    except MCPServerUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
