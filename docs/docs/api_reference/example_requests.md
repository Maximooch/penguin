---
sidebar_position: 10
---

# Example API Requests

Basic `curl` commands for interacting with the API server.

## Send a Chat Message
```bash
curl -X POST http://localhost:8000/api/v1/chat/message \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello"}'
```

## Stream Chat Responses
```bash
# Requires websocat or similar tool
websocat ws://localhost:8000/api/v1/chat/stream
{"text": "Hello"}
```

## Execute a Task
```bash
curl -X POST http://localhost:8000/api/v1/tasks/execute \
  -H "Content-Type: application/json" \
  -d '{"name": "Build project", "description": "Set up repo"}'
```
