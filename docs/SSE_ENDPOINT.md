# SSE Endpoint Documentation

## Overview

The SSE (Server-Sent Events) endpoint at `/api/v1/events/sse` provides OpenCode-compatible message/part event streaming for the TUI implementation.

## Existing Streaming Infrastructure

### WebSocket Endpoints (routes.py)

| Endpoint | Purpose | Line |
|----------|---------|------|
| `/api/v1/events/ws` | General event streaming (bus.message, UI events) | 402 |
| `/api/v1/ws/messages` | Message-specific events | 496 |
| `/api/v1/ws/telemetry` | Telemetry data streaming | 609 |
| `/api/v1/chat/stream` | Chat streaming with token-by-token delivery | 1122 |

### MCP HTTP Server (integrations/mcp/http_server.py)

Uses `StreamingResponse` for tool output streaming (separate concern, not related to TUI).

## New SSE Endpoint

### Endpoint: `GET /api/v1/events/sse`

**Query Parameters:**
- `session_id` (optional): Filter events to specific session
- `agent_id` (optional): Filter events to specific agent
- `directory` (optional): Workspace directory for context

**Headers:**
- `Accept: text/event-stream`

**Response:**
```
data: {"type": "server.connected", "properties": {...}}

data: {"type": "message.updated", "properties": {"id": "msg_123", ...}}

data: {"type": "message.part.updated", "properties": {"part": {...}, "delta": "chunk"}}
```

### Differences from WebSocket

| Aspect | WebSocket | SSE |
|--------|-----------|-----|
| Direction | Bidirectional | Unidirectional (server → client) |
| Format | Binary JSON frames | Text `data: {...}\n\n` |
| Reconnection | Manual | Automatic (built-in) |
| HTTP Compatible | No (ws://) | Yes (http://) |
| Event Model | Penguin native | OpenCode-compatible |

### Event Types

**Message Events:**
- `message.updated` - Message metadata (created, completed, model, tokens)
- `message.part.updated` - Part content with delta streaming

**Connection Events:**
- `server.connected` - Initial connection handshake

**Part Types:**
- `text` - Assistant response text
- `reasoning` - Reasoning/thinking content
- `tool` - Tool execution with state (pending/running/completed/error)

## Architecture

```
┌─────────────────┐     stream_chunk      ┌──────────────────┐
│   PenguinCore   │ ─────────────────────→ │ PartEventAdapter │
│   (emit_ui_event)│                       └────────┬─────────┘
└─────────────────┘                                │
                                                   ↓ emit "opencode_event"
┌─────────────────┐                       ┌──────────────────┐
│   TUI Client    │ ←── SSE stream ────── │   EventBus       │
│ (EventSource)   │    text/event-stream  │                  │
└─────────────────┘                       └──────────────────┘
```

## Testing

### Manual Test with curl

```bash
# Start the server
python -m penguin.web.server  # or however server is started

# Connect to SSE endpoint
curl -N http://localhost:8000/api/v1/events/sse \
  -H "Accept: text/event-stream"

# With session filter
curl -N "http://localhost:8000/api/v1/events/sse?session_id=test-123" \
  -H "Accept: text/event-stream"
```

### Browser Test

```javascript
const evtSource = new EventSource("http://localhost:8000/api/v1/events/sse");

evtSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Event:", data.type, data.properties);
};

evtSource.onerror = (err) => {
  console.error("SSE error:", err);
};
```

## Integration Status

- ✅ Backend: `penguin/engine/part_events.py` - Message/Part dataclasses
- ✅ Adapter: `PartEventAdapter` in core streaming pipeline
- ✅ Endpoint: `penguin/web/sse_events.py` - SSE route
- ✅ Wiring: `app.py` includes router and sets core instance
- ⏳ Testing: Requires running server (blocked by startup dependencies)
- ⏳ TUI: Fork OpenCode TUI and replace SDK client

## Next Steps

1. **Server Startup Test**: Verify endpoint works with running server
2. **Tool Integration**: Map tool executions to `ToolPart` events
3. **Error Handling**: Test reconnection and error scenarios
4. **TUI Fork**: Copy OpenCode TUI and adapt SDK client