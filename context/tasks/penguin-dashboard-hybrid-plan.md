# Penguin Dashboard: Hybrid Observability Plan

**Status:** Phase 1 delivered. See `penguin/dashboard/` for the built dashboard.

## Objective

Make Penguin's execution observable — cost, traces, errors, context health — without
building a full observability stack from scratch.

## Guiding principle

Adopt where the open-source community has already solved the problem well.
Build custom only where Penguin's data doesn't fit existing tools.

This means two things:

1. **Langfuse (self-hosted, Phase 2)** for cost tracking, trace waterfalls, token
   analytics, and evaluation workflows. Langfuse's trace/span/observation model maps
   directly to Penguin's `runtime_events.db` structure.

2. **A lightweight Streamlit dashboard (Phase 1, now)** for the data that Langfuse
   will never understand — context window health from server logs, task lifecycle
   from `projects.db`, and full session transcript browsing.

## Relationship to the existing plan

`context/tasks/penguin-dashboard-observability-plan.md` is the comprehensive
long-term vision: events, traces, metrics, artifacts, full custom UI, OTLP export,
redaction, and Link alignment.

This hybrid plan is a **pragmatic first phase** that delivers value now by standing
on the shoulders of existing open-source work. The two plans coexist. The existing
plan is a reference for what to build if the hybrid approach proves insufficient
or if Penguin's specific needs outgrow Langfuse's capabilities.

## Decisions

These were settled in conversation with the human author:

| Question | Decision |
|----------|----------|
| Streamlit vs. integrated into penguin-web? | **Separate process** (Streamlit). Can migrate into the web server later if warranted. |
| Langfuse vs. Streamlit only? | **Streamlit now.** Langfuse Phase 2 after the dashboard proves useful. |
| Replay vs. live bridge for Langfuse? | **Replay.** Batch script, not a live bridge. |
| Dashboard in workspace or repo? | **In the repo.** `penguin/dashboard/`. Penguin is a modular monolith monorepo, and git is already here. |
| Replace or coexist with existing plan? | **Coexist as a first phase.** This plan is the pragmatic entry point; the existing plan is the long-term reference. |
| Log parser cache strategy? | **Build-time cache** with a refresh button. Parse server logs once, cache structured results in SQLite, re-parse on demand. |
| Privacy and redaction? | **Local developer is trusted, show everything.** Redaction and privacy gating is a Phase 2 concern when Langfuse integration happens. |

## Data sources

All paths are relative to `PENGUIN_WORKSPACE` (default: `~/penguin_workspace`).

| Source | Path | What it contains |
|--------|------|-----------------|
| `runtime_events.db` | `runtime_events/runtime_events.db` | Structured event stream: session lifecycle, LLM calls with cost, tool executions, VCS events |
| `server-logs/` | `server-logs/` | Rotated text files with `engine.context.snapshot`, `engine.llm_attempt.done`, `tool.exec.done` — timing, tokens, category budgets, cache hits |
| `projects.db` | `projects.db` | Task lifecycle, execution records, state transitions, token usage |
| `conversations/` | `conversations/` | JSON session files with full message transcripts, tool outputs, checkpoints |
| `session_index.json` | `conversations/session_index.json` | Session metadata: timestamps, message counts, titles |

## Part 1: Streamlit Dashboard (Phase 1 — Now)

### Why Streamlit

- **Zero infrastructure** — `pip install streamlit && streamlit run app.py`
- **Direct SQLite** — no API layer, no SDK, no Docker
- **Fast to build** — ~400 lines for the full set of views
- **Interactive** — filters, date ranges, drill-downs
- **Static data friendly** — can parse rotated log files, JSON sessions, etc.

### Dashboard tabs

#### Tab 1: Cost & Usage
```
Source: runtime_events.db
Queries: grouped by model, session, day
Charts: cost over time (line), top models by token usage (bar), cache hit ratio
```

