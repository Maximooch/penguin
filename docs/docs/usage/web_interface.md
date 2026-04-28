# Web Interface / API Server Guide (v0.6.x)

Penguin ships with a **FastAPI-based HTTP server** that exposes chat, projects, tasks, SSE/WS streaming, uploads, and integration routes. That server is also the backend surface used by the OpenCode-derived terminal UI in `penguin-tui/`.

This page focuses on **how to run and expose the web server safely**.

---

## Starting the server

```bash
# Local development
penguin-web

# Explicit host/port
HOST=127.0.0.1 PORT=9000 penguin-web

# Exposed host (requires auth unless explicitly overridden)
HOST=0.0.0.0 PORT=9000 penguin-web
```

The command is a thin wrapper around `penguin.web.server:main`. Host and port
selection is controlled by environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `127.0.0.1` | Bind address. Use `0.0.0.0` only for intentionally exposed deployments. |
| `PORT` | `9000` | HTTP port for API, local dashboard routes, and TUI backend traffic. |
| `DEBUG` | `false` | Enables development behavior such as reload where supported. |

Do not rely on `penguin-web --host ... --port ...` until that path is explicitly
verified. Use `HOST` and `PORT` instead.

After startup, the server prints:

- the local server URL
- API documentation URL at `/api/docs`
- local authorization guidance when auth is enabled

---

## Current Security Posture

The web server is no longer “wide open unless you remember to harden it later.” Current behavior:

- protected HTTP routes can require API-key or JWT auth
- protected WebSocket routes also require auth before `accept()`
- query-string API keys are not accepted
- CORS no longer defaults to `*`
- non-local bind without auth is blocked at startup unless explicitly overridden
- upload handling is restricted to image MIME types/extensions
- GitHub webhook replay defense rejects duplicate `X-GitHub-Delivery` IDs within a process-local TTL window

### Public routes

Some routes remain public by design, including:

- `/`
- `/api/docs`
- `/api/redoc`
- `/api/openapi.json`
- `/api/v1/health`
- `/static/...`

Additional public routes can be exposed explicitly with `PENGUIN_PUBLIC_ENDPOINTS`.

---

## Authentication

Authentication is controlled by `PENGUIN_AUTH_ENABLED`.

When enabled, protected routes accept:

- `X-API-Key: <key>`
- `X-Link-API-Key: <key>`
- `Authorization: Bearer <jwt>`

Local browser sessions can also be authorized by opening the startup
`/authorize#local_token=...` URL printed by `penguin-web`. The TUI/CLI local
session path authenticates automatically. For CI, scripts, and headless clients,
prefer `PENGUIN_API_KEYS` plus the `X-API-Key` header.

### Example: authenticated HTTP request

```bash
curl http://127.0.0.1:9000/api/v1/capabilities \
  -H "X-API-Key: your-key"
```

### Example: explicitly unauthenticated local-only request

If you intentionally run local-only without auth:

```bash
PENGUIN_AUTH_ENABLED=false HOST=127.0.0.1 PORT=9000 penguin-web
curl http://127.0.0.1:9000/api/v1/capabilities
```

### RunMode / Task Execution Truth

RunMode-backed execution semantics are richer than a simple success/fail response. Current shared truth includes:
- clarification/waiting-input outcomes are non-terminal
- explicit runmode time limits are a separate concept from blueprint/task/project timing fields
- project-scoped autonomous execution may stop honestly when no ready work remains

This page is not yet the full home for RunMode contract details, but it should not imply simpler behavior than the runtime actually has.

### Task / Clarification Surface Truth

Important constraint: browser JavaScript cannot cleanly set arbitrary custom WebSocket headers in the same way as backend clients. That means browser-facing WS auth ergonomics are still a design concern for the future UI rewrite.

For now:
- backend clients should use headers
- browser-facing improvements likely need short-lived WS tickets or cookie/session auth later

### Tool Execution Surface Truth

Tool use is model-driven through the normal chat endpoints. Clients do not call
`read_file`, `list_files`, `execute_command`, or similar tools directly through
the web server; they send a chat request, and the runtime executes any approved
tool calls as part of the reasoning loop.

