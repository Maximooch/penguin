"""Parse Penguin server logs into structured data.

The server logs are rotated text files under `server-logs/` in the workspace.
Each line is a Python log record. Key loggers for observability:

- penguin.engine: engine.llm_attempt.done, engine.context.snapshot, engine.llm_step.*
- penguin.tools.runtime: tool.exec.done, tool.exec.start, tool.batch.schedule
- penguin.llm.api_client: HTTP request/response info
- penguin.llm.adapters.*: provider-specific gateway info

Log line format:
  {timestamp} - {logger} - {level} - {message}

The message is a key=value format with spaces separating fields.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from penguin.dashboard.queries.runtime_events import get_workspace

# ── cache database ─────────────────────────────────────────────────────

CACHE_DIR = Path(__file__).resolve().parent.parent / ".log_cache"
CACHE_DB = str(CACHE_DIR / "server_log_cache.db")


def _ensure_cache_db():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS log_cache (
            key TEXT PRIMARY KEY,
            data_json TEXT NOT NULL,
            cached_at INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _cache_get(key: str) -> list[dict[str, Any]] | None:
    conn = _ensure_cache_db()
    row = conn.execute(
        "SELECT data_json FROM log_cache WHERE key = ?", (key,)
    ).fetchone()
    if row:
        return json.loads(row[0])
    return None


def _cache_set(key: str, data: list[dict[str, Any]]):
    conn = _ensure_cache_db()
    conn.execute(
        "INSERT OR REPLACE INTO log_cache (key, data_json, cached_at) VALUES (?, ?, ?)",
        (key, json.dumps(data), int(datetime.now().timestamp())),
    )
    conn.commit()


def _cache_clear():
    conn = _ensure_cache_db()
    conn.execute("DELETE FROM log_cache")
    conn.commit()


# ── log file discovery ─────────────────────────────────────────────────


def get_all_log_files() -> list[str]:
    """Return sorted list of server log file paths, newest first."""
    logs_dir = Path(get_workspace()) / "server-logs"
    if not logs_dir.exists():
        return []
    files = sorted(logs_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    return [str(f) for f in files if f.is_file() and f.name.endswith(".txt")]


def _read_log_lines(file_path: str, max_lines: int = 50000) -> list[str]:
    """Read log lines from a file, respecting max_lines."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-max_lines:]
    except (OSError, IOError):
        return []


# ── log line parser ────────────────────────────────────────────────────

# Pattern: "2026-07-29 02:28:56,393 - penguin.engine - INFO - message"
_LOG_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s*-\s+"
    r"([\w.]+)\s*-\s+"
    r"(\w+)\s*-\s+"
    r"(.*)$"
)


def _parse_log_line(line: str) -> dict[str, Any] | None:
    match = _LOG_PATTERN.match(line)
    if not match:
        return None
    return {
        "timestamp": match.group(1),
        "logger": match.group(2),
        "level": match.group(3),
        "message": match.group(4),
        "raw": line,
    }


# ── LLM attempt parser ─────────────────────────────────────────────────

# engine.llm_attempt.done lines have key=value pairs in the message
_LLM_ATTEMPT_RE = re.compile(
    r"engine\.llm_attempt\.done\s+"
    r"request=(\S+)\s+"
    r"session=(\S+)\s+"
    r"duration_ms=([\d.]+)\s+"
    r"response_len=(\d+)\s+"
    r"pending_tool_call=(\w+)\s+"
    r"status=(\w+)\s+"
    r"finish_reason=(\S+)?\s*"
    r"usage=\{(.*?)\}\s*"
    r"lifecycle_data=\{(.*?)\}"
)


