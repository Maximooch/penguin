"""System status helpers for path, VCS, formatter, and LSP endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from penguin.config import WORKSPACE_PATH

logger = logging.getLogger(__name__)
_LAST_BRANCH_KEY: str | None = None
_VCS_EMIT_TASK: asyncio.Task | None = None
_VCS_WATCH_TASK: asyncio.Task | None = None


def _run_git(args: Iterable[str], cwd: str) -> str:
    """Run a git command and return stdout, or empty string on failure."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception as exc:
        logger.debug("git command failed", exc_info=exc)
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _detect_extensions(root: str, max_files: int = 5000) -> set[str]:
    """Detect file extensions present under a root path."""
    found: set[str] = set()
    seen = 0
    skip_dirs = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [item for item in dirnames if item not in skip_dirs]
        for filename in filenames:
            seen += 1
            if seen > max_files:
                return found
            suffix = Path(filename).suffix.lower()
            if suffix:
                found.add(suffix)
    return found


def get_path_info(core: Any) -> dict[str, str]:
    """Return OpenCode-compatible path information."""
    runtime = getattr(core, "runtime_config", None)
    workspace = getattr(runtime, "workspace_root", None) or WORKSPACE_PATH
    project = getattr(runtime, "project_root", None) or workspace
    directory = getattr(runtime, "active_root", None) or project

    config_candidate = Path(project) / ".penguin"
    config_dir = str(config_candidate) if config_candidate.exists() else str(project)

    worktree = _run_git(["rev-parse", "--show-toplevel"], str(directory))
    if not worktree:
        worktree = str(project)

    return {
        "home": str(Path.home()),
        "state": str(workspace),
        "config": config_dir,
        "worktree": worktree,
        "directory": str(directory),
    }


def get_vcs_info(core: Any, *, emit_events: bool = True) -> dict[str, Any]:
    """Return real VCS info for the current worktree."""
    global _LAST_BRANCH_KEY
    path_info = get_path_info(core)
    directory = path_info["directory"]
    worktree = _run_git(["rev-parse", "--show-toplevel"], directory)
    if not worktree:
        return {
            "vcs": "none",
            "root": "",
            "worktree": "",
            "branch": "",
            "detached": False,
            "head": "",
            "upstream": "",
            "dirty": False,
            "ahead": 0,
            "behind": 0,
            "error": "not a git repository",
        }

    common_dir = _run_git(
        ["rev-parse", "--path-format=absolute", "--git-common-dir"], directory
    )
    root = ""
    if common_dir:
        common_path = Path(common_dir).resolve()
        root = (
            str(common_path.parent) if common_path.name == ".git" else str(common_path)
        )
    if not root:
        root = worktree

    status_porcelain = _run_git(["status", "--porcelain"], worktree)
    dirty = bool(status_porcelain)

    branch = _run_git(["symbolic-ref", "--short", "HEAD"], worktree)
    detached = not bool(branch)
    head = _run_git(["rev-parse", "--short", "HEAD"], worktree)
    if detached:
        branch = ""

    upstream = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        worktree,
    )

    ahead = 0
    behind = 0
    ahead_behind = (
        _run_git(
            ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"], worktree
        )
        if upstream
        else ""
    )
    if ahead_behind and len(ahead_behind.split()) == 2:
        parts = ahead_behind.split()
        try:
            behind = int(parts[0])
            ahead = int(parts[1])
        except ValueError:
            behind = 0
            ahead = 0

    branch_key = f"{worktree}|{branch}|{head}|{detached}"
    if emit_events and branch_key != _LAST_BRANCH_KEY:
        _LAST_BRANCH_KEY = branch_key
        try:
            loop = asyncio.get_running_loop()
            global _VCS_EMIT_TASK
            _VCS_EMIT_TASK = loop.create_task(
                core.event_bus.emit(
                    "opencode_event",
                    {
                        "type": "vcs.branch.updated",
                        "properties": {
                            "branch": branch,
                            "detached": detached,
                            "head": head,
                            "worktree": worktree,
                        },
                    },
                )
            )
        except Exception:
            logger.debug("Unable to emit vcs.branch.updated", exc_info=True)

    return {
        "vcs": "git",
        "root": root,
        "worktree": worktree,
        "branch": branch,
        "detached": detached,
        "head": head,
        "upstream": upstream,
        "dirty": dirty,
        "ahead": ahead,
        "behind": behind,
        "error": "",
    }


