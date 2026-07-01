---
sidebar_position: 2
---

# Runtime Events and Durable Replay

Penguin's runtime event envelope is the canonical public event shape for live UI
updates, SSE replay, TUI/OpenCode projections, logs, and future analytics.
OpenCode-shaped payloads are compatibility projections of this envelope, not the
source of truth.

## RuntimeEvent Envelope

Runtime events are built in `penguin.system.runtime_events`. The public schema is
versioned as `penguin.runtime_event.v1` and includes:

| Field | Purpose |
|-------|---------|
| `id` | Stable replay identity, used as the public SSE/OpenCode event id |
| `schema_version` | Runtime event schema version |
| `type` | Event type such as `session.created`, `message.part.updated`, or `todo.updated` |
| `category` | Coarse category such as `session_lifecycle`, `stream_chunk`, `tool_action_lifecycle`, `file_diff`, `task_run_state`, `provider_model_state`, or `cwm_token_usage` |
| `source` | Event producer, normally `penguin.backend` |
| `subject` | Human-readable subject derived from scope and event type |
| `time` | Millisecond timestamp |
| `stream_id` | Replay stream, usually session-scoped when a session is known |
| `sequence` | Monotonic per-stream sequence number |
| `scope` | Normalized `session_id`, `conversation_id`, `agent_id`, `task_id`, `run_id`, `project_id`, and `directory` fields when present |
| `correlation` | Correlation ids such as request/message/tool-call ids |
| `actor` | Explicit actor metadata when supplied by the caller |
| `privacy` | Redaction classification and redacted field list |
| `payload` | Redacted event payload |
| `projections` | Optional compatibility projections |

OpenCode-compatible event payloads emitted on the `EventBus` should be wrapped
with `wrap_opencode_event(...)` or flow through service helpers that do the same.
The wrapper builds a `runtime_event`, then projects the public OpenCode fields
(`id`, `order`, `time`, `type`, and `properties`) from that envelope.

## Ownership

| Area | Owner |
|------|-------|
| Envelope construction, normalization, redaction | `penguin.system.runtime_events` |
| Durable append/replay/retention | `penguin.system.runtime_event_ledger` |
| EventBus recording hook and SSE replay | `penguin.web.sse_events` |
| OpenCode event normalization and recording helpers | `penguin.web.services.opencode_events` |
| Session lifecycle event helpers | `penguin.web.services.session_events` |
| Stream/status/user-message bridge helpers | `penguin.core_runtime.stream_events` |
| Todo/LSP/action bridge helpers | `penguin.core_runtime.action_events` |
| Transcript tool-part redaction | `penguin.core_runtime.opencode_transcript` |

`PenguinCore` holds the shared `EventBus` reference and exposes compatibility
methods. It should not own runtime event schema decisions, replay policy, or
OpenCode payload shaping.

## Durable Ledger

The durable runtime event ledger is a SQLite-backed store for redacted public
`RuntimeEvent` envelopes. It is not the conversation transcript, not private
diagnostics, and not a replacement for persisted session state.

Default path:

```text
${WORKSPACE_PATH}/runtime_events/runtime_events.db
```

Environment overrides:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PENGUIN_RUNTIME_EVENT_LEDGER_PATH` | workspace runtime-events DB | Override SQLite path |
| `PENGUIN_RUNTIME_EVENT_LEDGER_MAX_EVENTS` | `100000` | Maximum retained rows |
| `PENGUIN_RUNTIME_EVENT_LEDGER_MAX_AGE_DAYS` | `14` | Age-based retention window |
| `PENGUIN_RUNTIME_EVENT_LEDGER_MAX_BYTES` | `268435456` | Soft DB/WAL size limit |
| `PENGUIN_RUNTIME_EVENT_LEDGER_CLEANUP_INTERVAL_SECONDS` | `60` | Minimum cleanup interval |

Append is best-effort from the live event path: ledger failures should not stop
live UI delivery. Cleanup checkpoints the SQLite WAL before measuring size, skips
size pruning when WAL truncation fails, and rolls back append transactions on
failure.

## SSE Replay

`GET /api/v1/events/sse` streams OpenCode-compatible projections of runtime
events. It supports:

- `session_id` or `conversation_id` filters
- `agent_id` filter
- `directory` filter
- `last_event_id` query parameter
- `Last-Event-ID` header

The per-connection queue only buffers live delivery for currently connected
clients. Durable replay comes from the runtime event ledger. A reconnecting
client should send the last delivered event id; Penguin replays retained events
after that id and then resumes live streaming.

If the requested cursor is no longer retained, Penguin emits a
`server.replay_gap` event with the missing `lastEventID`, oldest retained event
id, newest retained event id, and `reason="last_event_id_not_available"`.

## Testing Expectations

Default tests for runtime events should be deterministic and offline:

- reset sequence counters in tests that assert event ids or ordering
- use fake `EventBus` instances and in-process SSE/service tests
- assert stable envelope fields and public projections, not wall-clock values
- verify redaction preserves safe telemetry such as token usage while removing
  credential fields
- keep live provider and browser checks opt-in