def parse_llm_attempts(
    file_paths: list[str] | None = None, force_refresh: bool = False
) -> list[dict[str, Any]]:
    """Parse engine.llm_attempt.done lines from server logs.

    Returns structured records with duration, model, tokens, cost.
    """
    cache_key = "llm_attempts"
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    if file_paths is None:
        file_paths = get_all_log_files()

    results: list[dict[str, Any]] = []
    seen = set()

    for fp in file_paths:
        lines = _read_log_lines(fp)
        for line in lines:
            parsed = _parse_log_line(line)
            if not parsed:
                continue
            msg = parsed["message"]
            if "engine.llm_attempt.done" not in msg:
                continue

            # Try to extract usage dict from the message
            # The message format varies; grab the session, duration, and usage
            record = {
                "timestamp": parsed["timestamp"],
                "logger": parsed["logger"],
                "level": parsed["level"],
            }

            # Extract session
            m = re.search(r"session=(\S+)", msg)
            if m:
                record["session"] = m.group(1)

            # Extract duration
            m = re.search(r"duration_ms=([\d.]+)", msg)
            if m:
                record["duration_ms"] = float(m.group(1))

            # Extract model from lifecycle_data or usage
            m = re.search(r"model=(\S+)", msg)
            if m:
                record["model"] = m.group(1)

            # Extract provider
            m = re.search(r"provider=(\S+)", msg)
            if m:
                record["provider"] = m.group(1)

            # Extract status
            m = re.search(r"status=(\w+)", msg)
            if m:
                record["status"] = m.group(1)

            # Extract finish_reason
            m = re.search(r"finish_reason=(\S+)", msg)
            if m:
                record["finish_reason"] = m.group(1)

            # Extract usage dict
            m = re.search(r"usage=\{(.*?)\}", msg)
            if m:
                try:
                    usage_str = "{" + m.group(1) + "}"
                    usage = json.loads(usage_str)
                    record.update(
                        {
                            f"usage_{k}": v
                            for k, v in usage.items()
                            if isinstance(v, (int, float))
                        }
                    )
                except json.JSONDecodeError:
                    pass

            # Deduplicate by (session, timestamp)
            dedup_key = (record.get("session", ""), record.get("timestamp", ""))
            if dedup_key not in seen:
                seen.add(dedup_key)
                results.append(record)

    _cache_set(cache_key, results)
    return results


# ── context snapshot parser ────────────────────────────────────────────

_CONTEXT_SNAPSHOT_RE = re.compile(
    r"engine\.context\.snapshot\s+"
    r"request=(\S+)\s+"
    r"session=(\S+)\s+"
    r"agent=(\S+)\s+"
    r"formatted_messages=(\d+)\s+"
    r"roles=\{(.*?)\}\s+"
    r"total_chars=(\d+)\s+"
    r"approx_tokens=(\d+)\s+"
    r"session_messages=(\d+)\s+"
    r"session_tokens=(\d+)\s+"
    r"category_tokens=\{(.*?)\}\s+"
    r"largest=\[(.*?)\]"
)


def parse_context_snapshots(
    file_paths: list[str] | None = None, force_refresh: bool = False
) -> list[dict[str, Any]]:
    """Parse engine.context.snapshot lines into structured records.

    These contain category token budgets, largest messages, session token counts.
    This is the most Penguin-specific observability data.
    """
    cache_key = "context_snapshots"
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    if file_paths is None:
        file_paths = get_all_log_files()

    results: list[dict[str, Any]] = []
    seen = set()

    for fp in file_paths:
        lines = _read_log_lines(fp)
        for line in lines:
            parsed = _parse_log_line(line)
            if not parsed:
                continue
            msg = parsed["message"]
            if "engine.context.snapshot" not in msg:
                continue

            record = {
                "timestamp": parsed["timestamp"],
                "logger": parsed["logger"],
            }

            # Extract session
            m = re.search(r"session=(\S+)", msg)
            if m:
                record["session"] = m.group(1)

            # Extract agent
            m = re.search(r"agent=(\S+)", msg)
            if m:
                record["agent"] = m.group(1)

            # Extract formatted_messages
            m = re.search(r"formatted_messages=(\d+)", msg)
            if m:
                record["formatted_messages"] = int(m.group(1))

            # Extract total_chars
            m = re.search(r"total_chars=(\d+)", msg)
            if m:
                record["total_chars"] = int(m.group(1))

            # Extract approx_tokens
            m = re.search(r"approx_tokens=(\d+)", msg)
            if m:
                record["approx_tokens"] = int(m.group(1))

            # Extract session_tokens
            m = re.search(r"session_tokens=(\d+)", msg)
            if m:
                record["session_tokens"] = int(m.group(1))

            # Extract category_tokens dict
            m = re.search(r"category_tokens=\{(.*?)\}", msg)
            if m:
                try:
                    ct = json.loads("{" + m.group(1) + "}")
                    for k, v in ct.items():
                        record[f"cat_{k}"] = v
                except json.JSONDecodeError:
                    pass

            # Extract largest messages
            m = re.search(r"largest=\[(.*?)\]", msg)
            if m:
                try:
                    largest = json.loads("[" + m.group(1) + "]")
                    record["largest_count"] = len(largest)
                    if largest:
                        record["largest_tokens"] = largest[0].get("tokens", 0)
                        record["largest_category"] = largest[0].get("category", "")
                        record["largest_role"] = largest[0].get("role", "")
                except (json.JSONDecodeError, IndexError):
                    pass

            # Deduplicate
            dedup_key = (record.get("session", ""), record.get("timestamp", ""))
            if dedup_key not in seen:
                seen.add(dedup_key)
                results.append(record)

    _cache_set(cache_key, results)
    return results


