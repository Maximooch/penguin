# Multi-Session Regression

Date: 2026-04-04

## Summary

This note tracks the current regression and fix work for OpenCode/Penguin multi-session
handling on the shared web server path.

The original regression is now mostly resolved: concurrent OpenCode/TUI sessions on the
same Penguin web server no longer appear to bleed chat history, tool roots, directory
scope, or active request model/runtime state into each other during normal operation.

The remaining work is narrower and should be treated as follow-up hardening rather than
the original isolation failure. Current rough edges are around post-processing/runtime
polish, model-specific tool-call quality, and a few stale global-state fallbacks still
visible in diagnostics.

## Current Decisions

- Isolation boundary is exact directory/worktree, not just same git repository.
- `session_id` is authoritative for session-scoped routes such as `find/file`.
- When `session_id` and `directory` disagree, the server should reject the request
  instead of silently trusting the raw directory.

## Current Status

- Main multi-session request isolation appears fixed on the web server path.
- Session-local conversation state is now handed off into the engine instead of being
  re-derived from stale shared conversation state mid-request.
- Request-local model/runtime selection is now isolated, so one tab no longer appears to
  switch another tab's in-flight model.
- Session metadata now carries `providerID`, `modelID`, and `variant`, and the TUI now
  restores model selection from session info before falling back to message/global state.
- Transcript/event metadata and session title generation now prefer session-scoped model
  state over global `core.model_config` fallback.

## Immediate Fix Scope

- Completed:
- `find/file` and related lookup paths now prefer session binding over remembered or
  caller-provided directory state.
- Session listing no longer groups different directories/worktrees together under the
  same git root/common-dir identity.
- Cross-session persistence/finalization races were reduced by persisting finalized
  messages directly to the target session store instead of reloading shared conversation
  state first.
- Request-local engine state now reuses the already-loaded session-scoped conversation
  manager instead of rebuilding from stale shared base state.
- Per-session model/provider/variant metadata is now persisted and surfaced through
  session info for TUI restoration.
- Added focused regression coverage for mismatched `session_id` and `directory`,
  exact-dir filtering, request-scoped engine reuse, malformed tool-output repair, and
  session model metadata round-trip.

## Known Short-Term Risks

- The web layer still sits on shared mutable conversation/session-manager state.
- `ConversationSystem.load()` and `SessionManager.current_session` are still mutable and
  request-global within an agent scope, even though request-local handoff now avoids the
  worst observed bleed.
- Some diagnostics still reveal stale shared-session pointers (`current_conv_session`)
  even when the actual persisted output is correct because the direct session-store path
  is winning.
- Model/provider-specific behavior is still jagged in some cases:
  - OpenRouter/Kimi can fail on max-context/max-output negotiation.
  - Some models still emit malformed partial tool syntax and rely on repair turns.
  - Timeouts or abrupt stream endings can still produce rough UX even without session
    bleed.

## Longer-Term Considerations

- Move away from mutating shared `ConversationSystem` / `SessionManager` objects on the
  hot request path.
- Prefer request-local session handles or a stronger session-scoped serialization model
  around load/add/save/finalize operations.
- Audit remaining server-wide caches and remembered state for session leakage, including
  directory fallbacks, stream state, and any persistence helpers that infer session from
  mutable globals.
- Consider reducing dependence on legacy global fallbacks in transcript/event shaping so
  diagnostics and replay metadata line up more closely with the request-scoped runtime.

## Open Follow-Ups

- Clean up or eliminate stale `current_conv_session` diagnostics where possible.
- Review provider/model-specific robustness:
  - timeouts
  - context/max-output negotiation
  - malformed tool-call emission
- Improve graceful handling when a stream ends abruptly or the user aborts during a long
  request.
- Decide whether any remaining TUI oddities are server bugs, model-quality issues, or
  frontend UX issues before doing more structural work.

## Working Notes

- Previous commit restored message/history/SSE isolation more effectively than tool and
  directory isolation.
- Follow-up work fixed the deeper runtime issues that previous surface-level isolation did
  not cover:
  - request-scoped conversation handoff
  - request-scoped model runtime
  - stricter session directory authority
  - per-session model metadata persistence/restoration
- Latest live repros indicate the original multi-session bleed is no longer the primary
  problem area.
