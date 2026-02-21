# OpenCode TUI Port for Penguin

## Status

**Implementation In Progress (refactor-penguin-backend-tui branch)**

- SSE compatibility and OpenCode event translation are operational.
- Multi-session directory binding and request-scoped execution context are in place.
- Stream-state routing now uses request scope (`session_id:agent_id`) in core streaming paths.
- Engine initialization fallback bug was fixed (Engine now initializes in web mode, no silent legacy fallback).
- Stream chunk/finalize now propagate explicit session hints, reducing cross-session finalize collisions.
- Tool/stream session status lifecycle now balances `busy`/`idle` in the adapter path to prevent stuck-after-first-message flows.
- Production-safe concurrent session behavior is still in hardening/audit, but latest two-session manual runs are now mostly stable.

## Objective

Make concurrent OpenCode web sessions production-safe for same-agent (`default`)
multi-turn usage across different repos, without queued/stuck UI states.

## Latest Validation (2026-02-21)

- Manual two-session runs (Cadence + Tuxford) on one `penguin-web` process now complete multi-turn chat in parallel with correct directory/session wiring.
- Prior cross-session content bleed was reduced after explicit `session_id`/`conversation_id` propagation through streaming chunk + finalize paths.
- Remaining gate is sustained stress confidence (longer parallel prompt runs) before declaring production-safe.
- Phase C parity wiring landed for config/provider/auth endpoints and alias routes; Penguin-mode TUI bootstrap now fetches backend config/provider/auth payloads first (with fallback), and new route/service tests are in place.
- Provider/config/auth backend was refactored toward Penguin-first services (`provider_catalog`, `provider_credentials`, `provider_auth`) with OpenCode-specific mapping isolated to compatibility adapters.

## Root Cause Hypothesis

Streaming lifecycle was historically scoped by `agent_id` (often `"default"`)
instead of `session_id`, which caused concurrent sessions to collide in shared
stream state.

## Additional Audit Finding (Single-Session Stuck)

Even with one session, UI can remain non-idle due to `session.status` lifecycle
imbalance:

- `PartEventAdapter.on_stream_start()` emits `session.status=busy`.
- `on_stream_end()` emits `session.status=idle`.
- Tool fallback path can trigger `on_stream_start()` from `on_tool_start()` when no
  active message exists, but tool completion path does not guarantee a matching
  stream-end/idle transition.
- Result: prompt can stay in spinner/interrupt mode after first response.

### Key Touchpoints for This Finding

