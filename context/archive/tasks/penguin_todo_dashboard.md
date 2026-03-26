# Penguin Dashboard - Implementation Plan

## Overview

A dashboard for visualizing and controlling Penguin's internals, accessible via the web interface at a separate `/dashboard` route. The dashboard provides real-time observability into agents, token usage, engine execution, tools, and memory systems.

## Goals

1. **Visibility**: See what's happening inside Penguin in real-time
2. **Control**: Pause/resume agents, switch models, manage checkpoints
3. **Debugging**: Trace tool executions, message flows, and errors
4. **Optimization**: Monitor token budgets and identify inefficiencies

## Existing API Infrastructure

These endpoints are already available in `penguin/web/routes.py`:

| Endpoint | Type | Description |
|----------|------|-------------|
| `/api/v1/telemetry` | GET | Telemetry summary (agents, tokens, performance) |
| `/api/v1/ws/telemetry` | WebSocket | Real-time telemetry stream |
| `/api/v1/agents` | GET | List registered agents with profiles |
| `/api/v1/agents/{id}` | GET/PATCH/DELETE | Agent CRUD + pause/resume |
| `/api/v1/token-usage` | GET | Token usage statistics |
| `/api/v1/health` | GET | Comprehensive health status |
| `/api/v1/events/ws` | WebSocket | Event stream (messages, tools, progress) |
| `/api/v1/models` | GET | Available models |
| `/api/v1/models/switch` | POST | Switch active model |
| `/api/v1/conversations/{id}/history` | GET | Conversation history |

## Implementation Phases

### Phase 1: Foundation (Current)
- [x] Document existing API endpoints
- [x] Create `/dashboard` route serving `dashboard.html` (in `app.py`)
- [x] Implement Token Budget Visualizer panel
- [x] Basic layout with navigation tabs
- [x] Agent Status panel (basic)
- [x] Engine Loop panel (basic)
- [x] Tool Execution Timeline panel (basic)

### Phase 2: Core Panels
- [ ] Agent Status Panel (list, state, pause/resume)
- [ ] Engine Loop Visualizer (iterations, stop conditions)
- [ ] Tool Execution Timeline (waterfall view)
- [ ] Message Flow Panel (MessageBus traffic)

### Phase 3: Advanced Features
- [ ] Project/Task DAG visualization
- [ ] Memory & Retrieval Panel
- [ ] Model Selector with live switching
- [ ] Checkpoint Manager UI

### Phase 4: Polish
- [ ] WebSocket-based live updates for all panels
- [ ] Dark/light theme toggle
- [ ] Export diagnostics as JSON
- [ ] Mobile-responsive layout

## UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Penguin Dashboard                              [Chat] [Dashboard]  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────┐  ┌─────────────────────────────────┐  │
│  │   Token Budget          │  │   Agent Status                  │  │
│  │   ━━━━━━━━━━━━━━━━━━━━  │  │   ┌─────┐ ┌─────┐ ┌─────┐      │  │
│  │   SYSTEM    ████░ 10%   │  │   │deflt│ │plan │ │ qa  │      │  │
│  │   CONTEXT   ████████ 35%│  │   │ ● ▶ │ │ ○ ⏸│ │ ○ ▶ │      │  │
│  │   DIALOG    ██████████  │  │   └─────┘ └─────┘ └─────┘      │  │
│  │   SYS_OUT   ██░░░░ 5%   │  │                                 │  │
│  │                         │  │   Active: default               │  │
│  │   45,231 / 128,000      │  │   Messages: 24 | Tools: 8       │  │
│  └─────────────────────────┘  └─────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │   Engine Loop                                    Iter 3/5000 │  │
│  │   ────●─────────────────────────────────────────────────────  │  │
│  │                                                               │  │
│  │   ┌─────────────────────────────────────────────────────────┐│  │
│  │   │ 1. LLM Request (claude-3.5-sonnet)        ✓ 1.2s       ││  │
│  │   │ 2. Parse Actions                          ✓ 12ms       ││  │
│  │   │ 3. Execute: read_file → src/core.py       ✓ 45ms       ││  │
│  │   │ 4. Check Stop Conditions                  → continuing  ││  │
│  │   └─────────────────────────────────────────────────────────┘│  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │   Tool Execution Timeline                                     │  │
│  │   ├── read_file (src/core.py)                    45ms  ✓    │  │
│  │   ├── grep_search ("def process")                120ms ✓    │  │
│  │   ├── write_file (src/utils.py)                  30ms  ✓    │  │
│  │   └── bash (pytest tests/)                       2.4s  ⏳   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Token Budget Panel - Detailed Design

### Data Source
- Primary: `/api/v1/token-usage` endpoint
- Real-time: Subscribe to `/api/v1/ws/telemetry` for live updates

### Expected Response Shape
```json
{
  "usage": {
    "total_tokens": 45231,
    "max_context_window": 128000,
    "categories": {
      "system": { "tokens": 2100, "budget_pct": 10 },
      "context": { "tokens": 15800, "budget_pct": 35 },
      "dialog": { "tokens": 22500, "budget_pct": 50 },
      "system_output": { "tokens": 4831, "budget_pct": 5 }
    },
    "trimming_events": [
      { "timestamp": "...", "category": "system_output", "tokens_removed": 1200 }
    ]
  }
}
```

### Visual Components
1. **Overall Progress Bar**: Total usage vs max context window
2. **Category Bars**: Per-category usage with budget limits
3. **Warning States**: Yellow >80%, Red >95%
4. **Trimming Log**: Recent truncation events (collapsible)

### Interactivity
- Hover: Show exact token counts
- Click category: Expand to show message breakdown
- Real-time: Animate bar changes on WebSocket updates

## File Structure

```
penguin/web/
├── static/
│   ├── index.html          # Chat interface (existing)
│   └── dashboard.html      # New dashboard interface
├── routes.py               # Add /dashboard route
└── app.py                  # Mount static files
```

## Technical Notes

1. **Framework**: Continue using Vue 3 (CDN) + Tailwind for consistency
2. **Charts**: Consider Chart.js or lightweight D3 for visualizations
3. **WebSocket**: Reuse existing `/api/v1/ws/telemetry` infrastructure
4. **State**: Vue reactive refs, no external state management needed
5. **Polling Fallback**: For browsers without WebSocket, poll every 2s

## Next Steps

1. Create `dashboard.html` with Token Budget panel prototype
2. Add route in `routes.py` to serve dashboard
3. Test with mock data, then wire up to real endpoints
4. Iterate on additional panels
