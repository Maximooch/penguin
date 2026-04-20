# TUI OpenCode Fork Alignment Plan

## Goal

Capture a future refactor plan for bringing Penguin's TUI fork back toward
stronger OpenCode-style patterns after the current web/TUI bugfix work is done.

This is intentionally a follow-up track, not part of the immediate regression
fix pass described in `context/tasks/web-and-tui-bugfix.md`.

## Why This Exists

- Penguin's TUI started as an OpenCode fork.
- Some divergence was necessary to support Penguin's backend, local auth,
  session model, SSE bridge, and transcript semantics.
- However, the current fork has accumulated a meaningful amount of Penguin-only
  control flow directly inside the TUI state and prompt layers.
- That drift makes the fork harder to reason about and likely contributed to the
  current regressions in bootstrap, busy-state handling, optimistic UI, and
  message ordering.

## Current Assessment

### Healthy divergence

- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sdk.tsx`
  - Penguin auth header injection and SSE adaptation live close to the transport
    boundary, which is the right general direction.
- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/session-hydration.ts`
  - extracting hydration and reconciliation logic into a testable helper is
    better than leaving everything inline in `sync.tsx`.

### Risky divergence

- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
  - now owns a large amount of Penguin-specific bootstrap translation,
    endpoint fetching, event filtering, session hydration, ordering logic, and
    directory scoping.
- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
  - now contains substantial Penguin-only send/session creation flow,
    optimistic message/session-status emission, and transport fallback logic.
- The fork relies on many `sdk.penguin` branches across the TUI surface.
- The TUI is compensating for backend differences at the component/state level
  rather than through a thinner client/service boundary.

## Architectural Smell To Address Later

The main smell is not just that Penguin differs from OpenCode. It is that the
Penguin-specific behavior has leaked upward into UI and store orchestration
instead of being contained near the SDK or transport boundary.

In practice, this shows up as:

- manual `fetch` usage in TUI state code where typed client calls would be safer
- synthetic local event emission from the prompt component
- UI-side reconciliation of server truth instead of trusting a single source of truth
- duplicated bootstrap/session/message semantics split between backend and TUI
- large `sdk.penguin` branches in shared components instead of isolated adapters

## Refactor Objective

Move Penguin-specific backend adaptation down into small, testable adapter or
service layers so the TUI components can look more like upstream OpenCode again:

- typed client calls where possible
- backend-owned truth for sessions/messages/status
- thinner prompt and sync components
- fewer inline Penguin/OpenCode bifurcations

## Important Constraint

This refactor should happen only after the current bugfix track is complete and
stable enough that we are not mixing reliability fixes with architecture churn.

Immediate bugfixes first:

- `context/tasks/web-and-tui-bugfix.md`

Then fork-alignment refactor.

## Future Workstreams

### Workstream 1: Audit the Penguin/OpenCode boundary

- [ ] Inventory all `sdk.penguin` branches under `penguin-tui/packages/opencode/src/cli/cmd/tui/`
- [ ] Group them into:
  - transport/auth differences
  - bootstrap/session API differences
  - optimistic UI differences
  - purely presentational branding differences
- [ ] Identify which branches belong in the SDK layer versus UI components.

### Workstream 2: Reduce prompt-layer divergence

- [ ] Revisit `component/prompt/index.tsx` and isolate Penguin-specific send logic.
- [ ] Decide whether optimistic local message emission should remain in the TUI.
- [ ] If optimistic behavior is still needed, move it into one narrow helper or
      service instead of keeping it inline in the prompt component.
- [ ] Make prompt submission use one clearer abstraction for:
  - session creation
  - message send
  - command handling
  - failure recovery

### Workstream 3: Reduce sync-layer divergence

- [ ] Break `context/sync.tsx` into smaller Penguin-specific helpers where needed.
- [ ] Minimize inline manual bootstrap shape translation.
- [ ] Revisit whether session hydration, ordering, and directory scoping belong
      directly in the main sync context.
- [ ] Keep `sync.tsx` focused on store orchestration, not endpoint adaptation.

### Workstream 4: Prefer typed boundaries over ad hoc fetches

- [ ] Review which Penguin endpoints should be represented in the generated SDK
      or a thin typed client wrapper.
- [ ] Replace manual response-shape probing where practical.
- [ ] Reduce custom `unwrap()`-style compatibility logic in UI state code.

### Workstream 5: Re-center server truth

- [ ] Revisit where message ordering truth should live.
- [ ] Revisit where session busy/idle truth should live.
- [ ] Revisit whether the backend can provide enough immediate state for the TUI
      to stop synthesizing some of its own events.

### Workstream 6: Keep brand/UI differences, isolate runtime differences

- [ ] Preserve intentional Penguin branding and product-level UX differences.
- [ ] Separate those from runtime/transport differences so branding changes do
      not share code paths with message/session state behavior.

## Suggested Execution Order

1. Finish the current web/TUI regression fixes
2. Audit all `sdk.penguin` branches and classify them
3. Extract prompt submission and bootstrap helpers into clearer boundaries
4. Reduce `sync.tsx` responsibilities
5. Revisit typed client coverage for Penguin-specific backend endpoints
6. Remove or shrink UI-layer protocol emulation where possible

## Candidate Files

- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sdk.tsx`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/session-hydration.ts`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx`
- `reference/opencode/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
- `reference/opencode/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`

## Success Criteria

- Penguin keeps the backend/runtime behavior it needs.
- The TUI uses clearer, thinner boundaries for Penguin-specific behavior.
- Shared TUI components look closer to upstream OpenCode patterns again.
- Regressions caused by duplicated UI/backend state logic become less likely.
- Future upstream syncs are easier because Penguin-only behavior is more localized.
