"""SQL queries against runtime_events.db.

The `event_json` column is the richest source — it contains the full RuntimeEvent
envelope with scope, payload, privacy, projections, and timing. The `payload_json`
column is a subset and `projection_json` is an OpenCode projection.

Key event types:
  - message.updated / message_lifecycle: LLM responses with modelID, providerID,
    tokens (input/output/cache/reasoning), cost, finish reason, timing
  - message.part.updated / stream_chunk: streaming text/reasoning parts
  - message.part.updated / tool_action_lifecycle: tool calls with callID, tool name,
    status (running/completed), timing, input command
  - session.status / session_lifecycle: busy/idle transitions
  - session.created / session_lifecycle: new session
  - vcs.branch.updated / file_diff: git branch changes
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

# ── workspace path resolution ──────────────────────────────────────────

_WORKSPACE = os.environ.get(
    "PENGUIN_WORKSPACE",
    os.path.expanduser("~/penguin_workspace"),
)


def get_event_db_path() -> str:
    return str(Path(_WORKSPACE) / "runtime_events" / "runtime_events.db")


def get_workspace() -> str:
    return _WORKSPACE


# ── helpers ────────────────────────────────────────────────────────────


@st.cache_resource(ttl=60)
def _get_conn() -> sqlite3.Connection:
    db = get_event_db_path()
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _json_extract(path: str) -> str:
    return f"json_extract(event_json, '$.{path}')"


def _fetch_all(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def _fetch_one(query: str, params: tuple = ()) -> dict[str, Any] | None:
    conn = _get_conn()
    row = conn.execute(query, params).fetchone()
    return dict(row) if row else None


# ── cost queries ───────────────────────────────────────────────────────


def query_cost_summary() -> dict[str, Any]:
    """Overall cost summary: total cost, total LLM calls, date range."""
    row = _fetch_one(
        f"""
        SELECT
            COUNT(*) AS total_llm_calls,
            SUM(CAST({_json_extract("payload.cost")} AS REAL)) AS total_cost,
            MIN({_json_extract("scope.model_id")}) AS model_list,
            COUNT(DISTINCT {_json_extract("scope.session_id")}) AS session_count,
            COUNT(DISTINCT {_json_extract("scope.model_id")}) AS model_count,
            MIN(event_time) AS first_event,
            MAX(event_time) AS last_event
        FROM runtime_events
        WHERE event_type = 'message.updated'
          AND category = 'message_lifecycle'
          AND {_json_extract("payload.finish")} IS NOT NULL
        """
    )
    return row or {}


def query_cost_by_model() -> list[dict[str, Any]]:
    """Cost and token usage grouped by model."""
    rows = _fetch_all(
        f"""
        SELECT
            COALESCE({_json_extract("scope.model_id")}, 'unknown') AS model,
            COALESCE({_json_extract("scope.provider_id")}, 'unknown') AS provider,
            COUNT(*) AS call_count,
            SUM(CAST({_json_extract("payload.tokens.input")} AS INTEGER)) AS input_tokens,
            SUM(CAST({_json_extract("payload.tokens.output")} AS INTEGER)) AS output_tokens,
            SUM(CAST({_json_extract("payload.tokens.reasoning")} AS INTEGER)) AS reasoning_tokens,
            SUM(CAST({_json_extract("payload.tokens.cache.read")} AS INTEGER)) AS cache_read_tokens,
            SUM(CAST({_json_extract("payload.tokens.cache.write")} AS INTEGER)) AS cache_write_tokens,
            SUM(CAST({_json_extract("payload.cost")} AS REAL)) AS total_cost
        FROM runtime_events
        WHERE event_type = 'message.updated'
          AND category = 'message_lifecycle'
          AND {_json_extract("payload.finish")} IS NOT NULL
        GROUP BY {_json_extract("scope.model_id")}, {_json_extract("scope.provider_id")}
        ORDER BY total_cost DESC
        """
    )
    return rows


def query_cost_by_day() -> list[dict[str, Any]]:
    """Daily cost and token usage over time."""
    rows = _fetch_all(
        f"""
        SELECT
            DATE(event_time / 1000, 'unixepoch') AS day,
            COUNT(*) AS call_count,
            SUM(CAST({_json_extract("payload.cost")} AS REAL)) AS total_cost,
            SUM(CAST({_json_extract("payload.tokens.input")} AS INTEGER)) AS input_tokens,
            SUM(CAST({_json_extract("payload.tokens.output")} AS INTEGER)) AS output_tokens
        FROM runtime_events
        WHERE event_type = 'message.updated'
          AND category = 'message_lifecycle'
          AND {_json_extract("payload.finish")} IS NOT NULL
        GROUP BY day
        ORDER BY day
        """
    )
    return rows


def query_cost_by_session(limit: int = 20) -> list[dict[str, Any]]:
    """Cost per session (top N by cost)."""
    rows = _fetch_all(
        f"""
        SELECT
            COALESCE({_json_extract("scope.session_id")}, 'unknown') AS session_id,
            COUNT(*) AS call_count,
            SUM(CAST({_json_extract("payload.cost")} AS REAL)) AS total_cost,
            SUM(CAST({_json_extract("payload.tokens.input")} AS INTEGER)) AS input_tokens,
            SUM(CAST({_json_extract("payload.tokens.output")} AS INTEGER)) AS output_tokens,
            MIN(event_time) AS first_call,
            MAX(event_time) AS last_call
        FROM runtime_events
        WHERE event_type = 'message.updated'
          AND category = 'message_lifecycle'
          AND {_json_extract("payload.finish")} IS NOT NULL
        GROUP BY {_json_extract("scope.session_id")}
        ORDER BY total_cost DESC
        LIMIT ?
        """,
        (limit,),
    )
    return rows


def query_cache_hit_ratio() -> list[dict[str, Any]]:
    """Cache read ratio per model (cache_read / total_input)."""
    rows = _fetch_all(
        f"""
        SELECT
            COALESCE({_json_extract("scope.model_id")}, 'unknown') AS model,
            SUM(CAST({_json_extract("payload.tokens.input")} AS INTEGER)) AS total_input,
            SUM(CAST({_json_extract("payload.tokens.cache.read")} AS INTEGER)) AS cache_read,
            CASE
                WHEN SUM(CAST({_json_extract("payload.tokens.input")} AS INTEGER)) > 0
                THEN ROUND(
                    100.0 * SUM(CAST({_json_extract("payload.tokens.cache.read")} AS INTEGER))
                    / SUM(CAST({_json_extract("payload.tokens.input")} AS INTEGER)), 1
                )
                ELSE 0
            END AS cache_hit_pct
        FROM runtime_events
        WHERE event_type = 'message.updated'
          AND category = 'message_lifecycle'
          AND {_json_extract("payload.finish")} IS NOT NULL
        GROUP BY {_json_extract("scope.model_id")}
        ORDER BY cache_hit_pct DESC
        """
    )
    return rows


# ── tool execution queries ─────────────────────────────────────────────


def query_tool_executions() -> list[dict[str, Any]]:
    """All completed tool calls with timing and tool name."""
    rows = _fetch_all(
        f"""
        SELECT
            {_json_extract("payload.part.tool")} AS tool_name,
            {_json_extract("payload.part.callID")} AS call_id,
            {_json_extract("payload.part.state.status")} AS status,
            {_json_extract("payload.part.state.time.start")} AS start_time,
            {_json_extract("payload.part.state.metadata.model")} AS model,
            {_json_extract("scope.session_id")} AS session_id,
            event_time AS event_ts
        FROM runtime_events
        WHERE category = 'tool_action_lifecycle'
          AND {_json_extract("payload.part.state.status")} IN ('running', 'completed')
        ORDER BY event_time
        """
    )
    return rows


def query_tool_summary() -> list[dict[str, Any]]:
    """Aggregated tool statistics."""
    rows = _fetch_all(
        f"""
        SELECT
            {_json_extract("payload.part.tool")} AS tool_name,
            COUNT(*) AS total_calls,
            SUM(CASE WHEN {_json_extract("payload.part.state.status")} = 'completed'
                THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN {_json_extract("payload.part.state.status")} = 'running'
                THEN 1 ELSE 0 END) AS running
        FROM runtime_events
        WHERE category = 'tool_action_lifecycle'
        GROUP BY {_json_extract("payload.part.tool")}
        ORDER BY total_calls DESC
        """
    )
    return rows


# ── LLM call queries ───────────────────────────────────────────────────


def query_llm_calls_all() -> list[dict[str, Any]]:
    """All LLM call events with timing, model, tokens, cost."""
    rows = _fetch_all(
        f"""
        SELECT
            {_json_extract("payload.id")} AS message_id,
            {_json_extract("scope.session_id")} AS session_id,
            {_json_extract("scope.model_id")} AS model,
            {_json_extract("scope.provider_id")} AS provider,
            {_json_extract("payload.finish")} AS finish_reason,
            {_json_extract("payload.role")} AS role,
            {_json_extract("payload.tokens.input")} AS input_tokens,
            {_json_extract("payload.tokens.output")} AS output_tokens,
            {_json_extract("payload.tokens.reasoning")} AS reasoning_tokens,
            {_json_extract("payload.tokens.cache.read")} AS cache_read,
            {_json_extract("payload.tokens.cache.write")} AS cache_write,
            CAST({_json_extract("payload.cost")} AS REAL) AS cost,
            {_json_extract("payload.time.created")} AS created_ts,
            {_json_extract("payload.time.completed")} AS completed_ts,
            event_time AS event_ts
        FROM runtime_events
        WHERE event_type = 'message.updated'
          AND category = 'message_lifecycle'
          AND {_json_extract("payload.finish")} IS NOT NULL
        ORDER BY event_time
        """
    )
    return rows


# ── session queries ────────────────────────────────────────────────────


def query_session_events() -> list[dict[str, Any]]:
    """Session lifecycle events (created, busy, idle)."""
    rows = _fetch_all(
        f"""
        SELECT
            event_type,
            category,
            {_json_extract("payload.sessionID")} AS session_id,
            {_json_extract("payload.status.type")} AS status_type,
            event_time,
            {_json_extract("scope.session_id")} AS scope_session_id
        FROM runtime_events
        WHERE category = 'session_lifecycle'
        ORDER BY event_time
        """
    )
    return rows


def query_events_by_session(
    session_id: str, limit: int = 100
) -> list[dict[str, Any]]:
    """All events for a given session."""
    rows = _fetch_all(
        f"""
        SELECT
            event_type,
            category,
            sequence,
            event_time,
            substr(event_json, 1, 500) AS event_preview
        FROM runtime_events
        WHERE {_json_extract("scope.session_id")} = ?
        ORDER BY sequence
        LIMIT ?
        """,
        (session_id, limit),
    )
    return rows


def query_recent_sessions(limit: int = 50) -> list[dict[str, Any]]:
    """Most recently active sessions from event data."""
    rows = _fetch_all(
        f"""
        SELECT
            COALESCE({_json_extract("scope.session_id")}, 'orphan') AS session_id,
            COUNT(*) AS event_count,
            MIN(event_time) AS first_event,
            MAX(event_time) AS last_event
        FROM runtime_events
        GROUP BY {_json_extract("scope.session_id")}
        ORDER BY last_event DESC
        LIMIT ?
        """,
        (limit,),
    )
    return rows


# ── error / reliability queries ────────────────────────────────────────


def query_error_like_events() -> list[dict[str, Any]]:
    """Events that might indicate errors or issues."""
    rows = _fetch_all(
        f"""
        SELECT
            event_type,
            category,
            {_json_extract("scope.session_id")} AS session_id,
            {_json_extract("payload.part.callID")} AS call_id,
            {_json_extract("payload.part.tool")} AS tool_name,
            {_json_extract("payload.part.state.status")} AS status,
            event_time,
            substr(event_json, 1, 300) AS preview
        FROM runtime_events
        WHERE category = 'tool_action_lifecycle'
          AND {_json_extract("payload.part.state.status")} = 'running'
          AND NOT EXISTS (
              SELECT 1 FROM runtime_events AS r2
              WHERE r2.category = 'tool_action_lifecycle'
                AND json_extract(r2.event_json, '$.payload.part.callID') =
                    json_extract(runtime_events.event_json, '$.payload.part.callID')
                AND json_extract(r2.event_json, '$.payload.part.state.status') = 'completed'
          )
        ORDER BY event_time DESC
        LIMIT 50
        """
    )
    return rows


def query_tool_errors() -> list[dict[str, Any]]:
    """Tool calls with potential error conditions (long-running, no completion)."""
    # Completed tools with output > 0 that might indicate errors
    rows = _fetch_all(
        f"""
        SELECT
            {_json_extract("payload.part.tool")} AS tool_name,
            {_json_extract("payload.part.callID")} AS call_id,
            {_json_extract("payload.part.state.status")} AS status,
            {_json_extract("scope.session_id")} AS session_id,
            event_time,
            {_json_extract("payload.part.state.metadata.model")} AS model
        FROM runtime_events
        WHERE category = 'tool_action_lifecycle'
          AND {_json_extract("payload.part.state.status")} = 'completed'
        ORDER BY event_time DESC
        LIMIT 100
        """
    )
    return rows


def query_model_usage_by_session() -> list[dict[str, Any]]:
    """Which models were used in each session."""
    rows = _fetch_all(
        f"""
        SELECT
            {_json_extract("scope.session_id")} AS session_id,
            {_json_extract("scope.model_id")} AS model,
            {_json_extract("scope.provider_id")} AS provider,
            COUNT(*) AS call_count,
            SUM(CAST({_json_extract("payload.cost")} AS REAL)) AS total_cost
        FROM runtime_events
        WHERE event_type = 'message.updated'
          AND category = 'message_lifecycle'
          AND {_json_extract("payload.finish")} IS NOT NULL
        GROUP BY {_json_extract("scope.session_id")},
                 {_json_extract("scope.model_id")},
                 {_json_extract("scope.provider_id")}
        ORDER BY total_cost DESC
        """
    )
    return rows