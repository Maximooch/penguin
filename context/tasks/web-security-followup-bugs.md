# Web Security Follow-Up Bugs

Date: 2026-04-18
Branch: `refactor-web-security-overhaul`

## Verified Bugs

### High risk
- Startup-token auth is not scoped tightly enough to loopback peers in `penguin/web/middleware/auth.py`.
- Auth-failure suppression uses an unbounded in-memory set keyed by raw paths in `penguin/web/middleware/auth.py`.
- `PORT` parsing in `penguin/web/server.py` can fail with an uncontrolled `ValueError` on malformed input.
- Local auth token cache writes in `penguin/web/server.py` can abort startup if the filesystem write fails.

### Medium risk
- `task.phase` serialization in `penguin/web/routes.py` can raise `AttributeError` for tasks without a `phase` attribute.
- The browser auth bootstrap fragment in `penguin/web/static/authorize.html` is only cleared after a successful auth POST.
- Dashboard websocket reconnect timers in `penguin/web/static/dashboard.html` are not cleaned up on unmount.
- Chat websocket auth-close handling in `penguin/web/static/index.html` can leave pending send state hanging.
- TUI prompt send path in `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx` only clears pending state on network exceptions, not non-2xx responses.
- TUI bootstrap fetches in `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx` still swallow non-OK protected bootstrap responses.
- Test fixtures in `tests/api/test_web_auth_hardening.py` mutate singleton-ish state without restoring it.

### Low risk / consistency
- Legacy `8000` values remain in `penguin/run_web.py` and `tests/run_server.py`.

## Non-Bug Cleanup Items
- `collections.abc.Mapping` / `contextlib.suppress` cleanup in `penguin/local_auth.py`.
- Missing return annotations in `penguin/web/app.py` and `penguin/web/__init__.py`.
- `api_auth_session` service extraction in `penguin/web/routes.py`.
- Task serializer protocol typing in `penguin/web/routes.py`.
- Package/static asset relocation discussion for `dashboard.html`.

## Current Focus
1. Loopback-only startup-token acceptance.
2. Bounded auth-failure cache.
3. Safe startup parsing and cache-write failure handling.
