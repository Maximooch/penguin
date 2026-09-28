"""Penguin Local Dashboard — Streamlit app.

This dashboard reads from:
  - runtime_events.db (structured event stream)
  - server-logs/ (rotated text files, parsed and cached)
  - projects.db (task/project execution)
  - conversations/ (session transcripts)

Usage:
  cd /path/to/Code/Penguin/penguin
  streamlit run penguin/dashboard/app.py --server.port 8501

Or from workspace:
  PENGUIN_WORKSPACE=/path/to/penguin_workspace streamlit run penguin/dashboard/app.py
"""

from __future__ import annotations

import os

import streamlit as st

# Page config must be first Streamlit command
st.set_page_config(
    page_title="Penguin Dashboard",
    page_icon="🐧",
    layout="wide",
    initial_sidebar_state="expanded",
)

from penguin.dashboard.components import (
    cost_panel,
    context_panel,
    performance_panel,
    reliability_panel,
    session_explorer,
    task_panel,
)
from penguin.dashboard.queries.runtime_events import (
    get_event_db_path,
    get_workspace,
)
from penguin.dashboard.queries.server_logs import cache_status

# ── Sidebar ────────────────────────────────────────────────────────────

st.sidebar.title("🐧 Penguin Dashboard")
st.sidebar.caption("Local observability for Penguin agent sessions")

# Workspace info
workspace = get_workspace()
st.sidebar.subheader("Data Sources")
st.sidebar.text(f"Workspace: {workspace}")

event_db = get_event_db_path()
st.sidebar.text(f"Event DB: {'✅' if os.path.exists(event_db) else '❌'} exists")
st.sidebar.text(f"Size: {os.path.getsize(event_db) / 1_000_000:.1f} MB" if os.path.exists(event_db) else "")

projects_db = os.path.join(workspace, "projects.db")
st.sidebar.text(f"Projects DB: {'✅' if os.path.exists(projects_db) else '❌'} exists")

logs_dir = os.path.join(workspace, "server-logs")
if os.path.exists(logs_dir):
    log_count = len([f for f in os.listdir(logs_dir) if f.endswith(".txt")])
    st.sidebar.text(f"Server logs: {log_count} files")
else:
    st.sidebar.text("Server logs: ❌ not found")

# Cache status
cache_info = cache_status()
st.sidebar.subheader("Log Cache")
if cache_info["keys"]:
    st.sidebar.text(f"{len(cache_info['keys'])} datasets cached")
else:
    st.sidebar.text("Empty (parses on first load)")

# ── Tabs ───────────────────────────────────────────────────────────────

tabs = st.tabs([
    "💰 Cost & Usage",
    "⚡ Performance",
    "🛡️ Reliability",
    "📊 Context Window",
    "📋 Tasks & Projects",
    "🔍 Session Explorer",
])

with tabs[0]:
    cost_panel.render()

with tabs[1]:
    performance_panel.render()

with tabs[2]:
    reliability_panel.render()

with tabs[3]:
    context_panel.render()

with tabs[4]:
    task_panel.render()

with tabs[5]:
    session_explorer.render()

# ── Footer ─────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "Penguin Dashboard v0.1.0 — "
    "Data from `runtime_events.db`, `projects.db`, `server-logs/`, and `conversations/`. "
    "Logs are cached in `dashboard/.log_cache/`. "
    "Use the 🔄 Refresh buttons to force re-parse server logs."
)