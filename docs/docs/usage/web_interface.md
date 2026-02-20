# Web Interface / API Server Guide (v0.1.x)

Penguin currently includes a **FastAPI-based HTTP server** that exposes core functionality (projects, tasks, chat) as a REST/WS API.  A rich graphical UI is planned (see [future considerations](../advanced/future_considerations.md)), but not available yet.

---

## Installation
```bash
# Install Penguin with web extras
pip install "penguin-ai[web]"
```

## Starting the server
```bash
# Default → http://localhost:8000
penguin-web

# Custom host/port
penguin-web --host 0.0.0.0 --port 9000
```

The command is a thin wrapper around `penguin.web.app:app` (FastAPI) using `uvicorn`.

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
