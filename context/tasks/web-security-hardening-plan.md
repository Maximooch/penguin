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

## Reference Comparison

### Codex precedent
- Codex avoids exposing a local network listener by default and prefers `stdio` transports for rich clients.
- When Codex exposes a websocket listener, loopback listeners are treated as the normal local path.
- Non-loopback listeners require explicit token-based auth configuration.
- For browser-driven OAuth callbacks, Codex binds to `127.0.0.1` by default and only broadens bind scope when explicitly configured.
- Longer-lived credentials are stored in secure OS-backed storage.

### OpenCode precedent
- OpenCode defaults to `127.0.0.1` and prefers a local dev port, with fallback if that port is unavailable.
- OpenCode permits a local/browser-accessible HTTP server as a first-class workflow.
- Server auth is optional and implemented with simple HTTP Basic Auth when `OPENCODE_SERVER_PASSWORD` is set.
- OpenCode warns loudly when the server is started without auth.
- CORS is restricted to local origins, Tauri origins, and an explicit allowlist.

## Penguin Recommendation Matrix

### Safe defaults
- Default bind host should remain loopback-only: `127.0.0.1`.
- Default port should move to `9000` to reduce generic-port collisions and match repo guidance.
- Penguin should never default to `0.0.0.0`.

### Auth model
- Penguin should not introduce local Penguin accounts.
- When auth is enabled, Penguin should issue a startup capability token and exchange it once at a local auth endpoint.
- The auth endpoint should set an `HttpOnly` session cookie for same-origin browser use.
- Header auth should remain supported for TUI, CLI, and external clients.

### Browser compatibility
- Cookie-backed sessions are the recommended browser path because cookies work across normal HTTP, SSE, and WebSocket flows.
- Do not reintroduce query-string auth for SSE or WebSocket compatibility.
- Avoid relying on custom request headers for browser `EventSource` or browser-created `WebSocket` auth.

### Broad bind policy
- Non-loopback binds should remain blocked unless auth is enabled or an explicit insecure override is set.
- Startup messaging should make the safe local path obvious and make insecure overrides feel deliberate.

### UX guidance
- If Penguin is started without auth, emit a clear warning that the local server is unsecured.
- If Penguin rejects an unauthorized browser/client request, return a short remediation message describing the safe auth flow and the explicit no-auth local-only override.
- Avoid repeated noisy auth failures in logs when a single warning plus 401/1008 response is sufficient.

## Recommended Follow-up Implementation
- Add startup-token generation when `PENGUIN_AUTH_ENABLED=true` and no explicit API keys are configured.
- Add `POST /api/v1/auth/session` to redeem the startup token or configured API key for a signed session cookie.
- Add `POST /api/v1/auth/logout` to clear the session cookie.
- Extend HTTP, SSE, and WebSocket auth checks to accept the signed session cookie.
- Add a small, explicit unauthorized warning path for browser/local clients instead of silent 401 loops.
- Update local verification and docs to prefer `http://127.0.0.1:9000`.

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

### P3: Local browser session auth
- Add startup capability-token generation when `PENGUIN_AUTH_ENABLED=true` and no configured API key is present.
- Print a one-time local authorization message describing how to redeem the startup token.
- Add `POST /api/v1/auth/session` to exchange a startup token or configured API key for a signed `HttpOnly` session cookie.
- Add `POST /api/v1/auth/logout` to clear the session cookie.
- Ensure session cookies are loopback-safe and use conservative defaults for expiry, `SameSite`, and path.

### P4: Cookie auth integration across transports
- Extend HTTP auth middleware to accept the signed session cookie alongside header auth.
- Extend SSE auth checks to accept the signed session cookie.
- Extend protected WebSocket auth guards to accept the signed session cookie during handshake.
- Add focused tests proving cookie-authenticated HTTP, SSE, and WebSocket flows succeed.
- Keep query-string auth disabled.

### P5: Defaults and startup UX
- Move the default web port to `9000`.
- Keep the default bind host at `127.0.0.1`.
- Update startup banners, server messages, and docs to consistently point users at `http://127.0.0.1:9000`.
- Add a clear warning when Penguin is intentionally started without auth.
- Add concise remediation text for unauthorized browser/local requests instead of repeated noisy log spam.

### P6: Browser-client polish
- Add a minimal unauthorized state for local browser clients that explains the instance is protected and how to authorize safely.
- Avoid building a Penguin account/login concept; keep the flow framed as local instance authorization.
- Ensure auth-enabled browser clients recover cleanly after successful session creation instead of looping on repeated 401s.
- Add regression coverage for the protected-browser happy path.

### P7: TUI, packaging, and architecture alignment
- Audit `penguin-tui` and launcher flows to ensure they can authenticate cleanly against an auth-enabled local `penguin-web` instance.
- Keep header-based auth support for TUI/CLI-sidecar flows even after browser cookie auth is added.
- Decide whether the TUI should redeem a startup token directly, reuse configured API keys, or delegate local authorization through the launcher.
- Update any TUI/server startup assumptions to prefer `http://127.0.0.1:9000`.
- Update `pyproject.toml` script/runtime expectations if default port, auth messaging, or launcher assumptions change.
- Update `architecture.md` so the documented TUI/web topology and local security model match runtime truth.

### P8: Documentation and operator guidance
- Update README and web/TUI docs to describe the secure local-default posture.
- Document the default host/port, the startup-token flow, and the explicit insecure override paths.
- Document how browser, TUI, CLI, and external clients authenticate against a protected local Penguin instance.
- Document the difference between local instance authorization and user-account authentication.
- Add operator guidance for non-loopback deployments, including the requirement for explicit auth.
- Ensure examples, troubleshooting steps, and startup output snippets consistently use `127.0.0.1:9000`.

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
This should likely be split into at least seven commits:
1. auth correctness + WS auth
2. startup/upload hardening
3. webhook replay defense + credential precedence/docs
4. startup token + session cookie auth
5. default port/startup UX/docs polish
6. TUI/launcher + packaging alignment
7. architecture/docs final pass
