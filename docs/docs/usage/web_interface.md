# Web Interface / API Server Guide (v0.6.x)

Penguin ships with a **FastAPI-based HTTP server** that exposes core functionality (projects, tasks, chat, SSE/WS streaming) as a REST/WS API. That server is also the backend surface used by the OpenCode-derived terminal UI that now lives in the repository's `penguin-tui/` workspace.

---

## Installation
```bash
# Recommended: base install already includes the web runtime
uv tool install penguin-ai

# Alternative: plain pip
pip install penguin-ai

# Compatibility alias for older install docs
pip install "penguin-ai[web]"
```

## Starting the server
```bash
# Default → http://localhost:8000
penguin-web

# Custom host/port
penguin-web --host 0.0.0.0 --port 9000
```

The command is a thin wrapper around `penguin.web.server:main`, which serves the FastAPI app used by both API consumers and the modern TUI bridge.

Optional flags:
| Flag | Description |
|------|-------------|
| `--debug` | Enable reload & verbose logging |
| `--workers N` | Run with a process pool (production) |

---

## API Overview
The OpenAPI / Swagger UI is served at:
```
GET http://<host>:<port>/docs
```
Key route groups:
1. `/api/v1/projects` – CRUD for projects
2. `/api/v1/tasks` – CRUD & execution for tasks
3. `/api/v1/chat/message` – Chat endpoint (POST message, returns assistant reply)
4. `/api/v1/chat/stream` – WebSocket for streaming chat responses
5. `/api/v1/*` status/session endpoints for path, VCS, formatter, and LSP

### Task / Clarification Surface Truth

The task/project web surface is no longer just legacy CRUD sugar. Current behavior includes:
- richer task payloads that expose lifecycle truth such as `status`, `phase`, dependencies, dependency specs, artifact evidence, recipe references, and clarification metadata
- `POST /api/v1/tasks/{task_id}/execute` routing through `RunMode`, so non-terminal outcomes like `waiting_input` survive to clients
- `POST /api/v1/tasks/{task_id}/clarification/resume` to answer the latest open clarification and resume execution
- `GET /api/v1/events/sse` including clarification-related session status visibility for compatible clients

For full path details, inspect the live Swagger page or read `penguin/penguin/web/routes.py`.

> Example – list projects:
> ```bash
> curl http://localhost:8000/api/v1/projects
> ```

### Session + Directory Isolation

For OpenCode-compatible multi-session workflows, chat requests support:
- `session_id` and/or `conversation_id`
- `directory` (repo root for tool execution)

Behavior:
- The first valid directory bound to a session is immutable by default.
- Rebinding a session to a different directory returns `409`.
- Invalid directories return `400`.
- Request execution is context-scoped so parallel sessions can run safely across different repos.

---

## Authentication
Authentication is **not** yet implemented.  The server should only be exposed on trusted networks.

---

## Known Limitations
* No HTML UI – interaction is via REST/WS or the CLI.  
* Auth/RBAC, CORS, and HTTPS termination are future work.  
* API surface may change without notice until v1.0.

---

*Last updated: February 16th 2026* 
