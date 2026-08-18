"""SQL queries against projects.db.

Key tables:
  - projects: project metadata, status, budget
  - tasks: task lifecycle with status, phase, dependencies, tokens
  - execution_records: execution history with timing, tokens used, tools used
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import streamlit as st

from penguin.dashboard.queries.runtime_events import get_workspace


def get_projects_db_path() -> str:
    return str(Path(get_workspace()) / "projects.db")


@st.cache_resource(ttl=60)
def _get_conn() -> sqlite3.Connection:
    db = get_projects_db_path()
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_all(query: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def _fetch_one(query: str, params: tuple = ()) -> dict[str, Any] | None:
    conn = _get_conn()
    row = conn.execute(query, params).fetchone()
    return dict(row) if row else None


def query_project_summary() -> dict[str, Any]:
    """Overall project/task summary."""
    row = _fetch_one(
        """
        SELECT
            (SELECT COUNT(*) FROM projects) AS project_count,
            (SELECT COUNT(*) FROM tasks) AS total_tasks,
            (SELECT COUNT(*) FROM tasks WHERE status = 'done') AS done_tasks,
            (SELECT COUNT(*) FROM tasks WHERE status = 'in_progress') AS in_progress,
            (SELECT COUNT(*) FROM tasks WHERE status = 'pending') AS pending_tasks,
            (SELECT COUNT(*) FROM tasks WHERE status = 'failed') AS failed_tasks,
            (SELECT COUNT(*) FROM tasks WHERE phase = 'waiting_input') AS waiting_input,
            (SELECT COUNT(*) FROM execution_records) AS total_executions
        """
    )
    return row or {}


def query_task_summary() -> list[dict[str, Any]]:
    """Task status distribution."""
    rows = _fetch_all(
        """
        SELECT
            status,
            phase,
            COUNT(*) AS count,
            MIN(created_at) AS first_created,
            MAX(updated_at) AS last_updated
        FROM tasks
        GROUP BY status, phase
        ORDER BY count DESC
        """
    )
    return rows


def query_task_timeline(limit: int = 50) -> list[dict[str, Any]]:
    """Most recent tasks with full metadata."""
    rows = _fetch_all(
        """
        SELECT
            id,
            title,
            status,
            phase,
            project_id,
            priority,
            created_at,
            updated_at,
            progress,
            parent_task_id
        FROM tasks
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return rows


def query_state_transitions() -> list[dict[str, Any]]:
    """Task state transitions from execution records."""
    rows = _fetch_all(
        """
        SELECT
            e.task_id,
            t.title AS task_title,
            t.status AS task_status,
            t.phase AS task_phase,
            e.started_at,
            e.completed_at,
            e.iterations,
            e.max_iterations,
            e.tokens_used,
            e.tools_used,
            e.error_details
        FROM execution_records e
        LEFT JOIN tasks t ON e.task_id = t.id
        ORDER BY e.started_at DESC
        LIMIT 100
        """
    )
    return rows


def query_execution_records(limit: int = 50) -> list[dict[str, Any]]:
    """Recent execution records with timing and token usage."""
    rows = _fetch_all(
        """
        SELECT
            e.id,
            e.task_id,
            t.title AS task_title,
            t.status AS task_status,
            e.executor_id,
            e.started_at,
            e.completed_at,
            e.iterations,
            e.tokens_used,
            e.tools_used,
            e.error_details
        FROM execution_records e
        LEFT JOIN tasks t ON e.task_id = t.id
        ORDER BY e.started_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return rows


def query_tasks_by_project() -> list[dict[str, Any]]:
    """Task count per project."""
    rows = _fetch_all(
        """
        SELECT
            p.name AS project_name,
            p.id AS project_id,
            COUNT(t.id) AS task_count,
            SUM(CASE WHEN t.status = 'done' THEN 1 ELSE 0 END) AS done_count,
            SUM(CASE WHEN t.status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress_count,
            SUM(CASE WHEN t.status = 'failed' THEN 1 ELSE 0 END) AS failed_count
        FROM projects p
        LEFT JOIN tasks t ON t.project_id = p.id
        GROUP BY p.id
        ORDER BY task_count DESC
        """
    )
    return rows


def query_token_usage_from_executions() -> list[dict[str, Any]]:
    """Token usage breakdown from execution records."""
    rows = _fetch_all(
        """
        SELECT
            task_id,
            tokens_used,
            tools_used,
            error_details
        FROM execution_records
        WHERE tokens_used IS NOT NULL AND tokens_used != '{}'
        ORDER BY started_at DESC
        LIMIT 50
        """
    )
    # Parse JSON token fields
    parsed = []
    for r in rows:
        tokens = {}
        tools = []
        if r["tokens_used"]:
            try:
                tokens = json.loads(r["tokens_used"])
            except (json.JSONDecodeError, TypeError):
                pass
        if r["tools_used"]:
            try:
                tools = json.loads(r["tools_used"])
            except (json.JSONDecodeError, TypeError):
                pass
        r["tokens_parsed"] = tokens
        r["tools_parsed"] = tools
        parsed.append(r)
    return parsed


def query_orphan_tasks() -> list[dict[str, Any]]:
    """Tasks without a project."""
    rows = _fetch_all(
        """
        SELECT id, title, status, phase, created_at
        FROM tasks
        WHERE project_id IS NULL OR project_id = ''
        ORDER BY created_at DESC
        """
    )
    return rows