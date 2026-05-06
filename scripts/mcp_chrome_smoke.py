#!/usr/bin/env python3
"""Smoke test Penguin's MCP host path with Chrome DevTools MCP.

This script exercises Penguin consuming an external MCP server, not Penguin's own
MCP server surface. It starts `chrome-devtools-mcp` over stdio, navigates to a
Wikipedia page, verifies title/URL with JavaScript evaluation, and stores a
screenshot under /tmp by default.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Optional

from penguin.tools.providers.mcp import MCPToolProvider


def _build_config(args: argparse.Namespace) -> dict[str, Any]:
    chrome_args = [
        "-y",
        args.package,
        "--no-usage-statistics",
        "--no-update-checks",
        "--slim",
        "--isolated",
        "--viewport",
        args.viewport,
    ]
    if args.headless:
        chrome_args.append("--headless")
    return {
        "mcp": {
            "enabled": True,
            "servers": {
                "chrome-devtools": {
                    "command": "npx",
                    "args": chrome_args,
                    "startup_timeout_sec": args.startup_timeout,
                    "tool_timeout_sec": args.tool_timeout,
                    "output_token_limit": args.output_token_limit,
                }
            },
        }
    }


def _call(provider: MCPToolProvider, tool_name: str, arguments: dict[str, Any]) -> Any:
    payload = json.loads(provider.execute_tool(tool_name, arguments))
    if payload.get("error"):
        raise RuntimeError(payload)
    return payload["result"]


def _flatten(value: Any) -> Iterable[Any]:
    queue = [value]
    while queue:
        item = queue.pop(0)
        yield item
        if isinstance(item, dict):
            queue.extend(item.values())
        elif isinstance(item, list):
            queue.extend(item)


def _copy_screenshot(result: Any, destination: Path) -> Path:
    for item in _flatten(result):
        if isinstance(item, dict):
            data = item.get("data")
            mime = item.get("mimeType") or item.get("mime_type")
            if isinstance(data, str) and (mime or item.get("type") == "image"):
                destination.write_bytes(base64.b64decode(data))
                return destination
            text = item.get("text")
            if isinstance(text, str):
                source = Path(text)
                if source.exists() and source.suffix.lower() == ".png":
                    destination.write_bytes(source.read_bytes())
                    return destination
        elif isinstance(item, str):
            source = Path(item)
            if source.exists() and source.suffix.lower() == ".png":
                destination.write_bytes(source.read_bytes())
                return destination
    raise RuntimeError("Chrome MCP screenshot result did not include image data or a PNG path.")


def _text_content(result: Any) -> Optional[str]:
    for item in _flatten(result):
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            return item["text"]
    return None


def _visit_and_capture(
    provider: MCPToolProvider,
    url: str,
    output_path: Path,
) -> dict[str, Any]:
    navigation = _call(provider, "mcp__chrome_devtools__navigate", {"url": url})
    title = _call(provider, "mcp__chrome_devtools__evaluate", {"script": "document.title"})
    href = _call(provider, "mcp__chrome_devtools__evaluate", {"script": "location.href"})
    screenshot = _call(provider, "mcp__chrome_devtools__screenshot", {})
    saved = _copy_screenshot(screenshot, output_path)
    return {
        "requested_url": url,
        "resolved_url": _text_content(href),
        "title": _text_content(title),
        "navigation": _text_content(navigation),
        "screenshot": str(saved),
        "bytes": saved.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--package", default="chrome-devtools-mcp@latest")
    parser.add_argument("--viewport", default="1280x900")
    parser.add_argument("--startup-timeout", type=int, default=120)
    parser.add_argument("--tool-timeout", type=int, default=180)
    parser.add_argument("--output-token-limit", type=int, default=20_000_000)
    parser.add_argument("--no-headless", action="store_false", dest="headless")
    parser.add_argument("--include-random", action="store_true")
    parser.set_defaults(headless=True)
    args = parser.parse_args()

    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else Path(tempfile.mkdtemp(prefix="penguin-mcp-chrome-smoke-"))
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    provider = MCPToolProvider(_build_config(args))
    try:
        schemas = provider.get_tool_schemas()
        names = {schema.get("name") for schema in schemas}
        required = {
            "mcp__chrome_devtools__navigate",
            "mcp__chrome_devtools__evaluate",
            "mcp__chrome_devtools__screenshot",
        }
        missing = sorted(required - names)
        if missing:
            raise RuntimeError(f"Missing Chrome MCP tools: {missing}")

        results = [
            _visit_and_capture(
                provider,
                "https://en.wikipedia.org/wiki/Penguin",
                output_dir / "wikipedia-penguin.png",
            )
        ]
        if args.include_random:
            results.append(
                _visit_and_capture(
                    provider,
                    "https://en.wikipedia.org/wiki/Special:Random",
                    output_dir / "wikipedia-random.png",
                )
            )
        print(json.dumps({"status": "ok", "results": results}, indent=2))
        return 0
    finally:
        provider.close()


if __name__ == "__main__":
    sys.exit(main())
