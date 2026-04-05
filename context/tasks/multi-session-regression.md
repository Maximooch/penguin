# Multi-Session Regression

Date: 2026-04-04

## Summary

This note tracks the current regression and fix work for OpenCode/Penguin multi-session
handling on the shared web server path.

The immediate problem is that chat isolation was restored recently, but session-scoped
tooling, directory resolution, and some persistence/finalization paths can still bleed
across concurrent sessions.

## Current Decisions

- Isolation boundary is exact directory/worktree, not just same git repository.
- `session_id` is authoritative for session-scoped routes such as `find/file`.
- When `session_id` and `directory` disagree, the server should reject the request
  instead of silently trusting the raw directory.

## Immediate Fix Scope

- Make `find/file` and related lookup paths prefer session binding over remembered or
  caller-provided directory state.
- Remove session listing behavior that groups different directories/worktrees together
  under the same git root/common-dir identity.
- Reduce cross-session persistence/finalization races where shared conversation objects
  are reloaded and saved for the wrong session under concurrency.
- Add focused regression tests for mismatched `session_id` and `directory`, exact-dir
  filtering, and cross-session finalize behavior.

## Known Short-Term Risks

- The web layer still sits on shared mutable conversation/session-manager state.
- `ConversationSystem.load()` and `SessionManager.current_session` are still mutable and
  request-global within an agent scope.
- Per-session request gating helps, but it does not fully isolate all session state once
  multiple requests can touch the same agent-backed conversation object.

## Longer-Term Considerations

- Move away from mutating shared `ConversationSystem` / `SessionManager` objects on the
  hot request path.
- Prefer request-local session handles or a stronger session-scoped serialization model
  around load/add/save/finalize operations.
- Audit remaining server-wide caches and remembered state for session leakage, including
  directory fallbacks, stream state, and any persistence helpers that infer session from
  mutable globals.

## Working Notes

- Latest commit restored message/history/SSE isolation more effectively than tool and
  directory isolation.
- Current unstaged work is correctly aimed at autocomplete/tag lookup and finalization,
  but needs stricter session authority and race-proof persistence behavior.
