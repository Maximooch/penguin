# Web Session Concurrency Regression

## Summary

Penguin web regressed from supporting multiple simultaneous REST chat sessions to effectively serializing or corrupting cross-session execution.

## Symptoms

- REST chat requests appeared to run one-at-a-time.
- Different sessions in different repos/branches no longer behaved independently.
- Live verification on `:8080` showed different-session requests interfering with each other even after removing the global request gate.

## Root Causes

### 1. Global REST Request Gate

`penguin/web/routes.py` introduced a singleton `core._opencode_request_gate` around `core.process(...)`.

Impact:
- Every REST chat request on the shared global `PenguinCore` was serialized.

### 2. Shared Conversation Session Pointer Race

Even after replacing the global lock with per-session locking, the engine still used a scoped conversation wrapper that reused the shared underlying `ConversationSystem` object for the default agent.

Impact:
- `ConversationSystem.load()` mutates `self.session`.
- Concurrent requests for different session IDs could overwrite each other's active conversation session.
- This caused live request interference and long tail latency.

## Evidence

### Static Evidence

- `penguin/web/routes.py` wrapped REST chat processing in a global `asyncio.Lock` on `core`.
- `penguin/core.py` loads conversations through the conversation object associated with the engine-scoped manager.
- `penguin/system/conversation.py` mutates `self.session` during `load()`.
- `penguin/engine.py` originally used `_ScopedConversationManager` as a thin wrapper around the shared conversation object rather than cloning session state per request.

### Live Evidence

Observed on a real server running on port `8080`:
- single request: ~4.14s
- two different sessions concurrently: ~21.49s total
  - one completed in ~3.51s
  - the other stalled to ~21.48s

That pattern is inconsistent with healthy parallelism and strongly suggests cross-request shared state or upstream request corruption.

## Fix Plan

### Completed / In Progress

- Replace the global REST gate with per-session locking.
- Add regression tests for REST lock behavior.
- Add engine/session scoping tests.
- Patch engine scoped conversation handling to bind an isolated session copy per request.

### Remaining

- Re-run live verification after engine/session scoping patch.
- Make model/reasoning overrides request-scoped instead of mutating shared `core.model_config`.
- Consider request-scoped model handler selection to prevent cross-request provider/model bleed.

## Why This Matters

This is not just a performance bug.
It is a correctness bug.

Concurrency without request-scoped state isolation produces:
- session contamination
- wrong context sent to models
- misleading latency spikes
- non-deterministic behavior under parallel usage

## Notes

The global lock was the obvious regression.
The deeper issue is shared mutable request state in both conversation/session handling and model/runtime config handling.
