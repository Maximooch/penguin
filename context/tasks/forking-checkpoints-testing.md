# Forking And Checkpoints Validation Checklist

## Goal

Validate the remaining gap between existing conversation checkpoint/branch capabilities in Penguin and the OpenCode-style TUI session forking UI, then identify the exact files to patch.

## Current Signal

- TUI already exposes fork/revert/unrevert affordances:
  - fork action in `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/dialog-message.tsx:75`
  - session fork command in `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx:390`
  - revert/unrevert actions in `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx:467`
- TUI data model already has fork/revert semantics upstream-style:
  - `penguin-tui/packages/opencode/src/session/index.ts:158`
  - `penguin-tui/packages/opencode/src/session/revert.ts:23`
- Penguin backend already has checkpoint and branching primitives:
  - `penguin/core.py:2031` create checkpoint
  - `penguin/core.py:2060` branch from checkpoint
  - `/api/v1/checkpoints/*` routes in `penguin/web/routes.py:5118`
- But the OpenCode-compatible session endpoints are not wired yet:
  - `/session/{id}/fork` currently 404s
  - no OpenCode-shaped `/session/{id}/revert` / `/session/{id}/unrevert` routes are currently present in `penguin/web/routes.py`
- Current TUI failure mode:
  - `dialog-message.tsx` assumes `result.data!.id` and crashes if the backend route is missing or returns a different shape

## Minimum Merge Bar (If Choosing To Finish This Pre-Merge)

- [ ] `POST /session/{session_id}/fork` exists and returns OpenCode-shaped `Session.Info`
- [ ] TUI fork action creates a new child/branch session and navigates to it
- [ ] Revert and unrevert routes exist and update TUI state cleanly
- [ ] Branch/checkpoint semantics are documented enough that users know what is and is not supported

## Validation Flow

### 1. Fork Endpoint Presence

- [ ] Call `POST /session/{session_id}/fork` from TUI or curl
- [ ] Confirm response is not 404
- [ ] Confirm response shape includes a new session info object with `id`

### 2. TUI Fork From Message

- [ ] Open message dialog on a user/assistant message
- [ ] Choose `Fork`
- [ ] Confirm:
  - no `result.data.id` crash
  - a new session opens
  - forked session includes the expected initial history up to the selected point

### 3. Forked Session Identity

- [ ] Confirm forked session has a distinct id and title
- [ ] Confirm parent relationship / branch semantics are reflected in metadata if intended
- [ ] Confirm further messages in the fork do not mutate the original session

### 4. Revert / Unrevert

- [ ] Trigger revert from a session with tool/file changes
- [ ] Confirm:
  - revert route exists
  - TUI marks reverted range correctly
  - diff/sidebar state updates
- [ ] Trigger unrevert
- [ ] Confirm state restores cleanly

### 5. Checkpoint Bridge

- [ ] Create a manual checkpoint through backend checkpoint routes
- [ ] Confirm checkpoint listing works
- [ ] Confirm branching from a checkpoint creates a usable conversation branch
- [ ] Decide whether TUI forking should map directly to:
  - session/message clone semantics, or
  - checkpoint-backed branch semantics

### 6. Reload / Persistence

- [ ] Restart TUI or reconnect
- [ ] Confirm forked sessions still exist
- [ ] Confirm revert metadata survives reload if supported

## If Something Fails, Patch Here

### `/session/{id}/fork` is missing or wrong

- `penguin/web/routes.py:4336`
- add OpenCode-compatible:
  - `POST /session/{session_id}/fork`
  - `/api/v1/session/{session_id}/fork` alias
- likely helper location:
  - `penguin/web/services/session_view.py`

### Fork semantics already exist, but only in internal TUI TS layer

- `penguin-tui/packages/opencode/src/session/index.ts:158`
- use as reference for expected payload/clone behavior, but backend must provide equivalent semantics for Penguin web

### TUI crashes when fork response is missing

- `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/dialog-message.tsx:79`
- add defensive handling before assuming `result.data!.id`

### Revert / unrevert not plugged into Penguin web

- `penguin-tui/packages/opencode/src/session/revert.ts:23`
- `penguin/web/routes.py`
- likely service home:
  - `penguin/web/services/session_view.py`
  - or a focused new session-branch/revert service module

### Need to bridge to existing checkpoint system

- `penguin/core.py:2031`
- `penguin/core.py:2060`
- `penguin/web/routes.py:5118`
- `penguin/system/checkpoint_manager.py`

## Design Decisions To Lock Before Full Wiring

- [ ] Should TUI `fork` mean:
  - clone transcript up to `messageID` into a new session, or
  - create a checkpoint-backed branch and load it?
- [ ] Should forked sessions set `parentID`, or remain parallel roots with title lineage only?
- [ ] Should revert/unrevert be fully exposed in Penguin web before merge, or deferred post-merge with defensive TUI guards?

## Recommended Short-Term Path

1. Add defensive TUI handling for missing fork route/shape
2. Add OpenCode-compatible `/session/{id}/fork` route returning `Session.Info`
3. Reuse existing checkpoint/branching internals where practical, but keep the external contract simple
4. Defer deeper checkpoint UX until after merge if the simple fork flow is enough

## Manual Evidence To Capture

- [ ] screenshot of fork dialog/action
- [ ] screenshot of successful forked session open
- [ ] screenshot of original and fork diverging
- [ ] server log for fork route success
- [ ] one note on whether revert/unrevert was validated or explicitly deferred
