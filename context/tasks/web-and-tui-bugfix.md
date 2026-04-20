# Web And TUI Bugfix Plan

## Goal

Capture the current web-auth, TUI, and OpenAI/Codex regression cluster in one
durable task note so the fixes survive compaction and can be implemented in a
deliberate order without losing cross-cutting context.

## Background

- Recent web security work landed in PR `#43` and PR `#44`.
- PR `#44` enabled local web auth by default and rewired the Penguin TUI to use
  authenticated local requests.
- Follow-up commit `758fd65d0439bbca046f26bcfa26b459f6c0bb9d` added TODOs in the
  TUI prompt and sync code instead of fully resolving the remaining reliability
  issues.
- The current regressions span both the Python backend and the `penguin-tui`
  sidecar, so they should be treated as one shared bugfix track rather than as
  isolated point fixes.

## Problems To Resolve

### 1. Web security hardening regressed Penguin TUI startup and send flows

- The TUI bootstrap path now hard-fails on non-2xx bootstrap responses instead
  of degrading where possible.
- The TUI prompt send path can leave the session visually stuck as busy when the
  request fails after local optimistic events have already been emitted.
- This aligns with the TODOs in:
  - `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
    - lines around `888-902`
  - `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
    - lines around `776-777`

### 2. OpenAI/Codex empty-response handling is incomplete for repeated tool-only loops

- The backend has empty-response handling and stream finalization placeholders.
- However, OpenAI/Codex Responses-style tool-only turns can still loop for many
  iterations with empty assistant text before eventually persisting
  `[Empty response from model]`.
- OpenRouter is less affected because its adapter usually returns an explicit
  non-empty diagnostic or placeholder when content is empty.

### 3. TUI message ordering can still become visually wrong

- A newer assistant message can appear above the user message that triggered it.
- The likely culprit is the live TUI ordering logic re-sorting messages by
  `time.created` instead of respecting transcript order once the backend has
  persisted the canonical order.
- This is especially fragile when optimistic local messages, hydrated session
  history, retries, and tool-only assistant turns all interact.

### 4. We need one verification path for the whole cluster

- These bugs overlap in bootstrap, auth, SSE, optimistic UI, transcript replay,
  and OpenAI Responses iteration behavior.
- They should be verified together with both backend tests and TUI-side tests.

## Current Evidence

### TUI bootstrap hard-fail path

- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
  - `bootstrap()` now throws on non-2xx for `/config/providers`, `/provider`,
    `/config`, `/provider/auth`, and system bootstrap endpoints.
  - The outer bootstrap flow exits on error instead of degrading.

### Busy-state hang path

- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
  - emits optimistic `message.updated`, `message.part.updated`, and
    `session.status = busy`
  - only resets local pending flags on send failure
  - does not reset the emitted session busy state on failure

### OpenAI/Codex empty tool-only loop path

- `penguin/llm/runtime.py`
  - `call_with_retry()` retries once and raises `LLMEmptyResponseError` for
    empty non-tool responses
- `penguin/llm/stream_handler.py`
  - finalization inserts `[Empty response from model]` when a stream completes
    with no content
- `penguin/engine.py`
  - intentionally treats `iteration_results && empty assistant text` as valid
    progress for OpenAI/Codex tool-only turns
- `penguin/llm/adapters/openai.py`
  - returns empty string for Responses tool-call-only turns

### Ordering mismatch path

- Backend transcript persistence stores canonical message order in
  `_opencode_transcript_v1.order`.
- Session view returns transcript rows in persisted order.
- TUI live sync still sorts Penguin-mode messages with
  `compareMessagesByCreated()` on every update.
- That can conflict with causal transcript order and with optimistic user events.

## Root Cause Hypotheses

### A. TUI auth/bootstrap work hardened transport but not degradation behavior

- We fixed authentication correctness first.
- We did not fully preserve the previous TUI expectation that startup and send
  failures should degrade cleanly instead of wedging the session UI.

### B. Empty-response handling is split across multiple layers with different intent

- Adapter layer: may legitimately return empty string for tool-only turns.
- Runtime retry layer: retries only when it believes there is no pending tool work.
- Engine loop: explicitly allows empty tool-only progress.
- Stream finalization layer: eventually persists placeholder content.
- That combination is correct for one or two tool-only turns, but not for long
  pathological loops.

### C. The TUI is mixing two ordering models

- Optimistic local updates use arrival time / local time.
- Persisted transcript history has canonical backend order.
- Live sync then re-sorts by `time.created`, which can override the intended
  transcript order and produce visible inversions.

## Workstreams

### Workstream 1: Fix TUI bootstrap degradation

- [x] Audit which Penguin bootstrap endpoints are truly critical for first paint.
- [x] Change Penguin-mode bootstrap so non-critical endpoint failures degrade to
      local defaults instead of exiting the whole sync flow.
- [x] Keep truly critical failures explicit and user-visible.
- [x] Surface bootstrap auth failures clearly so protected local servers do not
      look like generic loading failures.