Every LLM call in the event DB has cost data. This is the same data you'd push to
Langfuse, but available immediately without Docker.

#### Tab 2: Performance
```
Source: server-logs/ (parsed) + runtime_events.db
Queries: LLM latency by model/provider, tool execution time by tool
Charts: latency distribution (histogram), slowest tools (bar), P50/P95/P99 table
```

The server logs have `engine.llm_attempt.done` with duration_ms and
`tool.exec.done` with duration_ms. Parse the rotated files, extract structured rows,
query like a database.

#### Tab 3: Reliability
```
Source: runtime_events.db + server-logs/ (parsed)
Queries: error counts by tool, by session, over time
Charts: error rate trend (line), errors by tool (stacked bar), sessions with errors (table)
```

#### Tab 4: Context Window Health
```
Source: server-logs/ (parsed) — specifically engine.context.snapshot lines
Queries: category token budgets, largest messages, trimming events
Charts: context fill rate (gauge), category breakdown (stacked bar), trimming events over time
```

This is the most Penguin-specific view. Langfuse will never understand category
budgets or per-category token pressure. The server logs are the only source.

#### Tab 5: Task & Project Tracking
```
Source: projects.db
Queries: task lifecycle, state transitions, execution records
Charts: task status distribution (pie), task duration (bar), state transition DAG
```

#### Tab 6: Session Explorer
```
Source: conversations/ + session_index.json
Queries: session metadata, message counts, date ranges
Charts: sessions over time (calendar heatmap), session detail (expandable rows)
```

### Server-logs parser strategy

The log parser reads rotated text files and extracts structured rows.
This is inherently fragile — log formats change, fields get added, etc.

**Build-time cache with refresh button:** Parse on first load, cache structured
results in a SQLite table (`dashboard_cache`). Only re-parse when the user clicks
refresh or when new log files appear. This avoids slow load times for large log
directories while keeping data fresh enough.

### Privacy strategy

**Phase 1: Show everything.** The dashboard reads local files on a local developer
machine. The developer is trusted. No redaction gates, no click-to-reveal.

**Phase 2 (Langfuse):** Privacy and redaction will be seriously addressed when
Langfuse integration is added. The existing `penguin-dashboard-observability-plan.md`
has the privacy model to follow.

### File layout

```
penguin/dashboard/
├── app.py                 ← Streamlit entry point (streamlit run penguin/dashboard/app.py)
├── __init__.py
├── queries/
│   ├── __init__.py
│   ├── runtime_events.py  ← SQL queries against runtime_events.db
│   ├── server_logs.py     ← Log parser (rotated files → structured rows, SQLite cache)
│   └── projects.py        ← SQL queries against projects.db
├── components/
│   ├── __init__.py
│   ├── cost_panel.py      ← Cost & Usage tab
│   ├── performance_panel.py ← Performance tab (LLM latency, tool timing)
│   ├── reliability_panel.py ← Reliability tab (errors, stuck tools, log levels)
│   ├── context_panel.py   ← Context Window Health tab (category budgets, trimming)
│   ├── task_panel.py      ← Task & Project Tracking tab
│   └── session_explorer.py ← Session Explorer tab
├── .log_cache/            ← Auto-created SQLite cache for parsed server logs
├── dashboard.html         ← Legacy FastAPI dashboard (deprecated, kept for reference)
└── README.md
```

## Part 2: Langfuse Integration (Phase 2 — Future)

### Why Langfuse (when we get there)

- **Open source (AGPL)** — matches Penguin's license, no SaaS lock-in
- **Self-hosted via Docker** — data stays local
- **Trace/span model** — maps directly to Penguin's session → LLM call → tool call structure
- **Cost tracking** — built-in cost attribution per model, per session, per trace
- **Python SDK** — can read from SQLite and push custom events
- **Mature UI** — trace waterfalls, token charts, eval dashboards, cost breakdowns
- **Active development** — one of the most actively maintained open-source observability tools

### How it maps

