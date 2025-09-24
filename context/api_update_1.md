# API Update 1 – Multi‑Agent & Sub‑Agent

Base: `/api/v1` (no auth yet; plan for CORS + auth later)

Content type: `application/json` for requests/responses. Errors use `application/problem+json` (RFC 7807).

ID rules: `^[a-z0-9_-]{1,64}$` (lowercase), unique per runtime.

## Error Shape (Problem+JSON)

```json
{
  "type": "about:blank",
  "title": "Invalid model id",
  "status": 400,
  "detail": "model_config_id 'kimi-lite' not found",
  "instance": "/api/v1/agents",
  "extras": {"field": "model_config_id"}
}
```

## Agents

### GET /agents
Returns the full roster (same as `core.get_agent_roster()`).

Query params (optional): `active=true|false`, `parent=default`, `is_sub=true|false`.

### GET /agents/{id}
Returns a single agent profile (same as `core.get_agent_profile(id)`).

### POST /agents (spawn)
Create a top‑level or sub‑agent. Payload (minimal):

```json
{
  "id": "researcher",
  "parent": "default",          // optional → sub‑agent when present
  "model_config_id": "kimi-lite", // REQUIRED (model id). If unknown, see model_overrides
  "persona": "research",          // optional; supplemental only
  "system_prompt": "...",         // optional
  "share_session": false,          // default false
  "share_context_window": false,   // default false
  "shared_cw_max_tokens": 512,     // optional; applies when isolated CW
  "model_overrides": {             // optional fallback (used only when model_config_id missing)
    "model": "moonshotai/kimi-k2-0905",
    "provider": "openrouter",
    "client_preference": "openrouter"
  },
  "default_tools": ["read_file"],  // optional metadata only
  "activate": true,                 // optional
  "initial_prompt": "Summarize docs" // optional – enqueue after spawn
}
```

201 Created → profile; 400 (Problem+JSON) when `model_config_id` is invalid and no viable `model_overrides` supplied.

### PATCH /agents/{id}
Update pause state or light metadata.

```json
{ "paused": true }
```

200 OK → updated profile. (Reserve full reconfiguration for future.)

### DELETE /agents/{id}
Unregister an agent. Query: `preserve_conversation=true|false` (default: true). Returns 200 with `{ "removed": true }` or Problem+JSON if blocked (e.g., has active sub‑agents).

## Messaging

### POST /messages
General message ingress. Prefer single recipient per request; clients submit multiple requests for multi‑target. Use channels for broadcast semantics.

```json
{
  "recipient": "researcher",        // "human" or agent id
  "content": "status update",       // string or structured payload
  "message_type": "message",        // message|status|action
  "channel": "dev-room",            // optional
  "metadata": {"trace_id": "..."}  // optional
}
```

200 `{ "sent": true }` or Problem+JSON. (For multiple recipients: send separate requests, or use a future broadcast endpoint.)

### WebSocket /ws/messages
Bidirectional events. Query filters: `agent_id`, `channel`, `session_id`. Messages use the same envelope fields and include `agent_id`, `recipient_id`, `message_type`, `channel`, `metadata`, `timestamp`.

## Conversations

### GET /conversations/{id}/history
Query params: `limit`, `include_system=true|false`, `agent_id`, `channel`, `message_type`.

Returns flat events with provenance (agent_id, recipient_id, message_type, channel, metadata).

### GET /agents/{id}/history (optional)
Convenience alias to current (active) session for agent `{id}`. Pros: simple URL per agent. Cons: ambiguous when multiple conversations exist; requires clear “current session” semantics. Alternatives:

- Always require a conversation id via `GET /conversations/{conversation_id}/history`.
- Support explicit session routing under the agent resource:

  - `GET /agents/{id}/sessions` → list of sessions for the agent (ids, created_at, last_active, counts)
  - `GET /agents/{id}/sessions/{session_id}/history` → history for that agent’s specific session

This pattern avoids ambiguity while remaining agent‑centric. We can still keep `GET /agents/{id}/history` as a convenience for “current session”.

## Telemetry

### GET /telemetry
Aggregate gauges and counters:

```json
{
  "version": "…",
  "agents": {
    "total": 3,
    "active": 1,
    "paused": 1,
    "sub_agents": 2
  },
  "messages": {
    "total": 124,
    "by_type": {"message": 100, "status": 20, "action": 4},
    "by_channel": {"dev-room": 60, "ops-room": 10},
    "last_message_at": "2025-09-23T00:00:00Z"
  },
  "tokens": {
    "overall": {"current_total_tokens": 1200, "max_tokens": 128000},
    "per_agent": {"default": {"current_total_tokens": 1200, "max_tokens": 128000}}
  },
  "rates": {
    "1m": {"messages": 10},
    "5m": {"messages": 42},
    "15m": {"messages": 120}
  }
}
```

### WebSocket `/api/v1/ws/telemetry`
- Streams the same telemetry payload on an interval (default 2s).
- Query params: `interval` (seconds) and optional `agent_id` to focus on a single agent (filters `agents` and `tokens.per_agent`).

## CORS

Expose CORS toggles for the REST/WebSocket servers (origin allowlist via env/config). No auth now; plan for API keys or OAuth/JWT later.

## Notes / Deferred

- Rate limiting & concurrency: defer for now (documented in this file; to be revisited with usage data).
- Multiple recipients: not supported in POST /messages; prefer one request per target or channel broadcasts.
- Permission/budget engine: not implemented; personas/models recorded but not enforced.
