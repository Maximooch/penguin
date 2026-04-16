# Web Docs vs Live Code Audit

**Date:** 2026-04-16
**Scope:** Compare `docs/docs/` against the live FastAPI surface in `penguin/web/`
**Status:** Completed

---

## Executive Summary

The docs are useful for orientation, but they are **not an authoritative map of the current web API**.

Measured against the route definitions in `penguin/web/routes.py`, `penguin/web/sse_events.py`, and `penguin/web/integrations/github_webhook.py`:

- **Live routes found:** 146
- **Distinct documented paths found:** 64
- **Exact documented live matches:** 59
- **Approximate route coverage:** **40.4%**

That number is conservative but still ugly enough to matter. Core chat/task flows are mostly represented; the broader web/API surface has significant drift.

---

## What Still Looks Accurate

The main chat/task docs are broadly aligned with the current implementation:

- `POST /api/v1/chat/message`
- `WebSocket /api/v1/chat/stream`
- `POST /api/v1/tasks/{task_id}/execute`
- `POST /api/v1/tasks/{task_id}/clarification/resume`
- `GET /api/v1/events/sse`

The docs also correctly describe the newer task payload direction: preserving richer lifecycle truth such as `phase`, clarification state, dependency metadata, and artifact evidence.

Relevant source anchors:

- `penguin/web/routes.py` — task payload serialization and task lifecycle endpoints
- `penguin/web/sse_events.py` — SSE endpoint and session/directory filtering
- `penguin/web/app.py` — app creation and router wiring

---

## Confirmed Drift / Stale Docs

### 1. Projects endpoint is outdated

Docs still describe:

- `POST /api/v1/projects/create`

Live code exposes:

- `POST /api/v1/projects`

This is a real mismatch, not a formatting nit.

### 2. GitHub webhook path is outdated

Docs still describe:

- `POST /api/v1/github/webhook`

Live code exposes:

- `POST /api/v1/integrations/github/webhook`

### 3. Agent session history route is documented but not live

Docs describe:

- `/api/v1/agents/{agent_id}/sessions/{session_id}/history`

Live code currently exposes:

- `/api/v1/agents/{agent_id}/history`
- `/api/v1/agents/{agent_id}/sessions`

That nested history route does **not** appear to exist in the live router.

### 4. Conversation history docs contain a wrong parameterized path form

A documented path form uses:

- `/api/v1/conversations/{agent_id}/history`

Live code exposes:

- `/api/v1/conversations/{conversation_id}/history`

Wrong placeholder names in API docs are how integrations get quietly broken. This one should be fixed.

### 5. App initialization docs are incomplete

The app setup docs do not fully reflect current `penguin/web/app.py` behavior.

Missing/incomplete items include:

- authentication middleware
- SSE router registration
- provider credential rehydration
- VCS watcher startup/shutdown hooks
- optional MCP HTTP router inclusion

So even the architectural overview is lagging the live app wiring.

---

## Major Live Surface Missing from Docs

Large chunks of the current web/API surface are live but absent or barely covered in `docs/docs/`.

Examples:

- session APIs: `/api/v1/session*`
- approval APIs: `/api/v1/approvals*`
- permission/question APIs
- provider auth/config endpoints
- memory APIs: `/api/v1/memory*`
- workflow APIs: `/api/v1/workflows*`
- orchestration APIs
- security config APIs
- some system/config/status endpoints
- utility/status endpoints such as formatter, LSP, VCS, path, find/file

This means anyone using docs as the source of truth will miss a lot of functionality.

---

## Coverage Snapshot

### Documented and live enough to trust

- chat endpoints
- core task execution endpoints
- SSE visibility for task/clarification flows
- parts of agents/messaging/checkpoints/models/system status

### Live but underdocumented or undocumented

- sessions
- approvals
- memory
- workflows
- orchestration
- security config
- provider auth/runtime config
- operational status utilities

### Documented but stale/wrong

- `/api/v1/projects/create`
- `/api/v1/github/webhook`
- `/api/v1/agents/{agent_id}/sessions/{session_id}/history`
- `/api/v1/conversations/{agent_id}/history`

---

## Recommended Fix Order

### Priority 1 — Fix false docs

These are the most dangerous because they actively mislead:

1. Replace `/api/v1/projects/create` with `/api/v1/projects`
2. Replace `/api/v1/github/webhook` with `/api/v1/integrations/github/webhook`
3. Remove or correct `/api/v1/agents/{agent_id}/sessions/{session_id}/history`
4. Fix `/api/v1/conversations/{agent_id}/history` to `/api/v1/conversations/{conversation_id}/history`

### Priority 2 — Update architecture docs

Bring `api_server.md` in sync with `penguin/web/app.py`:

- auth middleware
- SSE router registration
- provider credential hydration
- watcher lifecycle behavior
- optional MCP router behavior

### Priority 3 — Document the missing live surface

Start with the highest-leverage live APIs:

1. session endpoints
2. approvals/permission flow
3. provider auth/config endpoints
4. memory endpoints
5. workflows/orchestration endpoints

---

## Conclusion

Blunt version: the docs are **good enough for a guided tour, not good enough for contract-level trust**.

If the release depends on docs credibility, fix the stale paths first and then either:

- expand the docs to cover the real API surface, or
- explicitly label the docs as partial/high-level until they catch up.

Pretending these are complete would be fiction with markdown.

---

## Source Files Reviewed

- `docs/docs/api_reference/api_server.md`
- `docs/docs/api_reference/project_api.md`
- `docs/docs/api_reference/api_updates.md`
- `docs/docs/usage/web_interface.md`
- `docs/docs/usage/project_management.md`
- `penguin/web/app.py`
- `penguin/web/routes.py`
- `penguin/web/sse_events.py`
- `penguin/web/integrations/github_webhook.py`

---

## Method Note

This audit compared documented paths found under `docs/docs/**/*.md` against router declarations in the live code. Exact match counting underestimates semantic coverage slightly, but it is sufficient to identify real documentation drift and stale endpoint references.