async def _vcs_watch_loop(core: Any, interval_seconds: float) -> None:
    """Watch for VCS branch changes and emit events."""
    while True:
        try:
            get_vcs_info(core, emit_events=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("VCS watch loop iteration failed", exc_info=True)
        await asyncio.sleep(interval_seconds)


def start_vcs_watcher(core: Any, interval_seconds: float = 2.0) -> None:
    """Start a background watcher for VCS state changes."""
    global _VCS_WATCH_TASK
    if _VCS_WATCH_TASK and not _VCS_WATCH_TASK.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _VCS_WATCH_TASK = loop.create_task(_vcs_watch_loop(core, interval_seconds))


async def stop_vcs_watcher() -> None:
    """Stop background VCS watcher if running."""
    global _VCS_WATCH_TASK
    if not _VCS_WATCH_TASK or _VCS_WATCH_TASK.done():
        return
    _VCS_WATCH_TASK.cancel()
    try:
        await _VCS_WATCH_TASK
    except asyncio.CancelledError:
        pass
    _VCS_WATCH_TASK = None


def get_formatter_status(core: Any) -> list[dict[str, Any]]:
    """Return formatter availability for languages present in the workspace."""
    directory = get_path_info(core)["directory"]
    extensions = _detect_extensions(directory)

    formatters = [
        {"name": "ruff", "extensions": [".py"], "command": "ruff"},
        {"name": "black", "extensions": [".py"], "command": "black"},
        {
            "name": "prettier",
            "extensions": [".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".md"],
            "command": "prettier",
        },
        {
            "name": "biome",
            "extensions": [".js", ".jsx", ".ts", ".tsx", ".json"],
            "command": "biome",
        },
        {"name": "gofmt", "extensions": [".go"], "command": "gofmt"},
        {"name": "rustfmt", "extensions": [".rs"], "command": "rustfmt"},
    ]

    result: list[dict[str, Any]] = []
    for item in formatters:
        command_available = shutil.which(item["command"]) is not None
        has_language = bool(set(item["extensions"]) & extensions)
        if not has_language:
            continue
        result.append(
            {
                "name": item["name"],
                "extensions": item["extensions"],
                "enabled": bool(command_available),
            }
        )
    return result


def get_lsp_status(core: Any) -> list[dict[str, str]]:
    """Return LSP status for languages detected in the workspace."""
    directory = get_path_info(core)["directory"]
    extensions = _detect_extensions(directory)

    servers = [
        {
            "id": "pyright",
            "name": "pyright-langserver",
            "extensions": [".py"],
            "commands": ["pyright-langserver", "pylsp", "jedi-language-server"],
        },
        {
            "id": "typescript",
            "name": "typescript-language-server",
            "extensions": [".ts", ".tsx", ".js", ".jsx"],
            "commands": ["typescript-language-server"],
        },
        {
            "id": "rust",
            "name": "rust-analyzer",
            "extensions": [".rs"],
            "commands": ["rust-analyzer"],
        },
        {
            "id": "go",
            "name": "gopls",
            "extensions": [".go"],
            "commands": ["gopls"],
        },
        {
            "id": "c-family",
            "name": "clangd",
            "extensions": [".c", ".cc", ".cpp", ".h", ".hpp"],
            "commands": ["clangd"],
        },
    ]

    result: list[dict[str, str]] = []
    for item in servers:
        has_language = bool(set(item["extensions"]) & extensions)
        if not has_language:
            continue
        available = any(shutil.which(command) for command in item["commands"])
        result.append(
            {
                "id": item["id"],
                "name": item["name"],
                "root": ".",
                "status": "connected" if available else "error",
            }
        )
    return result
