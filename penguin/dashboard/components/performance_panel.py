"""Performance panel — LLM latency and tool execution timing."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from penguin.dashboard.queries.server_logs import (
    parse_llm_attempts,
    parse_tool_exec_done,
    clear_cache,
    cache_status,
)


def render():
    st.header("Performance")

    # ── Refresh control ────────────────────────────────────────────────
    col1, col2 = st.columns([3, 1])
    with col2:
        force_refresh = st.button("🔄 Refresh from logs", key="perf_refresh")

    with col1:
        cache_info = cache_status()
        if cache_info["keys"]:
            st.caption(f"Log cache: {len(cache_info['keys'])} cached datasets")
        else:
            st.caption("Log cache: empty (will parse on first load)")

    # ── LLM Latency ────────────────────────────────────────────────────
    st.subheader("LLM Response Time")

    llm_data = parse_llm_attempts(force_refresh=force_refresh)
    if not llm_data:
        st.info("No LLM attempt data found in server logs. This tab requires "
                "`engine.llm_attempt.done` log lines.")
        return

    df = pd.DataFrame(llm_data)

    # Duration histogram
    if "duration_ms" in df.columns:
        durations = df["duration_ms"].dropna()
        if len(durations) > 0:
            fig = px.histogram(
                df,
                x="duration_ms",
                nbins=40,
                title="LLM Response Time Distribution (ms)",
                labels={"duration_ms": "Duration (ms)", "count": "Count"},
                height=350,
            )
            st.plotly_chart(fig, width="stretch")

            # P50 / P95 / P99
            p50 = durations.median()
            p95 = durations.quantile(0.95)
            p99 = durations.quantile(0.99)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("P50", f"{p50:.0f}ms")
            c2.metric("P95", f"{p95:.0f}ms")
            c3.metric("P99", f"{p99:.0f}ms")
            c4.metric("Total Calls", len(durations))

    # Duration by status
    if "status" in df.columns and "duration_ms" in df.columns:
        grouped = (
            df.groupby("status")["duration_ms"]
            .agg(["count", "mean", "median", "min", "max"])
            .reset_index()
        )
        grouped.columns = [
            "Status", "Count", "Mean (ms)", "Median (ms)", "Min (ms)", "Max (ms)"
        ]
        for col in ["Mean (ms)", "Median (ms)", "Min (ms)", "Max (ms)"]:
            grouped[col] = grouped[col].fillna(0).round(0).astype(int)
        st.subheader("Latency by Status")
        st.dataframe(grouped, width="stretch", hide_index=True)

    # ── Tool Execution Performance ─────────────────────────────────────
    st.subheader("Tool Execution Performance")

    tool_data = parse_tool_exec_done(force_refresh=force_refresh)
    if tool_data:
        df_tools = pd.DataFrame(tool_data)

        if "tool_name" in df_tools.columns and "duration_ms" in df_tools.columns:
            # Average duration by tool
            tool_avg = (
                df_tools.groupby("tool_name")["duration_ms"]
                .agg(["mean", "median", "count", "sum"])
                .reset_index()
                .sort_values("mean", ascending=False)
            )
            tool_avg.columns = [
                "Tool", "Mean (ms)", "Median (ms)", "Count", "Total (ms)"
            ]
            for col in ["Mean (ms)", "Median (ms)", "Total (ms)"]:
                tool_avg[col] = tool_avg[col].fillna(0).round(0).astype(int)

            fig = px.bar(
                tool_avg.head(15),
                x="Tool",
                y="Mean (ms)",
                title="Average Tool Execution Time (Top 15)",
                labels={"Mean (ms)": "Mean Duration (ms)"},
                height=400,
                color="Count",
                color_continuous_scale="Viridis",
            )
            st.plotly_chart(fig, width="stretch")

            # Tool detail table
            st.subheader("Tool Execution Detail")
            df_tools_display = df_tools[
                ["tool_name", "duration_ms", "status", "output_bytes", "truncated"]
            ].copy()
            df_tools_display.columns = [
                "Tool", "Duration (ms)", "Status", "Output (bytes)", "Truncated"
            ]
            df_tools_display["Duration (ms)"] = df_tools_display["Duration (ms)"].fillna(0).round(0).astype(int)
            st.dataframe(
                df_tools_display.sort_values("Duration (ms)", ascending=False).head(20),
                width="stretch",
                hide_index=True,
            )

            # Output size scatter
            if "output_bytes" in df_tools.columns and "duration_ms" in df_tools.columns:
                fig = px.scatter(
                    df_tools,
                    x="duration_ms",
                    y="output_bytes",
                    color="tool_name",
                    title="Tool Execution Time vs Output Size",
                    labels={
                        "duration_ms": "Duration (ms)",
                        "output_bytes": "Output Size (bytes)",
                    },
                    height=400,
                )
                st.plotly_chart(fig, width="stretch")
    else:
        st.info("No tool execution data found in server logs.")