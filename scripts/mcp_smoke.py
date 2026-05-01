#!/usr/bin/env python3
"""Smoke-test Penguin's MCP host path against one stdio MCP server.

Example:
  uv run --extra mcp python scripts/mcp_smoke.py \
    --name everything \
    --command npx \
    --startup-timeout 60 \
    --args -y @modelcontextprotocol/server-everything stdio
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from penguin.integrations.mcp.config import MCPServerConfig
from penguin.integrations.mcp.manager import MCPClientManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test one stdio MCP server.")
    parser.add_argument("--name", default="smoke", help="MCP server name")
    parser.add_argument("--command", required=True, help="Server command, e.g. npx")
    parser.add_argument(
        "--arg",
        action="append",
        default=[],
        help="Server arg; repeatable; use --arg=-y for dash-prefixed values",
    )
    parser.add_argument(
        "--args",
        nargs=argparse.REMAINDER,
        default=None,
        help="All remaining values are server args; keep this last",
    )
    parser.add_argument("--call", help="Optional discovered public tool name to call")
    parser.add_argument("--arguments", default="{}", help="JSON arguments for --call")
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--tool-timeout", type=float, default=120.0)
    parser.add_argument(
        "--no-schemas",
        action="store_true",
        help="Only print status and optional call result",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = MCPServerConfig(
        name=args.name,
        command=args.command,
        args=list(args.args if args.args is not None else args.arg),
        startup_timeout_sec=args.startup_timeout,
        tool_timeout_sec=args.tool_timeout,
    )
    manager = MCPClientManager([server])
    tools = manager.list_tools_sync()
    print(json.dumps(manager.status(), indent=2, sort_keys=True))
    if not args.no_schemas:
        print(
            json.dumps(
                [tool.to_penguin_schema() for tool in tools],
                indent=2,
                sort_keys=True,
            )
        )

    if args.call:
        arguments: dict[str, Any] = json.loads(args.arguments)
        result = manager.call_tool_sync(args.call, arguments)
        print(json.dumps(result, indent=2, sort_keys=True))

    manager.close_sync()


if __name__ == "__main__":
    main()
