#!/usr/bin/env python3
"""Smoke test Penguin's MCP control-plane tools over STDIO.

This script validates the MCP server path, not just internal Python calls. It
starts `scripts/penguin_mcp_server.py` in an isolated temporary workspace, then
uses the official MCP Python SDK to:

1. list tools,
2. create a project,
3. dry-run Blueprint sync,
4. apply Blueprint sync,
5. list tasks,
6. query Blueprint status.

Run with a Python environment that has Penguin's MCP extra installed, e.g.:

    uv run --python 3.11 --extra mcp python scripts/mcp_control_plane_smoke.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except ImportError as exc:  # pragma: no cover - developer environment guard
    raise SystemExit(
        "MCP SDK is not installed. Run with: "
        "uv run --python 3.11 --extra mcp python scripts/mcp_control_plane_smoke.py"
    ) from exc


BLUEPRINT_CONTENT = """version: 1
name: MCP Control Plane Smoke
summary: Validate Penguin MCP PM and Blueprint tools.
tasks:
  - id: setup
    title: Prepare smoke fixture
    description: Create a deterministic project/task fixture.
    acceptance_criteria:
      - Fixture task exists.
  - id: verify
    title: Verify smoke fixture
    description: Confirm Blueprint status sees the synced DAG.
    depends_on:
      - setup
    acceptance_criteria:
      - Blueprint status reports synced tasks.
"""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_server_command() -> List[str]:
    return [
        sys.executable,
        str(_repo_root() / "scripts" / "penguin_mcp_server.py"),
    ]


def _json_from_result(result: Any) -> Dict[str, Any]:
    """Extract a JSON object from an MCP tool result."""
    content = getattr(result, "content", None) or []
    texts: List[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            texts.append(text)
    if not texts:
        return {"raw_result": repr(result)}
    combined = "\n".join(texts).strip()
    try:
        parsed = json.loads(combined)
    except json.JSONDecodeError:
        return {"text": combined}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def _tool_names(tools: Iterable[Any]) -> List[str]:
    return sorted(str(getattr(tool, "name", "")) for tool in tools)


def _require_tools(names: Sequence[str], required: Sequence[str]) -> None:
    missing = [name for name in required if name not in names]
    if missing:
        raise RuntimeError(
            "Penguin MCP server did not expose required tools: "
            f"{missing}; available={names}"
        )


async def _run_smoke(server_command: Sequence[str], keep_workspace: bool) -> Dict[str, Any]:
    if not server_command:
        raise ValueError("server_command must not be empty")

    with tempfile.TemporaryDirectory(prefix="penguin-mcp-smoke-") as tmp:
        workspace = Path(tmp) / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        project_root = Path(tmp) / "project"
        project_root.mkdir(parents=True, exist_ok=True)
        blueprint_path = project_root / "blueprint.yml"
        blueprint_path.write_text(BLUEPRINT_CONTENT, encoding="utf-8")

        env = dict(os.environ)
        env["PENGUIN_WORKSPACE"] = str(workspace)

        params = StdioServerParameters(
            command=server_command[0],
            args=list(server_command[1:]),
            env=env,
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                names = _tool_names(listed.tools)
                _require_tools(
                    names,
                    [
                        "penguin_pm_create_project",
                        "penguin_blueprint_sync",
                        "penguin_pm_list_tasks",
                        "penguin_blueprint_status",
                    ],
                )

                project_result = _json_from_result(
                    await session.call_tool(
                        "penguin_pm_create_project",
                        {
                            "name": "MCP Control Plane Smoke",
                            "description": "Created by MCP control-plane smoke.",
                            "workspace_path": str(project_root),
                        },
                    )
                )
                project_id = project_result.get("project", {}).get("id") or project_result.get("id")
                if not project_id:
                    raise RuntimeError(f"Project creation did not return project_id: {project_result}")

                dry_run = _json_from_result(
                    await session.call_tool(
                        "penguin_blueprint_sync",
                        {
                            "blueprint_path": str(blueprint_path),
                            "project_id": project_id,
                            "dry_run": True,
                        },
                    )
                )
                if dry_run.get("status") != "dry_run":
                    raise RuntimeError(f"Expected dry_run status, got: {dry_run}")

                sync = _json_from_result(
                    await session.call_tool(
                        "penguin_blueprint_sync",
                        {
                            "blueprint_path": str(blueprint_path),
                            "project_id": project_id,
                            "dry_run": False,
                            "create_missing": True,
                            "update_existing": False,
                        },
                    )
                )
                if sync.get("status") not in {"synced", "success"}:
                    raise RuntimeError(f"Expected sync success, got: {sync}")

                tasks = _json_from_result(
                    await session.call_tool(
                        "penguin_pm_list_tasks",
                        {"project_id": project_id},
                    )
                )
                task_items = tasks.get("tasks", [])
                if len(task_items) < 2:
                    raise RuntimeError(f"Expected at least 2 synced tasks, got: {tasks}")

                status = _json_from_result(
                    await session.call_tool(
                        "penguin_blueprint_status",
                        {"project_id": project_id},
                    )
                )
                status_project_id = (
                    status.get("project_id")
                    or status.get("project", {}).get("id")
                    or status.get("stats", {}).get("project_id")
                )
                if status_project_id != project_id:
                    raise RuntimeError(f"Blueprint status returned wrong project: {status}")

                summary = {
                    "status": "passed",
                    "workspace": str(workspace),
                    "project_root": str(project_root),
                    "project_id": project_id,
                    "tool_count": len(names),
                    "synced_task_count": len(task_items),
                    "dry_run": dry_run,
                    "sync": sync,
                    "blueprint_status": status,
                }

        if keep_workspace:
            # TemporaryDirectory deletes on context exit; copy-out would be needed for full preservation.
            summary["note"] = "--keep-workspace is informational; temp cleanup still occurs."
        return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Include workspace paths in output for debugging.",
    )
    parser.add_argument(
        "server_command",
        nargs=argparse.REMAINDER,
        help="Optional server command after '--'. Defaults to current Python running scripts/penguin_mcp_server.py.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server_command = list(args.server_command)
    if server_command and server_command[0] == "--":
        server_command = server_command[1:]
    if not server_command:
        server_command = _default_server_command()

    summary = asyncio.run(_run_smoke(server_command, keep_workspace=args.keep_workspace))
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
