"""Reliability panel — errors, warnings, and failure tracking."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from penguin.dashboard.queries.runtime_events import (
    query_error_like_events,
    query_tool_summary,
)
from penguin.dashboard.queries.server_logs import (
    cache_status,
    parse_errors_from_logs,
)


def render():
    st.header("Reliability")

    col1, col2 = st.columns([3, 1])
    with col2:
        force_refresh = st.button("🔄 Refresh from logs", key="rel_refresh")

    # ── Tool success/failure rates ─────────────────────────────────────
    st.subheader("Tool Call Summary")
    tool_summary = query_tool_summary()
    if tool_summary:
        df = pd.DataFrame(tool_summary)
        df["success_rate"] = (df["completed"] / df["total_calls"] * 100).round(1)
        df["success_rate"] = df["success_rate"].fillna(0)

        fig = px.bar(
            df,
            x="tool_name",
            y=["completed", "running"],
            title="Tool Calls by Status",
            labels={"value": "Count", "tool_name": "Tool", "variable": "Status"},
            height=400,
            barmode="group",
        )
        st.plotly_chart(fig, width="stretch")

        # Tool reliability table
        df_display = df[["tool_name", "total_calls", "completed", "running", "success_rate"]].copy()
        df_display.columns = ["Tool", "Total", "Completed", "Running", "Success Rate"]
        st.dataframe(df_display, width="stretch", hide_index=True)

    # ── Orphaned tool calls (running but never completed) ──────────────
    st.subheader("Potentially Stuck Tool Calls")
    error_events = query_error_like_events()
    if error_events:
        df = pd.DataFrame(error_events)
        st.warning(
            f"Found {len(df)} tool calls that started but never completed. "
            "These may indicate errors or interruptions."
        )
        df_display = df[["tool_name", "session_id", "event_time"]].copy()
        df_display["event_time"] = pd.to_datetime(
            df_display["event_time"], unit="ms"
        )
        st.dataframe(df_display, width="stretch", hide_index=True)
    else:
        st.success("No orphaned tool calls detected.")

    # ── Error/Warning logs ─────────────────────────────────────────────
    st.subheader("Error & Warning Logs")
    log_errors = parse_errors_from_logs(force_refresh=force_refresh)
    if log_errors:
        df = pd.DataFrame(log_errors)

        # Error count by level
        level_counts = df["level"].value_counts().reset_index()
        level_counts.columns = ["Level", "Count"]
        fig = px.pie(
            level_counts,
            values="Count",
            names="Level",
            title="Log Level Distribution",
            height=350,
        )
        st.plotly_chart(fig, width="stretch")

        # Error count by logger
        logger_counts = df["logger"].value_counts().head(10).reset_index()
        logger_counts.columns = ["Logger", "Count"]
        fig = px.bar(
            logger_counts,
            x="Logger",
            y="Count",
            title="Top 10 Loggers by Error/Warning Count",
            height=350,
        )
        st.plotly_chart(fig, width="stretch")

        # Recent errors
        st.subheader("Recent Errors & Warnings")
        recent = df.head(20)
        recent["timestamp"] = pd.to_datetime(recent["timestamp"])
        st.dataframe(
            recent[["timestamp", "level", "logger", "message_preview"]],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No ERROR or WARNING log lines found.")