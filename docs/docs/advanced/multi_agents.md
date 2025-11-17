---
sidebar_position: 7
---

# Multi-Agent Orchestration

Penguin can coordinate multiple high-level agents within the same runtime so each persona, integration, or automation surface can maintain its own identity while sharing platform capabilities.

## Why Multi-Agent?

- **Persona separation**: Keep product, support, and engineering assistants isolated while reusing the same deployment.
- **Integration shims**: Route SaaS-specific behaviors (Slack, GitHub, PagerDuty) to focused agents that understand the integration contract.
- **Parallel exploration**: Evaluate alternative approaches by letting different agents pursue independent strategies against the same request history.

## Core Concepts

### Agent Identity

Every API call accepts an optional `agent_id`. When provided, Penguin binds the request to an agent-scoped conversation, tool inventory, and runtime configuration. Agents that omit `agent_id` fall back to the default/global persona.

### Shared Infrastructure

All agents share:

- The same persistent memory store (vector search + summaries)
- Workspace artifacts (projects, checkpoints, context files)
- Core diagnostics and logging pipelines

This allows cross-agent recall and governance while still keeping per-agent execution state isolated.

### Isolation Boundaries

For each `agent_id`, Penguin tracks:

- Active conversation history (messages, checkpoints, run modes)
- Currently loaded model / provider (if agent performs a model switch)
- Tool enablement and throttling
- Task execution progress and streaming callbacks

Isolation ensures that one misbehaving agent does not leak context or mutate another agent's control flow.

## Getting Started

### REST API Example

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
        "text": "Summarize the latest tickets",
        "agent_id": "support",
        "streaming": false
      }'
```

Subsequent requests using `agent_id: "support"` will continue the same conversation, whereas another persona such as `"engineering"` receives a separate message log even though both run on the same server.

### Python Client Example

```python
import asyncio

from penguin.api_client import ChatOptions, PenguinClient


async def run() -> None:
    async with PenguinClient() as client:
        response = await client.chat(
            "Generate a changelog for v0.4.0",
            options=ChatOptions(
                context={"repository": "penguin"},
                agent_id="release",
            ),
        )
        print(response)


asyncio.run(run())
```

The client mirrors the REST surface: wrap per-call settings in `ChatOptions` (or `TaskOptions` for tasks) and supply an `agent_id` to stay on the same persona.

### Websocket Streaming

Streaming endpoints accept the same field. This allows dashboards to multiplex multiple personas over a single connection while routing messages correctly.

## Operational Guidance

- **Naming**: Use short, URL-safe names (alphanumeric plus `_` or `-`).
- **Config management**: Persist agent-specific defaults (model, provider, tools) in your own metadata store and supply them per request.
- **Observability**: Include `agent_id` when forwarding events to logging or analytics for clearer dashboards.
- **Access control**: The agent router lives in the API tier; combine it with auth middleware to enforce tenant or role-specific routing.
- **Coordinator policies**: The `MultiAgentCoordinator` now exposes explicit helpers for round-robin routing, role chains, broadcasts, and lite-agent fallbacks. Register role assignments up front so `Engine.run_task` and RunMode can pick the right persona automatically via `agent_role` context.
- **Conversation telemetry**: Use `GET /api/v1/conversations/{id}/history` (or `PenguinClient.get_conversation_history`) to retrieve flat logs tagged with `agent_id`, `recipient_id`, and `message_type`. Pair with MessageBus `channel` filters to stream the portions relevant to a team room.
- **Runtime metrics**: The telemetry collector aggregates message, agent, room, and task statistics. Call `GET /api/v1/telemetry` (or `PenguinClient.get_telemetry_summary`) to feed dashboards; the standalone app in `dashboard/app.py` shows a reference implementation.
- **Shared charter:** Treat `context/TASK_CHARTER.md` (or `.json`) as the single source of truth for task goal, normalized paths, acceptance criteria, and QA checklist. Planner writes/updates it, implementer records what changed and how it was verified, and QA signs off against it. This keeps parent + sub-agents aligned without inventing new wires.
- **QA gate:** A run finishes only after the QA persona (or equivalent validation agent) marks every charter item complete and sends the verdict back to the parent or human. If criteria are unmet, QA loops the issue back through the MessageBus rather than silently finishing.
- **No placeholders:** If the charter still contains placeholder text ("Pending", missing paths, unclear goals), implementers/QA should halt and send a status message back instead of guessing. Escalations travel over the same MessageBus so the parent agent can tighten the spec before work continues.
- **PenguinAgent helper:** When scripting or testing, `from penguin import PenguinAgent` provides a synchronous wrapper around `PenguinCore` that auto-loads project docs (`PENGUIN.md`, `AGENTS.md`, README), discovers charter files, and exposes helper methods for registering personas or sending MessageBus events.

## Roadmap

Upcoming milestones include:

- Policy-based routing and fallback between agents
- Dynamic registration APIs so agents can be created/removed at runtime
- Enhanced diagnostics that tag token and latency metrics by `agent_id`
- Public REST APIs (`/api/v1/agents`, `/api/v1/messages`, `/api/v1/telemetry`) plus
  WebSocket streams (`/api/v1/ws/messages`, `/api/v1/ws/telemetry`) so external
  services can orchestrate multi-agent workflows without the CLI.
- UI affordances in the web console for monitoring multi-agent deployments

Looking for finer-grained delegation patterns? Continue with [Sub-Agent Delegation](sub_agents.md).