| Penguin concept | Langfuse concept |
|----------------|-----------------|
| Session | `Trace` (grouped by session_id) |
| LLM call (message.part.updated) | `Generation` or `Observation` with usage metadata |
| Tool execution (tool_action_lifecycle) | `Span` with start/end, status, duration |
| Session lifecycle events | `Trace.metadata` |
| Token counts + cost | `Generation.usage` |
| Agent_id | `Trace.tags` or `Trace.metadata` |

### The replay script (when we build it)

A single Python script (~150 lines) that:

1. Reads `runtime_events.db` grouped by session
2. Creates a Langfuse `Trace` per session
3. For each `message.part.updated` (LLM call): creates a `Generation` with token
   counts, cost, model name
4. For each `tool_action_lifecycle`: creates a `Span` with tool name, duration, status
5. Attaches lifecycle events as `Trace.metadata`
6. Calls `langfuse.flush()` to export

This is a **replay/batch ingestion**, not a live bridge. Run it on demand after a
session, or as a cron job.

### What Langfuse would give us

- Trace waterfall with span hierarchy
- Cost breakdown by model, by session, over time
- Token usage charts (input, output, reasoning, cache)
- Latency distributions per model
- Evaluation workflows (score runs, compare models)
- Search/filter traces by metadata, tags, model
- Export to JSONL

### What Langfuse won't cover

These remain the Streamlit dashboard's job even after Langfuse is added:

- Context window health (category budgets, trimming, per-category token pressure)
- Server log analysis beyond what's in the event DB
- Task lifecycle DAG from projects.db
- Full session transcript browsing

## Combined picture

```
penguin/                     ← repo root
├── ...
└── dashboard/               ← Phase 1 (this week)
    ├── app.py               ← Streamlit entry point
    ├── queries/             ← data access
    ├── components/          ← UI panels
    └── README.md

penguin_workspace/           ← runtime data
├── runtime_events.db
├── projects.db
├── server-logs/
├── conversations/
│   └── session_index.json
└── memory_db/

scripts/                     ← Phase 2 (future)
└── replay-to-langfuse.py    ← optional Langfuse bridge
```

## Execution plan

### Phase 1: Streamlit dashboard (delivered)

Everything in Phase 1 is built. The dashboard lives at `penguin/dashboard/` and has
six fully-implemented tabs:

1. **Cost & Usage** — reads `runtime_events.db`, shows cost by model, daily cost, cache hit ratio, most expensive sessions
2. **Performance** — parses `engine.llm_attempt.done` and `tool.exec.done` from server logs, shows latency histograms, P50/P95/P99, tool timing
3. **Reliability** — shows tool call summary, orphaned tool calls, error/warning log levels from server logs
4. **Context Window Health** — parses `engine.context.snapshot` from server logs, shows category token distribution, token pressure over time, largest messages
5. **Task & Project** — reads `projects.db`, shows task status distribution, execution timeline, token usage
6. **Session Explorer** — reads `runtime_events.db` + `conversations/`, shows session list, event detail, raw messages

To run:
```bash
cd /path/to/Code/Penguin/penguin
streamlit run penguin/dashboard/app.py --server.port 8501
```

### Phase 2: Langfuse integration (future, after Phase 1 proves useful)

1. Set up `docker-compose.yml` for Langfuse (ClickHouse + Postgres + Redis + Web)
2. Write `replay-to-langfuse.py` — reads runtime_events.db, pushes to Langfuse
3. Verify trace waterfalls, cost charts, token analytics in Langfuse UI
4. Add privacy/redaction layer before any non-local use
5. Optionally add cron job for periodic replay

### Phase 3: Evaluate and iterate

- Which tabs are actually useful vs. decorative?
- Is Langfuse providing enough value over the Streamlit dashboard to justify Docker?
- Should any of the Streamlit data sources be pushed into Langfuse instead?
- Should the dashboard be integrated into the web server instead of a separate Streamlit app?