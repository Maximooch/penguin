"""Cost & Usage panel — runtime_events.db data."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from penguin.dashboard.queries.runtime_events import (
    query_cache_hit_ratio,
    query_cost_by_day,
    query_cost_by_model,
    query_cost_by_session,
    query_cost_summary,
)


def render():
    st.header("Cost & Usage")

    summary = query_cost_summary()
    if not summary or not summary.get("total_llm_calls"):
        st.info("No cost data available yet. Run some Penguin sessions first.")
        return

    # ── KPI row ────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    total_cost = summary.get("total_cost", 0) or 0
    k1.metric("Total Cost", f"${total_cost:.4f}")
    k2.metric("LLM Calls", summary.get("total_llm_calls", 0))
    k3.metric("Sessions", summary.get("session_count", 0))
    k4.metric("Models Used", summary.get("model_count", 0))

    # Date range
    first = summary.get("first_event")
    last = summary.get("last_event")
    if first and last:
        from datetime import datetime

        f_dt = datetime.fromtimestamp(first / 1000).strftime("%m/%d")
        l_dt = datetime.fromtimestamp(last / 1000).strftime("%m/%d")
        k5.metric("Date Range", f"{f_dt} — {l_dt}")

    # ── Cost by model ──────────────────────────────────────────────────
    st.subheader("Cost by Model")
    model_data = query_cost_by_model()
    if model_data:
        df = pd.DataFrame(model_data)
        fig = px.bar(
            df,
            x="model",
            y="total_cost",
            color="provider",
            title="Total Cost by Model",
            labels={"total_cost": "Cost ($)", "model": "Model"},
            height=400,
        )
        st.plotly_chart(fig, width="stretch")

        # Token breakdown table
        st.subheader("Token Usage by Model")
        df_tokens = df[
            [
                "model",
                "provider",
                "call_count",
                "input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "cache_read_tokens",
                "total_cost",
            ]
        ].copy()
        df_tokens["input_tokens"] = df_tokens["input_tokens"].apply(
            lambda x: f"{x:,.0f}" if x else "0"
        )
        df_tokens["output_tokens"] = df_tokens["output_tokens"].apply(
            lambda x: f"{x:,.0f}" if x else "0"
        )
        df_tokens["total_cost"] = df_tokens["total_cost"].apply(
            lambda x: f"${x:.4f}" if x else "$0"
        )
        st.dataframe(df_tokens, width="stretch", hide_index=True)

    # ── Cost over time ─────────────────────────────────────────────────
    st.subheader("Cost Over Time")
    day_data = query_cost_by_day()
    if day_data:
        df = pd.DataFrame(day_data)
        df["day"] = pd.to_datetime(df["day"])
        fig = px.line(
            df,
            x="day",
            y="total_cost",
            title="Daily Cost",
            labels={"total_cost": "Cost ($)", "day": "Date"},
            height=350,
        )
        st.plotly_chart(fig, width="stretch")

    # ── Cache hit ratio ────────────────────────────────────────────────
    st.subheader("Cache Hit Ratio by Model")
    cache_data = query_cache_hit_ratio()
    if cache_data:
        df = pd.DataFrame(cache_data)
        fig = px.bar(
            df,
            x="model",
            y="cache_hit_pct",
            title="Cache Read as % of Input Tokens",
            labels={"cache_hit_pct": "Cache Hit %", "model": "Model"},
            height=350,
            color="cache_hit_pct",
            color_continuous_scale="Blues",
        )
        st.plotly_chart(fig, width="stretch")

    # ── Top sessions by cost ───────────────────────────────────────────
    st.subheader("Most Expensive Sessions")
    session_data = query_cost_by_session(limit=15)
    if session_data:
        df = pd.DataFrame(session_data)
        df["session_id"] = df["session_id"].str[:40] + "..."
        df["total_cost"] = df["total_cost"].apply(
            lambda x: f"${x:.4f}" if x else "$0"
        )
        df["input_tokens"] = df["input_tokens"].apply(
            lambda x: f"{x:,.0f}" if x else "0"
        )
        df["output_tokens"] = df["output_tokens"].apply(
            lambda x: f"{x:,.0f}" if x else "0"
        )
        st.dataframe(
            df[["session_id", "call_count", "total_cost", "input_tokens", "output_tokens"]],
            width="stretch",
            hide_index=True,
        )