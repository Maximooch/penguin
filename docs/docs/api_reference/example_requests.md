---
sidebar_position: 10
---

# Example API Requests

Basic `curl` commands for interacting with the API server.

## Send a Chat Message
```bash
curl -X POST http://127.0.0.1:9000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello", "session_id": "example-session", "directory": "/absolute/path/to/repo"}'
```

## Stream Chat Responses
```bash
# Requires websocat or similar tool
websocat ws://127.0.0.1:9000/api/v1/chat/stream
{"text": "Hello", "session_id": "example-stream", "directory": "/absolute/path/to/repo"}
```

## Execute a Task
```bash
curl -X POST http://127.0.0.1:9000/api/v1/tasks/execute \
  -H "Content-Type: application/json" \
  -d '{"name": "Build project", "description": "Set up repo"}'
```

## Get Session-Scoped Token Usage
```bash
curl "http://127.0.0.1:9000/api/v1/token-usage?session_id=example-session"

# Equivalent session route
curl "http://127.0.0.1:9000/api/v1/sessions/example-session/token-usage"
```

Only responses with `usage.scope == "session"` are safe for transcript-specific
context-window meters or context horizon UI. The unscoped endpoint returns
runtime/global telemetry with `usage.scope == "runtime"`.
