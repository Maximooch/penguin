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
- OpenCode-compatible fork/revert routes are now present in Penguin web:
  - `POST /session/{id}/fork`
  - `POST /session/{id}/revert`
  - `POST /session/{id}/unrevert`
- Checkpoint branch route now returns real session info alongside legacy `branch_id`.
- Current remaining gaps from manual validation:
  - forking works well end-to-end from the TUI
  - revert/unrevert is only partially there: the backend works, but the TUI still feels like it is hiding a suffix of conversation state rather than providing an intuitive rollback/redo experience
  - checkpoint creation/branch/rollback is still not exposed in the TUI surface, so users cannot discover it from normal session/message actions

## Locked Decisions

- [x] TUI `fork` means: clone transcript history up to `messageID` into a new session.
- [x] Forked sessions should remain parallel roots in the session list (title lineage, not `parentID` subagent linkage).
- [x] Revert and unrevert should be fully exposed in Penguin web before merge.
- [x] Checkpoint branches should materialize as real sessions that can be opened from the normal session list; branch switching does not require a graph view in v1.

## Implementation Plan

### Phase 1: Stop TUI fork crashes immediately

1. Add defensive handling in:
   - `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/dialog-message.tsx`
   - `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/dialog-fork-from-timeline.tsx`
2. If `sdk.client.session.fork(...)` returns no `data.id` or an error:
   - show a toast/dialog error,
   - do not navigate,
   - do not crash.

### Phase 2: Add OpenCode-compatible fork API

Add routes in `penguin/web/routes.py`:

- `POST /session/{session_id}/fork`
- `POST /api/v1/session/{session_id}/fork`

Suggested request body:

```json
{
  "messageID": "optional-message-id"
}
```

Suggested response:
- OpenCode-shaped `Session.Info`

Implementation shape:

- Add a focused service module, likely `penguin/web/services/session_fork.py`
- Main function:

```python
fork_session(
    core,
    session_id: str,
    *,
    message_id: str | None = None,
    directory: str | None = None,
) -> dict[str, Any]
```

Behavior:

1. Resolve source session and owning manager.
2. Create a new saved session via the owning manager.
3. Copy transcript/messages/parts up to `message_id`.
4. Preserve directory binding/project identity.
5. Set lineage metadata such as:
   - `forked_from_session_id`
   - `forked_from_message_id`
6. Generate a user-friendly fork title (`<title> (fork #n)`).
7. Return `get_session_info(...)` for the new session.
8. Emit `session.created`.

### Phase 3: Add OpenCode-compatible revert / unrevert API

Add routes in `penguin/web/routes.py`:

- `POST /session/{session_id}/revert`
- `POST /api/v1/session/{session_id}/revert`
- `POST /session/{session_id}/unrevert`
- `POST /api/v1/session/{session_id}/unrevert`

Suggested request bodies:

```json
{
  "messageID": "message-id",
  "partID": "optional-part-id"
}
```

and

```json
{}
```

Suggested response:
- updated OpenCode-shaped `Session.Info`

Implementation shape:

- Add a focused service module, likely `penguin/web/services/session_revert.py`
- Main functions:

```python
revert_session(core, session_id: str, *, message_id: str, part_id: str | None = None) -> dict[str, Any]
unrevert_session(core, session_id: str) -> dict[str, Any]
```

Behavior:

1. Refuse revert/unrevert when session is busy.
2. Track the snapshot/filesystem state needed to restore later.
3. Compute/store revert metadata in session metadata:
   - `messageID`
   - `partID`
   - `snapshot`
   - `diff`
4. Recompute session diff/summary and emit update events.
5. On unrevert, restore snapshot and clear revert metadata.

### Phase 4: Expose revert metadata in session payloads

Extend `penguin/web/services/session_view.py` so `_build_session_info(...)` maps session metadata into the OpenCode fields expected by the TUI:

- `revert`
- `summary`

This is required for:

- `Undo previous message`
- `Redo`
- reverted-range rendering in the session view

### Phase 5: Bridge checkpoints and branches to real sessions

Keep the existing checkpoint system, but make branch creation materialize a real session that the TUI can open through the existing session list.

Likely patch points:

- `penguin/core.py`
- `penguin/system/conversation_manager.py`
- `penguin/system/checkpoint_manager.py`
- `penguin/web/routes.py`

Goal:

1. Branch from checkpoint produces a real saved session.
2. That session appears in `/session` and `/session/{id}`.
3. The TUI can switch branches using the normal session list, since there is no graph UI in v1.

### Phase 6: Validation and regression tests

Add/extend tests in:

- `tests/api/test_opencode_session_routes.py`
- `tests/api/test_session_view_service.py`
- likely new:
  - `tests/api/test_session_fork_routes.py`
  - `tests/api/test_session_revert_routes.py`

Minimum automated coverage:

- fork returns `Session.Info`
- fork copies history only through requested `messageID`
- fork emits `session.created`
- revert stores metadata and updates diff/summary
- unrevert clears metadata and restores state
- checkpoint branch returns a real new session

## Minimum Merge Bar (Current)

- [x] `POST /session/{session_id}/fork` exists and returns OpenCode-shaped `Session.Info`
- [x] TUI fork action creates a new child/branch session and navigates to it
- [~] Revert and unrevert routes exist, but TUI state/UX still needs another practical pass before calling it complete
- [~] Branch/checkpoint semantics are mostly documented in backend behavior, but checkpoint UI discoverability is still absent in the TUI

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
  - new post-revert turns remain visible
  - diff/sidebar state updates
- [ ] Trigger unrevert
- [ ] Confirm state restores cleanly

### 5. Checkpoint Bridge

- [ ] Create a manual checkpoint through backend checkpoint routes
- [ ] Confirm checkpoint listing works
- [ ] Confirm branching from a checkpoint creates a usable conversation branch
- [ ] Confirm branched checkpoint session appears in the normal session list
- [ ] Decide whether checkpoint creation/branch/rollback needs a first-class TUI dialog before merge, or is explicitly deferred

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

### Revert / unrevert feels functionally wrong in the TUI

- `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx`
- `penguin/web/services/session_revert.py`
- likely issue areas:
  - hidden-message selection and rendering
  - repeated undo/redo anchor selection
  - mixing new post-revert turns with hidden reverted history

### Checkpointing is not discoverable in the TUI

- add a TUI command/dialog surface, likely in:
  - `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/dialog-message.tsx`
  - `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx`
  - new `dialog-checkpoints.tsx`

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

- [x] TUI `fork` means clone transcript up to `messageID` into a new session.
- [x] Forked sessions remain parallel roots with title lineage only.
- [x] Revert/unrevert should be fully exposed in Penguin web before merge.
- [x] Checkpoint branches should become real sessions navigated through the session list.

## Recommended Short-Term Path

1. Add defensive TUI fork handling so the UI never crashes.
2. Add OpenCode-compatible `/session/{id}/fork` route returning `Session.Info`.
3. Add `/session/{id}/revert` and `/session/{id}/unrevert` plus session payload mapping for `revert` and `summary`.
4. Bridge checkpoint branching into real saved sessions navigable via the normal session list.
5. Use the session list as the branch-navigation UX in v1; defer any graph-style UI.

## Manual Evidence To Capture

- [ ] screenshot of fork dialog/action
- [ ] screenshot of successful forked session open
- [ ] screenshot of original and fork diverging
- [ ] server log for fork route success
- [ ] one note on whether revert/unrevert was validated or explicitly deferred
