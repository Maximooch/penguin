"""Context Window Health panel — category budgets, trimming, token pressure.

This is the most Penguin-specific view. It relies on `engine.context.snapshot`
lines from the server logs, which contain category token breakdowns and
largest-message details that no existing observability tool understands.
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from penguin.dashboard.queries.server_logs import (
    cache_status,
    parse_context_snapshots,
)


def render():
    st.header("Context Window Health")

    col1, col2 = st.columns([3, 1])
    with col2:
        force_refresh = st.button("🔄 Refresh from logs", key="ctx_refresh")

    snapshots = parse_context_snapshots(force_refresh=force_refresh)
    if not snapshots:
        st.info("No context snapshot data found in server logs. This tab requires "
                "`engine.context.snapshot` log lines from `penguin.engine`.")
        return

    df = pd.DataFrame(snapshots)
    if df.empty:
        return

    # ── Category token categories present ──────────────────────────────
    cat_cols = [c for c in df.columns if c.startswith("cat_")]
    if not cat_cols:
        st.info("No category token data in context snapshots.")
        return

    # ── KPI row ────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    total_snapshots = len(df)
    k1.metric("Context Snapshots", total_snapshots)

    total_tokens = df["session_tokens"].sum() if "session_tokens" in df.columns else 0
    k2.metric("Total Session Tokens", f"{total_tokens:,.0f}")

    avg_tokens = df["session_tokens"].mean() if "session_tokens" in df.columns else 0
    k3.metric("Avg Session Tokens", f"{avg_tokens:,.0f}")

    max_tokens = df["session_tokens"].max() if "session_tokens" in df.columns else 0
    k4.metric("Max Session Tokens", f"{max_tokens:,.0f}")

    # ── Category breakdown ─────────────────────────────────────────────
    st.subheader("Category Token Distribution")

    # Build a long-form DataFrame for Plotly
    cat_rows = []
    for _, row in df.iterrows():
        for col in cat_cols:
            cat_name = col.replace("cat_", "")
            val = row.get(col, 0)
            if val and val > 0:
                cat_rows.append(
                    {
                        "timestamp": row.get("timestamp", ""),
                        "session": row.get("session", ""),
                        "category": cat_name,
                        "tokens": val,
                    }
                )

    if cat_rows:
        cat_df = pd.DataFrame(cat_rows)

        # Stacked bar of recent snapshots
        recent = cat_df.tail(50)
        fig = px.bar(
            recent,
            x="timestamp",
            y="tokens",
            color="category",
            title="Category Token Distribution (Last 50 Snapshots)",
            labels={"tokens": "Tokens", "timestamp": "Time", "category": "Category"},
            height=400,
            barmode="stack",
        )
        st.plotly_chart(fig, width="stretch")

        # Average category breakdown
        avg_cat = cat_df.groupby("category")["tokens"].mean().reset_index()
        avg_cat = avg_cat.sort_values("tokens", ascending=True)
        fig = px.bar(
            avg_cat,
            x="tokens",
            y="category",
            orientation="h",
            title="Average Tokens per Category",
            labels={"tokens": "Avg Tokens", "category": "Category"},
            height=350,
            color="tokens",
            color_continuous_scale="Viridis",
        )
        st.plotly_chart(fig, width="stretch")

    # ── Token pressure over time ───────────────────────────────────────
    if "session_tokens" in df.columns and "timestamp" in df.columns:
        fig = px.line(
            df,
            x="timestamp",
            y="session_tokens",
            title="Session Token Count Over Time",
            labels={"session_tokens": "Session Tokens", "timestamp": "Time"},
            height=350,
            markers=True,
        )
        st.plotly_chart(fig, width="stretch")

    # ── Largest messages ───────────────────────────────────────────────
    st.subheader("Largest Messages in Context")
    largest_cols = [
        c for c in df.columns if c.startswith("largest_")
    ]
    if largest_cols:
        largest_df = df[["timestamp", "session"] + largest_cols].copy()
        largest_df = largest_df.dropna(subset=largest_cols)
        if not largest_df.empty:
            # Show the most recent snapshots with largest message info
            st.dataframe(
                largest_df.tail(20),
                width="stretch",
                hide_index=True,
            )

    # ── Category token summary table ───────────────────────────────────
    st.subheader("Category Token Summary")
    if cat_rows:
        summary = (
            cat_df.groupby("category")["tokens"]
            .agg(["count", "mean", "sum", "max"])
            .reset_index()
            .sort_values("sum", ascending=False)
        )
        summary.columns = ["Category", "Snapshots", "Avg Tokens", "Total Tokens", "Max Tokens"]
        for col in ["Avg Tokens", "Total Tokens", "Max Tokens"]:
            summary[col] = summary[col].fillna(0).round(0).astype(int)
        st.dataframe(summary, width="stretch", hide_index=True)

    # ── Full snapshot table ────────────────────────────────────────────
    with st.expander("Raw Context Snapshots (last 50)"):
        display_cols = ["timestamp", "session", "session_tokens", "approx_tokens",
                        "total_chars", "formatted_messages"] + cat_cols
        display_cols = [c for c in display_cols if c in df.columns]
        display_df = df[display_cols].tail(50).copy()
        display_df["timestamp"] = pd.to_datetime(display_df["timestamp"])
        if "session_tokens" in display_df.columns:
            display_df["session_tokens"] = display_df["session_tokens"].apply(
                lambda x: f"{x:,.0f}" if x else "0"
            )
        st.dataframe(display_df, width="stretch", hide_index=True)