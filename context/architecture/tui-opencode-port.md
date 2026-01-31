# OpenCode TUI Port for Penguin

## Status

**Implementation Started (refactor-penguin-backend-tui branch)**

Phase 1: SSE Backend Infrastructure - In Progress

## Key Updates from Investigation

### What Was Learned (Jan 31, 2026)

**Critical Finding:** Previous attempt moved `penguin/engine.py` → `penguin/engine/core.py` which broke import chains. 

**Decision:** Keep `engine.py` and `core.py` at root level. Add new code in isolated packages.

### Current Web API Structure

Penguin already has robust WebSocket + REST support:
- **WebSocket:** `/api/v1/events/ws`, `/api/v1/ws/messages` - streaming events
- **REST:** `/api/v1/chat/message` - synchronous chat
- **Event Systems:** 
  - `UtilsEventBus` (bus.message)
  - `CLIEventBus` (UI events: message, stream_chunk, human_message, tool)

### SSE Architecture Decision

SSE will be a **first-class peer** to WebSocket, not a replacement:
- Same event coverage
- Same filtering capabilities (agent_id, session_id, type)
- HTTP-based (better for proxies, load balancers)
- One-way streaming (server → client)

## Revised Implementation Plan

### Phase 1: SSE Infrastructure (Current)

**New Files (isolated packages):**
- `penguin/tui_adapter/` - OpenCode-specific translation layer
  - `part_events.py` - Message/Part dataclasses + adapter
  - `__init__.py` - Package exports
- `penguin/web/sse_events.py` - SSE endpoint (new router)

**Minimal Changes to Core Files:**
- `penguin/core.py`: Add ~5 lines to emit formatted events via EventBus
- `penguin/web/app.py`: Register SSE router (1 line)
- `penguin/web/routes.py`: No changes (keep existing WS/REST)

### Phase 2: Event Translation Layer

**Challenge:** OpenCode expects `message.part.updated` with deltas; Penguin emits `stream_chunk` events.

**Solution:** Adapter pattern in `tui_adapter`:
- Subscribe to Penguin events
- Transform to OpenCode envelope format
- Emit as `opencode_event` on EventBus
- SSE endpoint filters and streams

### Phase 3: TUI Fork (Future)

Create `penguin-tui` package by forking OpenCode's TUI:
- Replace OpenCode SDK with Penguin API client
- Connect to `/api/v1/events/sse`
- Keep SolidJS UI components unchanged

## SSE Endpoint Specification

### GET `/api/v1/events/sse`

**Query Parameters:**
- `session_id` / `conversation_id` (alias) - filter to specific session
- `agent_id` - filter to specific agent  
- `directory` - workspace context

**Event Stream Format:**
```
data: {"type":"server.connected","properties":{"sessionID":"..."}}

data: {"type":"message.updated","properties":{"id":"msg_123",...}}

data: {"type":"message.part.updated","properties":{"part":{...},"delta":"token"}}
```

**Keepalive:** `: keepalive\n\n` every 300s (configurable)

## OpenCode Event Compatibility

### Required Events for TUI

| Event | Purpose |
|-------|---------|
| `server.connected` | Handshake |
| `message.updated` | Message metadata changes |
| `message.part.updated` | Streaming content (text/reasoning/tool) |
| `message.part.removed` | Undo/redo support |
| `session.updated` | Session list refresh |

### Event Envelope Format

```json
{
  "type": "message.part.updated",
  "properties": {
    "part": {
      "id": "part_123",
      "messageID": "msg_123", 
      "sessionID": "sess_123",
      "type": "text",
      "text": "accumulated content"
    },
    "delta": "new token chunk"
  }
}
```

## Part Types Supported

- `text` - Assistant response (streamed via delta)
- `reasoning` - Chain-of-thought (if enabled)
- `tool` - Tool execution (pending → running → completed/error)
- `step-start`, `step-finish` - Iteration markers
- `patch` - File changes

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| SSE backpressure | 1000-event queue with drop-on-full |
| Event ordering | Per-session sequencing in adapter |
| Dual maintenance (WS + SSE) | Both use same EventBus, different routers |
| Data model drift | Compatibility tests in CI |

## Licensing

OpenCode is MIT-licensed. `penguin-tui` will include:
- MIT license text
- Copyright notice for reused files
- Attribution in README

## Success Criteria

- [ ] SSE endpoint streams events without timeouts
- [ ] OpenCode TUI can connect and display streaming text
- [ ] Tool execution renders correctly
- [ ] Session/agent filtering works
- [ ] No regression to existing WS/REST endpoints

---

**Last Updated:** 2026-01-31  
**Branch:** refactor-penguin-backend-tui