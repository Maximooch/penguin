# Web Security Hardening Plan

Date: 2026-04-16
Branch: `fix/web-security-hardening`
Worktree: `../penguin-web-security-hardening`

## Objective
Close the highest-risk web security gaps in Penguin's HTTP and WebSocket surface with minimal, test-backed changes.

## Scope
- `penguin/web/middleware/auth.py`
- `penguin/web/routes.py`
- `penguin/web/server.py`
- `tests/` additions and updates for auth + WebSocket behavior

## Findings Confirmed
1. Public endpoint matching bug can bypass auth because `/` is treated as a prefix.
2. WebSocket endpoints do not enforce auth before `accept()`.
3. API key auth currently accepts `api_key` via query string.
4. Server startup posture is permissive by default when bound broadly.
5. Upload endpoint lacks size/type/quota controls.

## Execution Plan

### P0: Authentication correctness
- Fix public endpoint matching so `/` is exact-match only.
- Support explicit prefix-only public paths such as `/static/`.
- Remove query-parameter API key authentication.
- Add focused unit tests for:
  - `/` exact match
  - `/api/v1/capabilities` not public when auth enabled
  - header auth succeeds
  - query-param auth rejected

### P0: WebSocket authentication
- Add a shared WebSocket auth guard reusable across all protected WS handlers.
- Enforce auth before `websocket.accept()` for:
  - `/api/v1/events/ws`
  - `/api/v1/ws/messages`
  - `/api/v1/ws/telemetry`
  - `/api/v1/chat/stream`
  - `/api/v1/tasks/stream`
- Add tests proving unauthorized WS handshakes are rejected and authorized handshakes succeed.

### P1: Startup hardening
- Add a startup/deployment guard for insecure broad binds without auth.
- Keep localhost/dev workflow working.
- Add tests for broad-bind + auth-disabled rejection behavior.

### P1: Upload hardening
- Add file size limits.
- Add allowlist for file types/extensions if the endpoint is image-focused.
- Return clear 4xx responses for rejected uploads.
- Add tests for oversized and disallowed uploads.

### P2: Follow-up items
- Replay defense for GitHub webhook deliveries using a process-local TTL cache.
- Document the replay-cache limitation for multi-instance deployments.
- Prefer operator-managed environment variables for provider credentials.
- Keep legacy plaintext JSON only as a compatibility fallback with loud warnings.
- Document credential precedence and deprecate plaintext persistence as the primary path.

## Verification
- Use the dedicated worktree only.
- Prefer local web verification on port `9000` per `AGENTS.md`.
- Run targeted pytest coverage first.
- Run live server checks against `http://127.0.0.1:9000`.

## Acceptance Criteria
- Auth-enabled HTTP protected endpoints require valid header auth.
- Query-string API key auth no longer works.
- Protected WebSocket endpoints reject unauthenticated connections before accept.
- Local verification on port `9000` passes targeted checks.
- No unrelated behavior churn.

## Notes
This should likely be split into at least three commits:
1. auth correctness + WS auth
2. startup/upload hardening
3. webhook replay defense + credential precedence/docs
