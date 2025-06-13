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
1. `/projects` – CRUD for projects
2. `/tasks` – CRUD & execution for tasks
3. `/chat` – Chat endpoint (POST message, returns assistant reply)
4. `/ws/chat` – WebSocket for streaming chat responses

For full path details, inspect the live Swagger page or read `penguin/penguin/web/routes.py`.

> Example – list projects:
> ```bash
> curl http://localhost:8000/projects
> ```

---

## Authentication
Authentication is **not** yet implemented.  The server should only be exposed on trusted networks.

---

## Known Limitations
* No HTML UI – interaction is via REST/WS or the CLI.  
* Auth/RBAC, CORS, and HTTPS termination are future work.  
* API surface may change without notice until v1.0.

---

*Last updated: June 13th 2025* 