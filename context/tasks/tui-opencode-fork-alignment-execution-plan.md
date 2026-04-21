# TUI Fork Alignment Execution Plan

## Summary

- Create an adapter-first refactor path for Penguin's OpenCode TUI fork.
- Push Penguin runtime differences down into narrow adapter/service helpers.
- Keep Penguin product behavior where intended, but move state and protocol
  handling out of prompt/store orchestration.
- Treat backend state as authoritative for busy/order truth while preserving
  minimal optimistic local echo for user turns.

## Findings

### 2026-04-20 Initial audit

- `context/sdk.tsx` is the healthiest existing Penguin boundary and should stay
  the primary transport/auth seam.
- `context/session-hydration.ts`, `context/sync-bootstrap.ts`, and
  `component/prompt/penguin-send.ts` already reflect the preferred extraction
  pattern: small Penguin-specific helpers outside the main UI/store files.
- The main runtime drift is concentrated in `component/prompt/index.tsx` and
  `context/sync.tsx`.
- `component/prompt/index.tsx` currently mixes prompt UI concerns with session
  creation, send flow, optimistic local event emission, pending/busy tracking,
  Penguin interrupt behavior, and agent-mode persistence.
- `context/sync.tsx` currently mixes store orchestration with bootstrap fetches,
  payload unwrapping, session/message normalization, event filtering, directory
  scoping, and usage refresh behavior.
- `routes/session/index.tsx` contains smaller but real runtime divergence via
  Penguin-specific interrupt handling and queued-message display semantics.
- `app.tsx`, `home.tsx`, `sidebar.tsx`, `permission.tsx`,
  `dialog-status.tsx`, `dialog-provider.tsx`, and `tips.tsx` are mostly
  branding/product-copy divergence, not the main runtime-boundary problem.
- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx.bak` is repo
  noise and should be removed during cleanup.

### 2026-04-20 Upstream refresh scout

- Penguin's embedded TUI package is currently at `1.1.48`; current upstream
  OpenCode latest tag fetched from `anomalyco/opencode` is `v1.14.19`
  (`2026-04-20`).
- This is not a simple linear "catch up to upstream" situation. Penguin has
  both version lag and structural divergence.
- Some local helper extractions do not exist upstream at `v1.14.19`:
  `context/session-hydration.ts`, `context/sync-bootstrap.ts`, and
  `component/prompt/penguin-send.ts`.
- The biggest runtime hot spots remain the same after upstream comparison:
  `context/sync.tsx` and `component/prompt/index.tsx`.
- Compared with upstream `v1.14.19`, local `context/sync.tsx` is much larger
  (`1159` vs `527` lines) and contains Penguin-only branching and fetch logic.
- Compared with upstream `v1.14.19`, local `component/prompt/index.tsx` is
  somewhat larger (`1584` vs `1367` lines) and still holds the highest
  concentration of Penguin-only runtime behavior.
- `routes/session/index.tsx` remains relatively close to upstream in overall
  structure, but still contains small Penguin-only runtime branches.
- Some divergence is clearly product-level rather than runtime-boundary level:
  `dialog-status.tsx` remains very close to upstream, while `home.tsx`,
  `sidebar.tsx`, and `tips.tsx` reflect heavier Penguin product customization.
- Upstream refresh should therefore be selective:
  inspect and import current upstream patterns where they simplify shared TUI
  runtime behavior, but do not attempt a blind overwrite of the fork.

### 2026-04-20 Refresh shortlist

- **Direct-refresh candidates**
  - Shared files with effectively no meaningful divergence should be refreshed
    opportunistically when touched: `ui/spinner.ts`, `ui/link.tsx`,
    `routes/session/footer.tsx`, `routes/session/dialog-subagent.tsx`,
    `context/prompt.tsx`, `context/helper.tsx`, `component/todo-item.tsx`,
    `component/border.tsx`, and most theme JSON files.
  - `component/dialog-status.tsx` is a low-risk near-upstream file; local
    changes are small and mostly Penguin naming/copy.
- **Selective-merge candidates**
  - `component/dialog-provider.tsx` is still structurally close enough to adopt
    newer upstream improvements selectively, but Penguin-specific provider/auth
    behavior must be preserved.
  - `routes/session/index.tsx` is still recognizably upstream-shaped and should
    absorb targeted upstream runtime improvements where they do not conflict
    with Penguin session semantics.
  - `component/prompt/index.tsx`, `context/sdk.tsx`, `context/sync.tsx`, and
    `app.tsx` should be compared against upstream continuously, but updated only
    through surgical merges because they carry Penguin runtime adaptation.
  - `routes/session/permission.tsx` is a medium-divergence file that can absorb
    upstream UX cleanup, but should not be treated as a blind replace.
- **Penguin-owned for now**
  - `context/session-hydration.ts`, `context/sync-bootstrap.ts`, and
    `component/prompt/penguin-send.ts` are Penguin-local extractions and should
    remain local unless upstream gains equivalent seams.
  - `routes/home.tsx`, `routes/session/sidebar.tsx`, `component/tips.tsx`,
    `component/logo.tsx`, and `component/dialog-settings.tsx` should be treated
    as Penguin product/UI files first, not upstream-sync targets.
  - `routes/session/header.tsx`, `util/api-error.ts`, `util/exit.ts`, and
    `util/session-family.ts` are local support files and should be preserved
    unless upstream adds a clearly better equivalent for the same need.
- **Upstream-only files to inspect later, not import blindly**
  - Upstream now includes broader plugin/config/runtime surface area under the
    TUI tree (`config/*`, `plugin/*`, `feature-plugins/*`, `context/project.tsx`,
    `context/tui-config.tsx`, `startup-loading`, workspace dialogs, and related
    support files).
  - These should be evaluated separately as capability additions, not folded
    into the initial fork-alignment pass.

### 2026-04-20 Implementation progress

- Added `context/penguin-sync.ts` as the first Penguin sync adapter helper.
- Moved Penguin-specific sync responsibilities into that helper:
  session-usage parsing, directory normalization, event scoping, bootstrap
  mapping, and Penguin session usage fetches.
- Rewired `context/sync.tsx` to consume the new helper instead of defining the
  Penguin bootstrap/scope logic inline.
- Added `component/prompt/penguin-runtime.ts` as the first Penguin prompt
  transport helper.
- Moved Penguin-specific prompt responsibilities into that helper:
  session-id resolution, local command parsing, agent-mode persistence, session
  creation, optimistic event construction, and prompt POST submission.
- Rewired `component/prompt/index.tsx` so Penguin prompt flow now delegates to
  the helper instead of owning the transport logic inline.
- Added focused prompt helper tests and kept the existing Penguin send failure
  tests passing.
- Sync helper tests were added, but full execution is currently blocked by
  missing local workspace dependencies (`zod` resolution through the TUI test
  environment), so sync helper behavior is only partially verified in this
  worktree right now.

## Implementation Changes

### 1. Add a Penguin TUI adapter layer

- Introduce a TUI-local typed adapter/service boundary for Penguin-specific:
  bootstrap fetches, payload normalization, session create/send/interrupt,
  directory scoping, event/session/message normalization, and usage refresh.
- Keep this adapter local to the TUI in the first slice; do not require
  generated SDK changes up front.

### 2. Reduce prompt-layer divergence

- Refactor `component/prompt/index.tsx` so it owns prompt UI state only.
- Move session creation, send, interrupt, failure recovery, and agent-mode
  persistence behind the adapter/helper boundary.
- Keep minimal optimistic echo for the local user turn, but stop letting the
  prompt own durable busy/order truth once server state arrives.

### 3. Reduce sync-layer divergence

- Refactor `context/sync.tsx` so it becomes store orchestration rather than
  endpoint adaptation.
- Replace inline payload probing and compatibility unwrapping with normalized
  adapter results.
- Keep event filtering and hydration logic explicit, but isolate Penguin-only
  rules in narrow helpers.

### 4. Preserve intentional Penguin UX

- Keep `build` / `plan` mode as Penguin product behavior.
- Keep branding/help-copy branches unless they block runtime alignment.
- Avoid broad UI churn in routes/components that are only product copy or
  branding differences.

### 5. Cleanup

- Remove stale `.bak` files associated with the audited TUI alignment work.

### 6. Upstream refresh track

- Keep upstream-refresh scouting separate from the adapter-alignment branch.
- Use upstream `v1.14.19` as the current comparison baseline unless a newer
  stable tag becomes relevant during implementation.
- Prefer targeted adoption of upstream runtime patterns in shared files over a
  broad repo-level sync.
- Use the refresh shortlist above to drive sequencing:
  direct-refresh candidates opportunistically, selective-merge candidates as
  part of runtime cleanup, and Penguin-owned files only when a local problem
  justifies changes.
- Re-evaluate backend contract changes only after adapter extraction and
  targeted upstream comparison expose a concrete mismatch worth fixing.

## Test Plan

- Add adapter-focused coverage for bootstrap normalization, degraded bootstrap
  fallback, directory scoping, and message/session normalization.
- Add prompt-flow regressions for session creation, minimal optimistic echo,
  failed send recovery, and interrupt while pending.
- Add sync/session-route regressions for canonical server ordering, queued
  rendering after hydration, and busy/idle reconciliation from server events.
- Re-run protected-local auth/bootstrap/send verification to ensure the adapter
  extraction does not regress Penguin auth handling.

## Assumptions

- Server state is authoritative for session busy/order truth as soon as backend
  events or hydrated transcript state are available.
- Minimal optimistic echo remains desirable for responsiveness.
- `build` / `plan` remains Penguin-specific UX in this pass.
- Backend contract changes are allowed later, but only if the adapter-first
  extraction reveals a concrete need.
