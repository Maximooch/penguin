"""Command dispatcher for Penguin CLI and TUI entrypoints.

This module provides a single front door (`penguin`) that defaults to the
Penguin TUI while preserving explicit routes for headless CLI workflows.
"""

from __future__ import annotations

import sys
from typing import Sequence

_FORCE_TUI_ALIASES = {"tui", "ptui"}
_FORCE_CLI_ALIASES = {"cli", "headless"}

_CLI_COMMANDS = {
    "agent",
    "chat",
    "config",
    "coord",
    "help",
    "msg",
    "permissions",
    "perf-test",
    "perf_test",
    "profile",
    "project",
}

_CLI_FLAGS = {
    "-c",
    "-h",
    "-p",
    "-v",
    "--247",
    "--continuous",
    "--continue",
    "--description",
    "--fast-startup",
    "--help",
    "--no-streaming",
    "--output-format",
    "--project",
    "--prompt",
    "--resume",
    "--root",
    "--run",
    "--time-limit",
    "--version",
    "--workspace",
    "-V",
}

_TUI_FLAGS = {
    "--no-web-autostart",
    "--url",
    "--use-global-opencode",
    "--web-timeout",
}


def _normalize_argv(argv: Sequence[str] | None) -> list[str]:
    if argv is None:
        return list(sys.argv[1:])
    return list(argv)


def _first_arg(args: Sequence[str]) -> str:
    if not args:
        return ""
    return str(args[0] or "").strip().lower()


def _routes_to_cli(args: Sequence[str]) -> bool:
    first = _first_arg(args)
    if not first:
        return False

    if first in _FORCE_CLI_ALIASES:
        return True
    if first in _FORCE_TUI_ALIASES:
        return False
    if first in _CLI_COMMANDS:
        return True

    if first.startswith("-"):
        if first in _TUI_FLAGS:
            return False
        if first in _CLI_FLAGS:
            return True
        # Preserve prior CLI behavior for unknown top-level flags.
        return True

    return False


def _strip_alias(args: Sequence[str]) -> list[str]:
    if not args:
        return []

    first = _first_arg(args)
    if first in _FORCE_TUI_ALIASES or first in _FORCE_CLI_ALIASES:
        return list(args[1:])
    return list(args)


def _to_exit_code(value: object) -> int:
    if isinstance(value, int):
        return value
    if value is None:
        return 0
    return 1


def main_cli(argv: Sequence[str] | None = None) -> int:
    """Run the headless Penguin CLI directly."""
    args = _normalize_argv(argv)
    from .cli import app as cli_app

    try:
        cli_app(args=list(args), prog_name="penguin-cli")
    except SystemExit as exc:
        return _to_exit_code(exc.code)
    return 0


def main_tui(argv: Sequence[str] | None = None) -> int:
    """Run the Penguin TUI launcher directly."""
    from .opencode_launcher import main as launcher_main

    return _to_exit_code(launcher_main(_normalize_argv(argv)))


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch `penguin` invocations to TUI or headless CLI."""
    args = _normalize_argv(argv)
    first = _first_arg(args)

    if first in _FORCE_TUI_ALIASES:
        return main_tui(_strip_alias(args))
    if first in _FORCE_CLI_ALIASES:
        return main_cli(_strip_alias(args))
    if _routes_to_cli(args):
        return main_cli(args)
    return main_tui(args)


__all__ = ["main", "main_cli", "main_tui"]
