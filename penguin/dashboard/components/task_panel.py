"""Task & Project tracking panel — projects.db data."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from penguin.dashboard.queries.projects import (
    query_execution_records,
    query_project_summary,
    query_state_transitions,
    query_task_summary,
    query_task_timeline,
    query_tasks_by_project,
    query_token_usage_from_executions,
)


def render():
    st.header("Task & Project Tracking")

    summary = query_project_summary()
    if not summary or not summary.get("total_tasks"):
        st.info("No project/task data found. The projects.db may be empty.")
        return

    # ── KPI row ────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Projects", summary.get("project_count", 0))
    k2.metric("Total Tasks", summary.get("total_tasks", 0))
    k3.metric("Done", summary.get("done_tasks", 0))
    k4.metric("In Progress", summary.get("in_progress", 0))
    k5.metric("Failed", summary.get("failed_tasks", 0))

    # ── Task status distribution ───────────────────────────────────────
    st.subheader("Task Status Distribution")
    task_summary = query_task_summary()
    if task_summary:
        df = pd.DataFrame(task_summary)
        fig = px.pie(
            df,
            values="count",
            names="status",
            title="Tasks by Status",
            height=400,
            hole=0.3,
        )
        st.plotly_chart(fig, width="stretch")

        # Status + phase breakdown
        st.subheader("Status & Phase Breakdown")
        df["label"] = df["status"] + " / " + df["phase"]
        st.dataframe(
            df[["label", "count", "first_created", "last_updated"]],
            width="stretch",
            hide_index=True,
        )

    # ── Tasks by project ───────────────────────────────────────────────
    st.subheader("Tasks by Project")
    project_data = query_tasks_by_project()
    if project_data:
        df = pd.DataFrame(project_data)
        fig = px.bar(
            df,
            x="project_name",
            y=["task_count", "done_count", "in_progress_count", "failed_count"],
            title="Tasks per Project",
            labels={"value": "Count", "project_name": "Project", "variable": "Status"},
            height=400,
            barmode="group",
        )
        st.plotly_chart(fig, width="stretch")

    # ── Recent task timeline ───────────────────────────────────────────
    st.subheader("Recent Tasks")
    timeline = query_task_timeline(limit=30)
    if timeline:
        df = pd.DataFrame(timeline)
        df["updated_at"] = pd.to_datetime(df["updated_at"])
        df_display = df[
            ["title", "status", "phase", "priority", "updated_at", "progress"]
        ].copy()
        df_display.columns = [
            "Title", "Status", "Phase", "Priority", "Updated", "Progress"
        ]
        df_display = df_display.fillna("")
        st.dataframe(df_display, width="stretch", hide_index=True)

    # ── Execution history ──────────────────────────────────────────────
    st.subheader("Execution History")
    executions = query_execution_records(limit=30)
    if executions:
        df = pd.DataFrame(executions)
        df["started_at"] = pd.to_datetime(df["started_at"])
        if "completed_at" in df.columns:
            df["completed_at"] = pd.to_datetime(df["completed_at"])

        fig = px.timeline(
            df.dropna(subset=["started_at", "completed_at"]),
            x_start="started_at",
            x_end="completed_at",
            y="task_title",
            color="task_status",
            title="Task Execution Timeline",
            labels={"task_title": "Task", "task_status": "Status"},
            height=400,
        )
        st.plotly_chart(fig, width="stretch")

        # Execution detail table
        df_display = df[
            ["task_title", "task_status", "started_at", "iterations", "error_details"]
        ].copy()
        df_display.columns = [
            "Task", "Status", "Started", "Iterations", "Errors"
        ]
        st.dataframe(df_display, width="stretch", hide_index=True)

    # ── Token usage from executions ────────────────────────────────────
    st.subheader("Token Usage in Tasks")
    token_data = query_token_usage_from_executions()
    if token_data:
        token_rows = []
        for r in token_data:
            tokens = r.get("tokens_parsed", {}) or {}
            row = {"task_id": r["task_id"][:20]}
            if isinstance(tokens, dict):
                for k, v in tokens.items():
                    row[k] = v
            token_rows.append(row)
        if token_rows:
            df = pd.DataFrame(token_rows)
            numeric_cols = df.select_dtypes(include="number").columns
            if not numeric_cols.empty:
                summary = df[numeric_cols].sum().reset_index()
                summary.columns = ["Token Type", "Total"]
                fig = px.bar(
                    summary,
                    x="Token Type",
                    y="Total",
                    title="Token Usage from Task Executions",
                    height=350,
                )
                st.plotly_chart(fig, width="stretch")

    # ── State transitions ──────────────────────────────────────────────
    with st.expander("State Transitions (Execution Records)"):
        transitions = query_state_transitions()
        if transitions:
            df = pd.DataFrame(transitions)
            st.dataframe(df, width="stretch", hide_index=True)