- `penguin/tui_adapter/part_events.py:209` (`_emit_session_status`)
- `penguin/tui_adapter/part_events.py:269` (`on_stream_start`, busy)
- `penguin/tui_adapter/part_events.py:330` (`on_stream_end`, idle)
- `penguin/tui_adapter/part_events.py:352` (`on_tool_start` fallback stream start)
- `penguin/core.py:3788` (`_on_tui_action`)
- `penguin/core.py:3831` (`_on_tui_action_result`)
- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx:69`

---

## Execution Plan

### Phase 0: Freeze + Baseline Audit (no behavior changes)

**Touchpoints**
- `penguin/core.py:3021` (`_handle_stream_chunk`)
- `penguin/core.py:3097` (`finalize_streaming_message`)
- `penguin/llm/stream_handler.py:423` (`AgentStreamingStateManager`)

**Work**
- Add temporary debug logging (session, conversation, agent, stream_id, scope key)
  at stream handle/finalize boundaries.
- Capture one failing two-session run trace (2 turns each).

**Exit criteria**
- Show at least one collision where two sessions share same stream manager key
  (`default`).

### Phase 1: Introduce deterministic stream scope key

**Touchpoints**
- `penguin/core.py`
  - `_handle_stream_chunk` (`3021`)
  - `finalize_streaming_message` (`3097`)
  - add helper: `_resolve_stream_scope_id(execution_context, agent_id) -> str`
- `penguin/llm/stream_handler.py`
  - `AgentStreamingStateManager.handle_chunk` (`472`)
  - `AgentStreamingStateManager.finalize` (`499`)

**Work**
- Compute `scope_id = "{session_id or conversation_id}:{agent_id or default}"`.
- Pass `scope_id` to stream manager methods (using existing `agent_id` slot or a
  renamed param if refactored).
- Ensure stream events include:
  - logical `agent_id` (for UI labeling),
  - internal `scope_id` only for state routing (not required in external payload).

**Exit criteria**
- Concurrent sessions no longer share a stream state bucket.

### Phase 2: Remove ambiguous finalize paths

**Touchpoints**
- `penguin/engine.py`
  - `_iteration_loop` (`790`, finalize call at `858`)
  - `_finalize_streaming_response` (`2004`, finalize call at `2054`)

**Work**
- Ensure finalize calls always pass explicit scope inputs (agent/session) and run
  exactly once per iteration.
- Avoid double-finalize races between `_llm_step` and outer loop.

**Progress (2026-02-19)**
- Engine finalize paths now pass explicit `agent_id` + current session-derived scope hints.
- Core finalize path now accepts explicit `session_id`/`conversation_id`/`stream_scope_id` and resolves deterministic scope keys.

**Exit criteria**
- Every streaming iteration produces exactly one finalization path with consistent
  scope.

### Phase 3: Conversation manager scoping hardening (default-agent path)

**Touchpoints**
- `penguin/engine.py`
  - `get_conversation_manager` (`471`)
  - `_resolve_components` (`672`)
- `penguin/core.py`
  - `process` (`2188`)

**Work**
- Ensure request path gets a scoped conversation handle even when `agent_id` is
  omitted.
- Remove reliance on shared mutable default conversation pointer in concurrent web
  requests.

**Exit criteria**
- Two requests with no explicit `agent_id` do not share mutable
  conversation/session pointers.

### Phase 4: Event completion ordering guarantees

**Touchpoints**
- `penguin/core.py`
  - `finalize_streaming_message` (`3097`) currently fire-and-forget emits via
    `asyncio.create_task`
  - `emit_ui_event` (`2894`)

**Work**
- For critical final stream completion events, use awaited emission in request path
  (or explicit flush barrier) before returning HTTP response.
- Keep non-critical events async if needed.

**Exit criteria**
- TUI never remains in `QUEUED` due to missing assistant completion event.

**Progress (2026-02-19)**
- Latest manual runs no longer reproduce the original first-message stuck behavior.
- Continue auditing for rare queued states under heavier concurrent traffic.

### Phase 5: TUI adapter consistency cleanup

**Touchpoints**
- `penguin/core.py`
  - `_get_tui_adapter` (`3494`)
  - `_on_tui_stream_chunk` (`3515`)
  - `_on_tui_action` (`3788`)
  - `_on_tui_action_result` (`3831`)
- `penguin/tui_adapter/part_events.py`

**Work**
- Keep session-scoped adapters, ensure tool-part keys remain session namespaced.
- Add adapter cleanup policy (on stream end/session idle) to prevent unbounded map
  growth.
- Ensure tool-only lifecycles cannot leave `session.status` in `busy`.

**Exit criteria**
- No cross-session adapter state bleed, no adapter map leak growth in long runs,
  and no stuck-busy single-session path.

### Phase 6: Documentation + formal audit artifact

**Touchpoints**
- `context/architecture/tui-opencode-implementation.md`
- `docs/docs/api_reference/api_server.md`
- `docs/docs/usage/api_usage.md`

**Work**
- Add "Concurrency Isolation Audit" results with checklist pass/fail per subsystem.
- Document final invariants:
  - stream scope key,
  - immutable session-directory binding,
  - completion event ordering guarantees,
  - busy/idle lifecycle guarantee for stream + tool paths.

**Exit criteria**
- Audit section explicitly marks production-safe criteria and evidence.

---

## Test Matrix (in order of execution)

1. **Unit: Stream scope isolation**
   - New: `tests/llm/test_stream_scope_isolation.py`
   - Cases:
     - two scope IDs (`s1:default`, `s2:default`) interleaved chunks
     - finalize one scope does not affect other
     - each scope emits its own `is_final` sequence

2. **Unit: Core stream routing**
   - New: `tests/test_core_stream_scope.py`
   - Cases:
     - `_handle_stream_chunk` routes by session scope from `ExecutionContext`
     - `finalize_streaming_message` finalizes correct scope

3. **API: Parallel multi-turn chat (critical)**
   - Extend: `tests/api/test_concurrent_session_isolation.py`
   - Cases:
     - same `agent_id` omitted (`default`), two sessions, two turns each, parallel
     - both sessions receive assistant completion (`time.completed`) each turn
     - no cross-session message/part IDs

4. **API: SSE filtering correctness**
   - Extend: `tests/api/test_sse_and_status_scoping.py`
   - Cases:
     - mixed interleaved events from two sessions, subscriber receives only matching
       session
     - final completion event arrives for each posted message

5. **Regression: Binding + context propagation**
   - Keep:
     - `tests/api/test_session_directory_binding.py`
     - `tests/test_execution_context.py`

6. **Smoke**
   - Keep:
     - `tests/test_multi_agent_smoke.py::test_core_process_routes_agent_context`

7. **Manual E2E (required gate)**
   - Two TUI windows, Cadence + Tuxford, same model, 5 back-to-back prompts each.
   - Pass criteria:
     - no lingering `QUEUED`,
     - both panes receive every assistant response,
     - no `409`s,
     - no cross-repo tool effects.

8. **Manual single-session regression gate**
   - One TUI session, 5 back-to-back prompts with tool usage.
   - Pass criteria:
     - prompt returns to idle between turns,
     - no permanent spinner/interrupt state,
     - balanced `session.status` transitions (`busy` -> `idle`) each turn.

---

## Magic Number Audit Snapshot

No known one-message cap found. Relevant constants to revisit/configure:

- `max_iterations` default `100` (`penguin/web/routes.py`)
- SSE queue size `1000` (`penguin/web/sse_events.py`)
- SSE keepalive timeout `300.0s` (`penguin/web/sse_events.py`)
- stream coalescing (`0.04s`, `12 chars`) (`penguin/llm/stream_handler.py`)
- prompt interrupt threshold (`>=2` within `5000ms`) 
  (`penguin-tui/.../prompt/index.tsx`)

---

## Success Criteria

- [x] SSE endpoint streams events without timeouts
- [x] OpenCode TUI can connect and display streaming text
- [x] Tool execution renders correctly with balanced busy/idle in current adapter path
- [~] Session/agent filtering works (hardening landed; sustained stress validation pending)
- [x] No regression to existing WS/REST endpoints

---

**Last Updated:** 2026-02-19
**Branch:** refactor-penguin-backend-tui
