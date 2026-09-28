"""Session Explorer panel — browse sessions, view transcripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from penguin.dashboard.queries.runtime_events import (
    get_workspace,
    query_events_by_session,
    query_recent_sessions,
    query_session_events,
)


def _get_session_index_path() -> Path:
    return Path(get_workspace()) / "conversations" / "session_index.json"


def _load_session_index() -> list[dict[str, Any]]:
    path = _get_session_index_path()
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, IOError):
        return []


def _get_session_dir() -> Path:
    return Path(get_workspace()) / "conversations"


def _load_session_messages(session_id: str, max_chars: int = 5000) -> str:
    """Load the latest messages.json for a session."""
    base = _get_session_dir()
    # Try default path first
    for child in base.iterdir():
        if child.is_dir() and session_id in child.name:
            msgs_file = child / "messages.json"
            if msgs_file.exists():
                try:
                    text = msgs_file.read_text(encoding="utf-8", errors="replace")
                    if len(text) > max_chars:
                        text = text[:max_chars] + "\n\n... (truncated)"
                    return text
                except (OSError, IOError):
                    pass
    return "Session messages not found."


def render():
    st.header("Session Explorer")

    # ── Session index ──────────────────────────────────────────────────
    index = _load_session_index()
    if index:
        st.success(f"Session index loaded: {len(index)} sessions")

    # ── Recent sessions from event DB ──────────────────────────────────
    st.subheader("Recent Sessions (from event DB)")
    recent = query_recent_sessions(limit=30)
    if recent:
        df = pd.DataFrame(recent)
        df["last_event"] = pd.to_datetime(df["last_event"], unit="ms")
        df["first_event"] = pd.to_datetime(df["first_event"], unit="ms")
        df["session_id"] = df["session_id"].str[:40] + "..."

        # Sessions over time (calendar)
        df["date"] = df["last_event"].dt.date
        session_counts = df.groupby("date").size().reset_index(name="count")
        fig = px.bar(
            session_counts,
            x="date",
            y="count",
            title="Sessions per Day",
            labels={"date": "Date", "count": "Sessions"},
            height=300,
        )
        st.plotly_chart(fig, width="stretch")

        # Session table
        df_display = df[
            ["session_id", "event_count", "first_event", "last_event"]
        ].copy()
        df_display.columns = ["Session", "Events", "First", "Last"]
        st.dataframe(df_display, width="stretch", hide_index=True)

    # ── Session selector ───────────────────────────────────────────────
    st.subheader("Session Detail")
    if recent:
        session_ids = [r["session_id"] for r in recent]
        # Get the original session ids (non-truncated)
        original_sessions = [r["session_id"] for r in query_recent_sessions(limit=30)]

        selected = st.selectbox(
            "Select a session to inspect",
            options=original_sessions,
            format_func=lambda x: x[:50] + "..." if len(x) > 50 else x,
        )

        if selected:
            # Show session events
            st.subheader(f"Events for {selected[:40]}...")
            events = query_events_by_session(selected, limit=50)
            if events:
                df_events = pd.DataFrame(events)
                df_events["event_time"] = pd.to_datetime(
                    df_events["event_time"], unit="ms"
                )
                st.dataframe(
                    df_events[["event_type", "category", "sequence", "event_time"]],
                    width="stretch",
                    hide_index=True,
                )

            # Show session messages
            with st.expander("View Session Messages (raw JSON)"):
                messages = _load_session_messages(selected)
                st.code(messages, language="json")

            # Show full event preview
            with st.expander("View Raw Event JSON (first 20)"):
                if events:
                    for ev in events[:20]:
                        preview = ev.get("event_preview", "")
                        if preview:
                            st.code(preview, language="json")

    # ── Session index table ────────────────────────────────────────────
    if index:
        st.subheader("Session Index Details")
        df_index = pd.DataFrame(index)
        if "timestamp" in df_index.columns:
            df_index["timestamp"] = pd.to_datetime(df_index["timestamp"], unit="ms")
        st.dataframe(df_index, width="stretch", hide_index=True)

    # ── Session lifecycle events ───────────────────────────────────────
    st.subheader("Session Lifecycle Events")
    lifecycle = query_session_events()
    if lifecycle:
        df = pd.DataFrame(lifecycle)
        df["event_time"] = pd.to_datetime(df["event_time"], unit="ms")
        # Count by status type
        if "status_type" in df.columns:
            status_counts = df["status_type"].value_counts().reset_index()
            status_counts.columns = ["Status", "Count"]
            fig = px.pie(
                status_counts,
                values="Count",
                names="Status",
                title="Session Status Distribution",
                height=350,
            )
            st.plotly_chart(fig, width="stretch")
        st.dataframe(
            df[["event_type", "status_type", "session_id", "event_time"]].dropna(
                subset=["status_type"]
            ),
            width="stretch",
            hide_index=True,
        )