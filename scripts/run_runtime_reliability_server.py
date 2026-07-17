#!/usr/bin/env python3
"""Start an isolated Penguin reliability server on 127.0.0.1:8080.

Run with:

    uv run python scripts/run_runtime_reliability_server.py

The command creates a unique workspace under ``~/.penguin/test-runtimes`` by
default. It never kills the current port owner and refuses to start when 8080 is
already occupied.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from typing import Sequence

from penguin.web.runtime_storage import (
    build_isolated_test_environment,
    resolve_runtime_storage,
)


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-directory",
        type=Path,
        help="Parent directory for the unique test workspace",
    )
    parser.add_argument(
        "--run-id",
        help="Optional deterministic workspace name (defaults to a unique id)",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Print the resolved isolated layout without starting a server",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable uvicorn reload inside the isolated test runtime",
    )
    return parser


def _port_available(host: str, port: int) -> bool:
    """Return whether ``host:port`` can be bound without disturbing an owner."""

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Resolve an isolated environment and replace this process with penguin-web."""

    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    environment = build_isolated_test_environment(
        base_directory=args.base_directory,
        run_id=args.run_id,
    )
    if args.debug:
        environment["DEBUG"] = "true"
    layout = resolve_runtime_storage(
        host=environment["HOST"],
        port=int(environment["PORT"]),
        environ=environment,
    )
    print(json.dumps(layout.to_diagnostics(), indent=2, sort_keys=True), flush=True)

    if args.describe:
        return 0
    if not _port_available(layout.host, layout.port):
        print(
            "Refusing to start: 127.0.0.1:8080 is already occupied. "
            "This command will not stop or replace its owner.",
            file=sys.stderr,
        )
        return 1

    os.execve(
        sys.executable,
        [sys.executable, "-m", "penguin.web.server"],
        environment,
    )
    return 1  # pragma: no cover - os.execve only returns by raising


if __name__ == "__main__":
    raise SystemExit(main())