Current behavior:
- native provider tool calls are preferred for providers that support them
- ActionXML remains a fallback compatibility path, not the primary contract
- tool calls execute inside the session-bound `directory`
- tool results are returned in `action_results` and also emitted as live
  message/tool-part events for TUI, SSE, and WebSocket clients
- tools that require approval pause until the approval flow resolves
- if native provider tools already executed an intent, the runtime does not
  re-parse the assistant text for duplicate ActionXML execution

---

## Startup Hardening

If you bind Penguin to a non-local interface such as `0.0.0.0` while auth is disabled, startup is blocked by default.

This prevents the easiest “accidentally exposed dev server on the internet” failure mode.

Override only if you really mean it:

```bash
PENGUIN_AUTH_ENABLED=false \
PENGUIN_ALLOW_INSECURE_NO_AUTH=true \
HOST=0.0.0.0 \
PORT=9000 \
penguin-web
```

That override exists for edge cases, not because it is a good idea.

---

## CORS Behavior

If `PENGUIN_CORS_ORIGINS` is unset, Penguin now defaults to a small development allowlist instead of wildcard origins.

Default dev origins:

- `http://localhost:8000`
- `http://127.0.0.1:8000`
- `http://localhost:9000`
- `http://127.0.0.1:9000`

Set an explicit allowlist for real deployments:

```bash
PENGUIN_CORS_ORIGINS=https://penguin.example.com,https://admin.example.com
```

---

## Upload Behavior

`POST /api/v1/upload` is currently intended for image-style uploads.

Current behavior:
- image MIME types/extensions only
- empty uploads rejected
- size limit enforced server-side
- max size controlled by `PENGUIN_MAX_UPLOAD_BYTES`

Example:

```bash
curl -X POST http://127.0.0.1:9000/api/v1/upload \
  -H "X-API-Key: your-key" \
  -F "file=@screenshot.png;type=image/png"
```

If you need generic large-object upload semantics later, that should be designed explicitly instead of pretending this endpoint is already that.

---

## GitHub Webhooks Under Auth

GitHub does not send Penguin API keys.

So if global Penguin auth is enabled, the webhook route must either:

1. be explicitly exposed as public, or
2. sit behind a relay/gateway that handles the trust boundary

Example:

```bash
PENGUIN_AUTH_ENABLED=true \
PENGUIN_PUBLIC_ENDPOINTS=/api/v1/integrations/github/webhook \
HOST=127.0.0.1 \
PORT=9000 \
penguin-web
```

Penguin still verifies the webhook HMAC signature and now also rejects replayed delivery IDs, but the route has to be reachable first.

---

## Recommended Deployment Profiles

### Local development

```bash
PENGUIN_AUTH_ENABLED=true
HOST=127.0.0.1
PORT=9000
penguin-web
```

Open the printed `/authorize#local_token=...` URL once for browser/dashboard
usage. TUI/CLI local sessions authenticate automatically.

### Local development without auth

```bash
PENGUIN_AUTH_ENABLED=false
HOST=127.0.0.1
PORT=9000
penguin-web
```

### Hardened exposed deployment

```bash
PENGUIN_AUTH_ENABLED=true
PENGUIN_API_KEYS=replace-me
PENGUIN_CORS_ORIGINS=https://penguin.example.com
HOST=0.0.0.0
PORT=9000
penguin-web
```

### GitHub webhook with auth enabled

```bash
PENGUIN_AUTH_ENABLED=true
PENGUIN_API_KEYS=replace-me
PENGUIN_PUBLIC_ENDPOINTS=/api/v1/integrations/github/webhook
GITHUB_WEBHOOK_SECRET=replace-me
HOST=0.0.0.0
PORT=9000
penguin-web
```

### TUI against a running development server

```bash
HOST=127.0.0.1 PORT=8080 uv run penguin-web
uv run penguin --url http://127.0.0.1:8080 --no-web-autostart
```

Use a non-reserved alternate port such as `8080` or `9010` when another Penguin
backend is already using the default `9000` port.

---

## Known Limitations

- The legacy dashboard/static UI is not the strategic frontend path and should not be treated as a polished product surface.
- WebSocket auth is correct, but browser-native auth ergonomics still need a better long-term design.
- GitHub webhook replay defense is process-local only; multi-instance deployments need shared replay state.
- Rate limiting and per-user/per-route quotas are still future work.

---

*Last updated: April 27, 2026*