- [x] Add or update TUI tests for protected bootstrap responses and degraded boot.

### Workstream 2: Fix prompt send failure recovery

- [x] Reset emitted session busy state when send returns non-2xx.
- [x] Reset emitted session busy state on transport-layer failures too.
- [x] Keep the optimistic local user message behavior, but ensure failure does
      not leave the session permanently working.
- [x] Show an actionable toast for transport failures, not just silent pending reset.
- [x] Add regression coverage for auth failure, network failure, and non-2xx send.

### Workstream 3: Bound empty OpenAI/Codex tool-only loops

- [x] Define the desired behavior for repeated empty tool-only iterations.
- [x] Keep valid tool-only turns working.
- [x] Add a guardrail for repeated empty tool-only assistant turns, such as:
  - max consecutive empty tool-only iterations
  - stronger diagnostics when the same tool-only empty pattern repeats
  - forced terminal error / note instead of allowing extremely long loops
- [x] Make sure the guard does not break legitimate short Codex tool chains.
- [x] Add targeted tests for repeated OpenAI/Codex empty tool-only loops.

### Workstream 4: Fix message ordering in Penguin-mode TUI

- [x] Revisit whether Penguin-mode live updates should be sorted at all once a
      session has canonical transcript order from the backend.
- [x] Decide whether ordering should follow:
  - transcript order first, or
  - timestamp order only for purely optimistic not-yet-hydrated messages
- [x] Make sure optimistic user insertion and hydrated replay reconcile without
      moving assistant responses above the triggering user turn.
- [x] Add regression coverage for:
  - optimistic local user message followed by assistant response
  - reopen / hydration after optimistic send
  - tool-only OpenAI/Codex turns followed by final assistant text

### Workstream 5: Verify the full web + TUI path together

- [x] Verify local protected startup with `uv run penguin-web` on `127.0.0.1:9000`.
- [x] Verify Penguin TUI can bootstrap against a protected local server.
- [x] Verify failed bootstrap and failed send do not leave the UI hanging.
- [x] Verify OpenAI/Codex repeated empty-turn scenarios stop in a controlled way.
- [x] Verify message order stays stable in live use and after session refresh.

## Proposed Execution Order

1. Fix bootstrap degradation in `sync.tsx`
2. Fix prompt send failure recovery in `prompt/index.tsx`
3. Add backend guardrails for repeated empty OpenAI/Codex tool-only loops
4. Fix Penguin-mode ordering semantics in TUI sync/hydration
5. Run focused backend and TUI regression coverage
6. Perform one end-to-end protected-local manual verification pass

## Candidate Files

### TUI

- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/session-hydration.ts`
- `penguin-tui/packages/opencode/test/cli/tui/sync-hydration.test.ts`

### Backend

- `penguin/engine.py`
- `penguin/llm/runtime.py`
- `penguin/llm/adapters/openai.py`
- `penguin/llm/stream_handler.py`
- `penguin/core.py`
- `penguin/web/services/session_view.py`

## Verification Checklist

- [x] `pytest -q tests/test_engine_responses_tool_calls.py`
- [x] `pytest -q tests/test_engine_responses_tool_action_results.py`
- [x] `pytest -q tests/test_core_opencode_stream_fallback.py`
- [ ] `pytest -q tests/api/test_web_auth_hardening.py tests/test_web_server.py tests/test_opencode_launcher.py`
- [x] TUI targeted test run for sync/hydration behavior
- [x] Manual local check with protected `penguin-web` + Penguin TUI-compatible bootstrap/send/auth flow

### Verification Notes

- Protected local server verification completed successfully against a real
  `uv run penguin-web` instance on `127.0.0.1:9000`.
- Unauthenticated TUI bootstrap endpoints returned `401`, confirming the
  protected-local path is active.
- The same bootstrap endpoints succeeded when replayed with the startup token in
  the `X-API-Key` header, matching Penguin TUI's auth flow.
- Unauthenticated `POST /api/v1/chat/message` returned `401`.
- Authenticated `POST /api/v1/chat/message` succeeded and created a real session.
- Session refresh confirmed stored transcript order returned `user -> assistant`
  after the live send.
- `tests/test_web_server.py` and `tests/test_opencode_launcher.py` passed.
- `tests/api/test_web_auth_hardening.py` is still not fully green in this
  environment because `test_events_websocket_accepts_authenticated_client`
  hangs instead of failing normally. The earlier auth-hardening cases in that
  file passed before the hang.

## Success Criteria

- Penguin TUI no longer exits or hangs on recoverable protected-local bootstrap failures.
- Failed send requests no longer leave sessions visually stuck as busy.
- OpenAI/Codex empty tool-only loops terminate in a controlled, diagnosable way.
- Assistant messages no longer render above the user turn that caused them.
- The fix set is documented here so future compactions and follow-up work do not
  lose the shared reasoning.