# ── tool exec done parser ──────────────────────────────────────────────

_TOOL_EXEC_DONE_RE = re.compile(
    r"tool\.exec\.done\s+"
    r"request=(\S+)\s+"
    r"session=(\S+)\s+"
    r"call_id=(\S+)\s+"
    r"tool=(\S+)\s+"
    r"source=(\S+)\s+"
    r"status=(\w+)\s+"
    r"duration_ms=([\d.]+)\s+"
    r"args_chars=(\d+)\s+"
    r"output_bytes=(\d+)\s+"
    r"output_lines=(\d+)\s+"
    r"truncated=(\w+)"
)


def parse_tool_exec_done(
    file_paths: list[str] | None = None, force_refresh: bool = False
) -> list[dict[str, Any]]:
    """Parse tool.exec.done lines from server logs.

    These contain tool execution timing, output size, truncation status.
    """
    cache_key = "tool_exec_done"
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    if file_paths is None:
        file_paths = get_all_log_files()

    results: list[dict[str, Any]] = []
    seen = set()

    for fp in file_paths:
        lines = _read_log_lines(fp)
        for line in lines:
            parsed = _parse_log_line(line)
            if not parsed:
                continue
            msg = parsed["message"]
            if "tool.exec.done" not in msg:
                continue

            record = {
                "timestamp": parsed["timestamp"],
                "logger": parsed["logger"],
            }

            # Extract session
            m = re.search(r"session=(\S+)", msg)
            if m:
                record["session"] = m.group(1)

            # Extract tool name
            m = re.search(r"tool=(\S+)", msg)
            if m:
                record["tool_name"] = m.group(1)

            # Extract status
            m = re.search(r"status=(\w+)", msg)
            if m:
                record["status"] = m.group(1)

            # Extract duration
            m = re.search(r"duration_ms=([\d.]+)", msg)
            if m:
                record["duration_ms"] = float(m.group(1))

            # Extract output_bytes
            m = re.search(r"output_bytes=(\d+)", msg)
            if m:
                record["output_bytes"] = int(m.group(1))

            # Extract output_lines
            m = re.search(r"output_lines=(\d+)", msg)
            if m:
                record["output_lines"] = int(m.group(1))

            # Extract truncated
            m = re.search(r"truncated=(\w+)", msg)
            if m:
                record["truncated"] = m.group(1) == "True"

            # Extract call_id
            m = re.search(r"call_id=(\S+)", msg)
            if m:
                record["call_id"] = m.group(1)

            # Deduplicate
            dedup_key = (
                record.get("session", ""),
                record.get("call_id", ""),
                record.get("timestamp", ""),
            )
            if dedup_key not in seen:
                seen.add(dedup_key)
                results.append(record)

    _cache_set(cache_key, results)
    return results


# ── error log parser ───────────────────────────────────────────────────


def parse_errors_from_logs(
    file_paths: list[str] | None = None, force_refresh: bool = False
) -> list[dict[str, Any]]:
    """Parse log lines with ERROR/WARNING level or error-like content."""
    cache_key = "log_errors"
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    if file_paths is None:
        file_paths = get_all_log_files()

    results: list[dict[str, Any]] = []
    seen = set()

    for fp in file_paths:
        lines = _read_log_lines(fp, max_lines=20000)
        for line in lines:
            parsed = _parse_log_line(line)
            if not parsed:
                continue
            if parsed["level"] not in ("ERROR", "WARNING", "CRITICAL"):
                continue

            msg = parsed["message"]
            record = {
                "timestamp": parsed["timestamp"],
                "logger": parsed["logger"],
                "level": parsed["level"],
                "message_preview": msg[:200],
            }

            # Extract session if present
            m = re.search(r"session=(\S+)", msg)
            if m:
                record["session"] = m.group(1)

            dedup_key = (record["timestamp"], record["message_preview"])
            if dedup_key not in seen:
                seen.add(dedup_key)
                results.append(record)

    _cache_set(cache_key, results)
    return results


def clear_cache():
    """Clear the log parse cache."""
    _cache_clear()


def cache_status() -> dict[str, Any]:
    """Return cache status info."""
    conn = _ensure_cache_db()
    rows = conn.execute(
        "SELECT key, cached_at FROM log_cache ORDER BY key"
    ).fetchall()
    return {
        "keys": [dict(r) for r in rows],
        "count": len(rows),
    }