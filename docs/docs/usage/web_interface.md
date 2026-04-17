# Web Interface / API Server Guide (v0.6.x)

Penguin ships with a **FastAPI-based HTTP server** that exposes chat, projects, tasks, SSE/WS streaming, uploads, and integration routes. That server is also the backend surface used by the OpenCode-derived terminal UI in `penguin-tui/`.

This page focuses on **how to run and expose the web server safely**.

---

## Starting the server

```bash
# Local development
penguin-web

# Explicit host/port
penguin-web --host 127.0.0.1 --port 9000

# Exposed host (requires auth unless explicitly overridden)
penguin-web --host 0.0.0.0 --port 9000
```

The command is a thin wrapper around `penguin.web.server:main`.

Optional flags:

| Flag | Description |
|------|-------------|
| `--debug` | Enable reload and verbose logging |
| `--workers N` | Run with a process pool |

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

### Example: authenticated HTTP request

```bash
curl http://127.0.0.1:9000/api/v1/capabilities \
  -H "X-API-Key: your-key"
```

### Example: unauthenticated request

```bash
curl http://127.0.0.1:9000/api/v1/capabilities
```

That now returns `401 Unauthorized`, not a misleading `500`.

### WebSocket auth

Protected WebSocket endpoints must authenticate during connection setup.

Important constraint: browser JavaScript cannot cleanly set arbitrary custom WebSocket headers in the same way as backend clients. That means browser-facing WS auth ergonomics are still a design concern for the future UI rewrite.

For now:
- backend clients should use headers
- browser-facing improvements likely need short-lived WS tickets or cookie/session auth later

---

## Startup Hardening

If you bind Penguin to a non-local interface such as `0.0.0.0` while auth is disabled, startup is blocked by default.

This prevents the easiest “accidentally exposed dev server on the internet” failure mode.

Override only if you really mean it:

```bash
PENGUIN_ALLOW_INSECURE_NO_AUTH=true penguin-web --host 0.0.0.0 --port 9000
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
penguin-web --host 127.0.0.1 --port 9000
```

Penguin still verifies the webhook HMAC signature and now also rejects replayed delivery IDs, but the route has to be reachable first.

---

## Recommended Deployment Profiles

### Local development

```bash
PENGUIN_AUTH_ENABLED=false
penguin-web --host 127.0.0.1 --port 9000
```

### Hardened exposed deployment

```bash
PENGUIN_AUTH_ENABLED=true
PENGUIN_API_KEYS=replace-me
PENGUIN_CORS_ORIGINS=https://penguin.example.com
penguin-web --host 0.0.0.0 --port 9000
```

### GitHub webhook with auth enabled

```bash
PENGUIN_AUTH_ENABLED=true
PENGUIN_API_KEYS=replace-me
PENGUIN_PUBLIC_ENDPOINTS=/api/v1/integrations/github/webhook
GITHUB_WEBHOOK_SECRET=replace-me
penguin-web --host 0.0.0.0 --port 9000
```

---

## Known Limitations

- The legacy dashboard/static UI is not the strategic frontend path and should not be treated as a polished product surface.
- WebSocket auth is correct, but browser-native auth ergonomics still need a better long-term design.
- GitHub webhook replay defense is process-local only; multi-instance deployments need shared replay state.
- Rate limiting and per-user/per-route quotas are still future work.

---

*Last updated: April 16, 2026*
