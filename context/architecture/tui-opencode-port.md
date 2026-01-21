# OpenCode TUI Port for Penguin

## Status

Planned. This document defines the target architecture, SSE-first streaming model, and a minimal-change fork strategy to reuse OpenCode's TUI for Penguin.

## Goals

- Adopt the OpenTUI + SolidJS stack for Penguin's CLI/TUI.
- Make SSE the eventual default streaming mechanism across clients.
- Preserve OpenCode's UI patterns with minimal rewrites.
- Align Penguin event emissions with OpenCode's message/part model.
- Add explicit licensing and attribution for reused code.

## Context

Penguin currently exposes streaming over WebSockets via `/api/v1/chat/stream` and emits UI events through an EventBus. OpenCode's TUI consumes an SSE event stream and updates a local store via message/part events. To minimize UI rewrites, Penguin should expose an SSE stream compatible with OpenCode's event envelope and data model.

Relevant references:

- `architecture.md`
- `docs/docs/api_reference/api_server.md`
- `docs/docs/api_reference/core.md`
- `reference/opencode/packages/opencode/src/cli/cmd/tui/*`

## Target Architecture (Client/Server)

### Server

- FastAPI remains the core API server.
- Add SSE as a first-class stream endpoint for UI and client consumption.
- Emit message/part events aligned to OpenCode's schema.
- Retain WebSocket endpoints during transition, then demote to legacy.

### Client

- Create a new package `penguin-tui` by forking OpenCode's TUI.
- Replace the OpenCode SDK client with a Penguin API client.
- Keep SolidJS providers, store, and components intact where possible.
- Use OpenTUI rendering and tree-sitter parser pipeline unchanged.

## SSE-First Event Model

### Event Envelope

All SSE events use the OpenCode-style envelope:

```json
{
  "type": "message.part.updated",
  "properties": {
    "part": { "id": "part_123", "messageID": "msg_123", "sessionID": "sess_123" },
    "delta": "token chunk"
  }
}
```

### Required Event Types

- `server.connected`
- `session.updated` (optional for UI session list)
- `message.updated`
- `message.removed`
- `message.part.updated` (streaming deltas)
- `message.part.removed`
- `permission.updated` (optional for approvals)
- `todo.updated` (optional)
- `lsp.updated` (optional)

### Message and Part Types

Model parity with OpenCode should be preserved to minimize UI changes.

Message:

```json
{
  "id": "msg_123",
  "sessionID": "sess_123",
  "role": "assistant",
  "time": { "created": 1700000000, "completed": 1700000001 },
  "modelID": "claude-3-5",
  "providerID": "anthropic",
  "mode": "chat",
  "path": { "cwd": "/repo", "root": "/repo" },
  "summary": false,
  "tokens": { "input": 0, "output": 0, "reasoning": 0, "cache": { "read": 0, "write": 0 } },
  "cost": 0
}
```

Part (key variants):

- `text` (streamed by `delta`)
- `reasoning` (streamed by `delta` if enabled)
- `tool` (pending, running, completed, error)
- `step-start`, `step-finish`
- `patch` (diff summary + file list)

## Streaming Lifecycle (SSE)

1. Assistant message created -> `message.updated` (empty content, pending)
2. Part created -> `message.part.updated` without `delta`
3. Streaming token chunks -> repeated `message.part.updated` with `delta`
4. Part complete -> `message.part.updated` with full state (no delta)
5. Message complete -> `message.updated` with `time.completed`

This mirrors OpenCode's `Session.updatePart` behavior, keeping UI logic intact.

## SSE Endpoint Specification

### GET `/api/v1/events/sse`

- Content-Type: `text/event-stream`
- Emits `server.connected` immediately.
- Streams all EventBus events in OpenCode envelope format.
- Supports optional filters via query params: `session_id`, `agent_id`, `type`.

Example SSE data line:

```
data: {"type":"message.part.updated","properties":{"part":{...},"delta":"hello"}}

```

### Transition Plan

- SSE becomes the default for the new `penguin-tui`.
- WebSocket endpoints remain for existing clients.
- Future default for all clients once SSE is proven stable.

## TUI Control Endpoints

These mirror OpenCode's TUI control API and reduce client-side complexity.

- `POST /api/v1/tui/append-prompt` -> append text to prompt input
- `POST /api/v1/tui/execute-command` -> dispatch UI command
- `POST /api/v1/tui/show-toast` -> show toast notification

Optional (remote TUI control queue):

- `GET /api/v1/tui/control/next`
- `POST /api/v1/tui/control/response`

## `penguin-tui` Fork Strategy

### Source

Fork from:

- `reference/opencode/packages/opencode/src/cli/cmd/tui`

### Minimal Changes

- Replace SDK client and endpoint definitions.
- Keep providers, store, components, and themes.
- Maintain `Message` and `Part` types as-is.
- Replace OpenCode-specific routes with Penguin API endpoints.

### Adapter Layer

Use a thin adapter to map Penguin SSE payloads into OpenCode types when needed. Prefer server-side normalization so the TUI can remain unchanged.

## Licensing and Attribution

- OpenCode is MIT-licensed; reuse is allowed with attribution.
- `penguin-tui` must include the MIT license text and copyright notice.
- Any reused files should retain OpenCode copyright headers.

## Risks and Mitigations

- SSE backpressure: apply buffering and rate limits; coalesce deltas server-side.
- Event ordering: enforce per-session ordering in the stream.
- Data model drift: add compatibility tests to keep Penguin schema aligned.
- Dual stream complexity: keep WS and SSE behavior identical during transition.

## Implementation Phases

1. Add SSE endpoint and event envelope in FastAPI.
2. Emit OpenCode-compatible message/part events from core/engine.
3. Fork OpenCode TUI into `penguin-tui` with a new Penguin client.
4. Validate streaming behavior with text + reasoning only.
5. Port tool rendering, diffs, and prompt UX.
6. Extend dialogs, themes, session/agent lists for parity.

## Verification

- Stream sequencing tests for `message.part.updated` deltas.
- End-to-end SSE test: prompt -> token stream -> final message.
- Snapshot test for tool rendering and markdown/code display.
- UI performance checks with long streams and large tool outputs.
