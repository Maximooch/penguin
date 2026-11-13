"""Inventory server diagnostics locally without exporting message payloads.

Only fixed categories, logger names and counts are retained. This is a triage
index, not an incident counter: log rotation, repeated errors, and embedded
verbatim log headers can all duplicate observations.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

HEADER = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} - "
    r"(?P<logger>[a-zA-Z_][\w.]*) - (?P<level>WARNING|ERROR|CRITICAL) - "
    r"(?P<message>.*)$"
)


def classify(logger: str, message: str) -> str:
    """Classify known symptoms without retaining arbitrary user-controlled text."""
    if "No space left on device" in message:
        return "storage_full"
    if logger == "penguin.core" and "stream.finalize.scope_miss" in message:
        return "stream_scope_miss"
    if logger == "penguin.core" and "[WALLET_GUARD]" in message:
        return "empty_response_guard"
    if logger == "penguin.engine" and "[WALLET_GUARD]" in message:
        return "empty_response_loop_guard"
    if logger == "penguin.system.session_manager":
        for prefix, category in (
            ("Error loading session", "session_load_failure"),
            ("Could not load session", "session_recovery"),
            ("Error saving session index", "session_index_save_failure"),
            ("Error saving session", "session_save_failure"),
        ):
            if message.startswith(prefix):
                return category
    if logger == "penguin.tools.process_runtime" and message.startswith(
        "Process capture failed"
    ):
        return "process_capture_failure"
    if logger == "penguin.system.checkpoint_manager" and message.startswith(
        "Error in checkpoint worker"
    ):
        return "checkpoint_worker_failure"
    if logger == "penguin.llm.adapters.openai" and "Sanitized Codex replay" in message:
        return "provider_replay_sanitized"
    if logger == "penguin.web.services.session_view":
        return "session_view_fallback"
    if logger == "penguin.web.middleware.auth" and message.startswith("Unauthorized"):
        return "unauthorized_request"
    if logger.startswith("penguin.llm."):
        return "provider_other"
    return "other"


def inventory(root: Path) -> dict[str, Any]:
    """Stream a snapshot of regular server log files, excluding symbolic links.

    Reads at most each file's initial byte size: an actively growing log cannot
    make this scan run forever. I/O errors propagate rather than imply coverage.
    """
    categories: Counter[str] = Counter()
    levels: Counter[str] = Counter()
    files = 0
    scanned_bytes = 0
    ignored_lines = 0
    for path in sorted(root.glob("penguin-web-*.txt*")):
        if path.is_symlink() or not path.is_file():
            continue
        remaining = path.stat().st_size
        files += 1
        with path.open("rb") as handle:
            while remaining:
                raw = handle.readline(remaining)
                if not raw:
                    break
                remaining -= len(raw)
                scanned_bytes += len(raw)
                match = HEADER.match(raw.decode("utf-8", errors="replace"))
                if match is None:
                    ignored_lines += 1
                    continue
                logger = match["logger"]
                if not (logger.startswith("penguin.") or logger == "uvicorn.error"):
                    ignored_lines += 1
                    continue
                levels[match["level"]] += 1
                categories[classify(logger, match["message"])] += 1
    return {
        "files": files,
        "scanned_bytes": scanned_bytes,
        "ignored_lines": ignored_lines,
        "diagnostic_records": sum(levels.values()),
        "levels": dict(sorted(levels.items())),
        "categories": dict(sorted(categories.items())),
    }


def main() -> None:
    """Print aggregate JSON only; never copy raw logs into the repository."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    if not args.directory.is_dir():
        parser.error("directory must exist")
    print(json.dumps(inventory(args.directory), indent=2))


if __name__ == "__main__":
    main()
