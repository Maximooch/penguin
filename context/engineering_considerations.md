# Engineering Considerations: Multi/Sub-Agent Context Windows

This document tracks trade-offs, edge cases, and follow-ups for multi-agent and
sub-agent context window management in Penguin.

## Current Behavior

- Default agent stores sessions under `workspace/conversations/`.
- Additional agents store sessions under `workspace/conversations/<agent_id>/`.
- Checkpoints for agents are stored under `workspace/agents/<agent_id>/checkpoints`.
- Each agent has an isolated `ContextWindowManager` (CWM) by default (no shared CWM instances).
- Sub-agents are provisioned with isolated sessions and CWMs; we perform a one-time
  partial sharing of SYSTEM + CONTEXT messages from the parent to the child.
- Optional clamp at creation: the child CWM `max_tokens` can be clamped (e.g., to the
  child model's context limit) while the parent remains unchanged.

## “Auto-Clamp” Definition

When agents share a context window, auto-clamp refers to constraining the
shared CWM’s `max_tokens` to the minimum limit across the sharing agents. The
goal is to prevent provider errors in agents with smaller model context limits
by reducing the overall budgeting capacity.

Notes:
- This does not trim SYSTEM messages; trimming uses existing strategies in the CWM.
- Today, clamping is applied at child creation via `register_agent(..., model_max_tokens=...)`
  and/or `shared_cw_max_tokens`. In future, auto-derive from per-agent `ModelConfig`.

## Edge Cases

- Mismatched model limits: Parent has large context, sub-agent has smaller model.
  - Mitigation: clamp shared CWM to the smaller limit.
  - Optional system note is emitted to the parent when clamping occurs.
- Shared sessions have been removed for new sub-agents to avoid shared CWMs; each
  sub-agent uses an isolated conversation and CWM.
- Deleting shared sessions: Removing a session used by multiple agents affects
  all of them. Use guarded delete in Core to warn unless `force=True`.
- Concurrency: Multiple agents writing to one transcript interleave messages;
  Phase 3’s message envelope and UI tagging will make provenance clear.

## Finalized Decisions for Phase 2

- Do not share CWM instances across agents.
- Sub-agents are isolated by default; perform a one-time partial share (SYSTEM + CONTEXT)
  from parent to child on creation.
- Support an optional clamp for the child CWM `max_tokens` (based on child model limit).
- Emit a system note to the parent when the child CWM is effectively smaller than the parent's.
- Add guarded deletion to avoid accidental removal of sessions that legacy agents may share.

## Potential Improvements

- Per-agent `ModelConfig` with automatic clamp: Compute the min across sharing
  agents on registration changes.
- Partial sharing refresh: Add an opt-in utility to re-copy SYSTEM + CONTEXT from
  parent to child on demand (useful after significant parent context changes).
- Category-aware routing: In Phase 3/4, support selective broadcast of categories via
  the message envelope/MessageBus rather than physical copies.
- Autosave scheduling: Many isolated agents spawn autosave threads. Consider a
  shared scheduler or opt-out for idle agents.
- Deletion UX: Offer a CLI/API prompt flow for shared-session deletions.

## Remaining Work Before Phase 3

- [ ] Ensure all Engine and Core entry points accept and correctly route `agent_id`.
  - Pending: `PenguinCore.process_message` and `PenguinCore.process` remain single-agent wrappers around the default conversation.
- [ ] Add light smoke checks in CI to verify multi-agent guarantees:
  - [ ] Creating isolated sub-agents clamps child CWM when specified.
  - [ ] Partial share (SYSTEM + CONTEXT) is applied to the child only once.
  - [ ] Engine routing executes with the requested agent’s conversation/CWM.
  - [ ] Guarded delete returns a warning for shared sessions when not forced.

## Phase 3 Dependencies and Considerations

- UI/event tagging: Include `agent_id` in emitted UI events and the message envelope
  so transcripts are labeled in TUI/Web.
- Envelope fields: `agent_id`, `recipient_id`, `message_type` to enable agent-to-agent
  and human routing; update (de)serialization accordingly.
- Cross-agent checkpoints: Consider global checkpoint index keyed by `agent_id`
  to support cross-agent restore/branch flows.

## Open Questions

- Should checkpoints be globally indexed with `agent_id` tags versus per-agent
  storage trees? Global indexing supports cross-agent restore flows better.
- How should clamping events be surfaced in the TUI/Web beyond the current
  system note? (Phase 3 UI tagging.)

## Test Checklist (Phase 2)

- Create agent A; create sub-agent B with `model_max_tokens` < A’s CWM; verify B’s CWM
  is clamped and a system note appears for A.
- Verify B’s conversation initially contains A’s SYSTEM + CONTEXT only (no DIALOG/TOOLS),
  and subsequent messages no longer mirror.
- Engine.run_single_turn/run_task with `agent_id` uses the correct conversation and CWM.
- Guarded delete warns when attempting to delete a conversation referenced by multiple agents
  (for legacy shared sessions); `force=True` bypasses warning.
