# Core TUI Bridge Extraction TODO

## Objective

- Reduce `penguin/core.py` from its current ~5,842 LOC toward a healthier orchestration-only range (roughly 2,500-3,500 LOC).
- Move OpenCode/Penguin TUI compatibility responsibilities out of `core.py` into narrower modules with clearer ownership.
- Keep `PenguinCore` focused on runtime coordination, not TUI event translation, transcript persistence details, or session-status bookkeeping.

## Why This Exists

- `penguin/core.py` is currently 5,842 lines.
- `penguin/web/routes.py` is also oversized at 6,986 lines.
- Track J in `context/tasks/tui-opencode-implementation.md` already calls out the cleanup work, but the extraction deserves its own task file because it is now large enough to be a refactor stream, not a footnote.
- The older `context/archive/plans/core-refactor-plan.md` is useful rationale, but its line counts and target structure are stale relative to the current codebase.

## Boundary Decision

- Not everything should move to `penguin/web/services/`.
- Web request/response shaping, session view helpers, and OpenCode-compatible endpoint services belong in `penguin/web/services/`.
- TUI/OpenCode event translation, tool-part mapping, transcript persistence, and session-runtime UI bookkeeping belong closer to `penguin/tui_adapter/` (or similarly scoped runtime bridge modules), not inside generic web services.
- `core.py` should orchestrate these collaborators, not implement them inline.

## Audit Evidence

- `penguin/core.py`
- `penguin/web/routes.py`
- `penguin/web/services/`
- `penguin/tui_adapter/`
- `context/tasks/tui-opencode-implementation.md` (Track J)
- `context/archive/plans/core-refactor-plan.md`

## Current Size Snapshot

- `penguin/core.py` -> 5,842 LOC
- `penguin/web/routes.py` -> 6,986 LOC
- existing `penguin/web/services/*.py` already prove the service-extraction pattern works, but coverage is still uneven

## Progress Snapshot

- [ ] Capture the exact TUI/OpenCode responsibilities still living in `core.py`
- [ ] Define target ownership for each responsibility (`core.py` vs `web/services` vs `tui_adapter`)
- [ ] Extract event subscription/handler wiring from `core.py`
- [ ] Extract action-to-tool mapping and result metadata shaping from `core.py`
- [ ] Extract transcript persistence/session lookup helpers from `core.py`
- [ ] Extract session runtime bookkeeping (`abort`, active request counts, `session.status`) from `core.py`
- [ ] Reduce `core.py` to a thinner orchestration layer without breaking OpenCode parity

## Scope

### In Scope
- OpenCode/TUI event subscription and handler wiring
- action-to-tool mapping helpers
- tool result metadata shaping for TUI/OpenCode parts
- transcript persistence helpers
- session runtime bookkeeping used primarily for TUI/OpenCode session lifecycle
- moving route-adjacent business logic into `penguin/web/services/` where it is truly service logic

### Out of Scope
- rewriting core runtime semantics just because the file is large
- moving generic runtime logic into `web/services/` if it is not web-specific
- changing user-facing API contracts unless needed for cleanup safety

## Proposed Ownership Split

### `penguin/core.py`
- request/task orchestration
- engine coordination
- top-level runtime wiring
- dependency injection of helper modules
- high-level session/process lifecycle

### `penguin/tui_adapter/` (or equivalent bridge modules)
- OpenCode/TUI event subscription + translation
- part-event mapping
- action-to-tool mapping
- transcript persistence for OpenCode-shaped replay
- TUI/session UI bookkeeping that is not generic runtime logic

### `penguin/web/services/`
- route-adjacent business logic
- OpenCode-compatible session/config/provider/service adapters
- reusable request-scoped service helpers shared by routes

## Checklist

### Phase 1 - Inventory and Ownership Map
- [ ] Enumerate every TUI/OpenCode-specific method/block in `penguin/core.py`
- [ ] Label each block as `core`, `tui_adapter`, or `web/services`
- [ ] Confirm which parts are still coupled to request/session scope and why
- [ ] Update the Track J checklist in `context/tasks/tui-opencode-implementation.md` to point at this task where appropriate

### Phase 2 - Low-Risk Extractions First
- [ ] Extract OpenCode/TUI event subscription + handlers into a dedicated bridge module
- [ ] Extract action-to-tool mapping and result metadata shaping into a dedicated mapping module
- [ ] Extract transcript persistence/session store lookup helpers into a dedicated persistence module
- [ ] Keep behavior byte-for-byte equivalent where possible

### Phase 3 - Session Runtime Cleanup
- [ ] Extract session runtime bookkeeping helpers (`abort`, active request counters, `session.status` emission)
- [ ] Ensure request-scoped/session-scoped invariants remain intact
- [ ] Remove duplicate state paths once parity is proven

### Phase 4 - Route/Service Realignment
- [ ] Move genuinely web-specific compatibility/service logic out of `core.py` and thin route handlers further
- [ ] Do **not** dump non-web runtime logic into `web/services/` just to make `core.py` smaller
- [ ] Add internal docs for the new ownership boundaries

### Phase 5 - Hardening and Exit Criteria
- [ ] Confirm OpenCode/TUI parity regressions stay green
- [ ] Confirm concurrent session isolation behavior stays green
- [ ] Confirm `core.py` lands in the target range or document why not
- [ ] Remove stale comments/TODOs that describe the old inline structure

## Verification Targets

- `tests/test_core_tool_mapping.py`
- `tests/test_action_executor_subagent_events.py`
- `tests/test_core_opencode_stream_fallback.py`
- `tests/api/test_concurrent_session_isolation.py`
- `tests/api/test_sse_and_status_scoping.py`
- `tests/api/test_session_view_service.py`
- `tests/api/test_opencode_session_routes.py`
- focused OpenCode/TUI parity regressions tied to Track J

## Notes

- Shrinking `core.py` is not the real goal. Better ownership is.
- If a proposed extraction makes ownership murkier, it is fake progress.
- The likely win is not “move everything to web services.” The likely win is “put each responsibility where it naturally belongs and stop making `core.py` be the junk drawer.”
