# Subagent TUI Validation Checklist

## Goal

Validate that Penguin sub-agents are usable as first-class child sessions in the OpenCode-style TUI before merge.

## What Already Exists

- Backend sub-agent session linkage is real:
  - `parentID` / `parent_agent_id` metadata is written in `penguin/system/conversation_manager.py:332`
  - spawned children emit `session.created` in `penguin/utils/parser.py:1184`
- Web session info already exposes lineage:
  - `parentID` is included in `penguin/web/services/session_view.py:156`
  - cross-manager session listing is in `penguin/web/services/session_view.py:647`
- Penguin bootstrap/store lineage is now much stronger:
  - Penguin-mode sync preserves `parentID`, `agent_id`, and `parent_agent_id` through reload in `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
  - session create/update/delete no longer relies on sorted-array `Binary.search` assumptions in Penguin mode
- TUI child-session navigation already exists:
  - child-family grouping in `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx:117`
  - next/previous/parent commands in `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx:863`
  - header parent/prev/next controls in `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/header.tsx:99`
  - keybinds in `penguin-tui/packages/opencode/src/config/config.ts:820`
- Session list child discoverability is now present in Penguin mode:
  - child sessions are grouped/indented under their parent in `penguin-tui/packages/opencode/src/cli/cmd/tui/component/dialog-session-list.tsx`
- Automated regressions now exist for:
  - child-session list grouping
  - family navigation ordering
  - unsorted session-store upserts/removals
  - child-lineage hydration

## Current Gaps

- Parent transcript parity is still missing: isolated subagent spawns render as generic tool output/raw transcript instead of OpenCode-style clickable `Task` block cards.
- Backend tool metadata for isolated `spawn_sub_agent` / `delegate_explore_task` does not yet reliably emit OpenCode `task`-style fields such as `metadata.sessionId` and rolling `summary`.
- Background isolated child runs are not yet consistently bound to the child session/conversation execution context, so child work can land as raw inline output instead of proper child-session transcript/tool cards.
- Manual validation is still open for the full parent-card -> child-session -> reload/navigation loop, even though automated coverage is now better.
- Shared-session subagents intentionally do not become child sessions; the merge target should focus on isolated subagents as first-class TUI child sessions.

## Locked Decisions

- [x] Merge target focuses on isolated subagents (`share_session = false`) as first-class child sessions in the TUI.
- [x] Shared-session subagents remain out of scope for child-session navigation parity.
- [x] Session list remains the primary navigation surface; no graph/tree UI is required in v1.
- [x] Child sessions must preserve both session lineage (`parentID`) and agent lineage (`parent_agent_id`, and ideally child `agent_id`) through reload.
- [x] Prefer reusing OpenCode’s existing `Task` block-card renderer for isolated subagent UX; do not add Penguin-specific subagent UI if backend metadata can match the upstream shape.

## Implementation Plan

### Phase 1: Preserve lineage during Penguin bootstrap (completed)

1. [x] Patch `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx` so Penguin bootstrap preserves:
   - `parentID`
   - `agent_id` (when present)
   - `parent_agent_id` (when present)
2. [x] Stop relying on `Binary.search` against unsorted Penguin session arrays, or sort/store them consistently before binary-search-based updates.
3. [x] Ensure `session.created`, `session.updated`, and `session.deleted` keep working after that store-shape fix.

### Phase 2: Expose full lineage from backend session payloads (completed)

1. [x] Extend `penguin/web/services/session_view.py` so `_build_session_info(...)` exports:
   - `parentID`
   - `agent_id` (or equivalent child agent identifier)
   - `parent_agent_id`
2. [x] Ensure `/session`, `/session/{id}`, and emitted session lifecycle events all carry the same lineage shape.

### Phase 3: Unify child-session event emission across spawn paths (completed)

1. [x] Identify all spawn paths that can create isolated subagent sessions.
2. [x] Route them through one helper that:
   - binds the child session directory from the parent
   - emits `session.created`
   - preserves parent session + parent agent metadata
3. [x] Most likely patch points:
   - `penguin/utils/parser.py`
   - `penguin/web/routes.py`
   - `penguin/tools/tool_manager.py`
   - possibly `penguin/core.py`

### Phase 4: Improve TUI child-session discoverability (completed)

1. [x] Patch `penguin-tui/packages/opencode/src/cli/cmd/tui/component/dialog-session-list.tsx` so child sessions do not become confusing pseudo-roots after reload.
2. [x] Adopt the v1 presentation of indenting/grouping child sessions under the parent.
3. [x] Keep header controls and `Ctrl+X Up/Left/Right` as the primary in-session navigation.

### Phase 5: Validate reload, routing, and multi-child stability (partial)

1. [x] Extend/retain backend coverage around emitted `session.created` events.
2. [x] Add/extend tests for bootstrap-rehydrated `parentID` and lineage.
3. [~] Validate a parent with at least two children through reload and repeated navigation.

### Phase 6: Bridge isolated subagents to OpenCode-style task cards

1. First-pass scope: map isolated `spawn_sub_agent` flows to OpenCode `task` card metadata in Penguin backend bridge code.
2. Defer `delegate_explore_task` cosmetics unless it is upgraded to a real child-session flow; clickable parent cards only make sense when a child session exists.
3. Populate `metadata.sessionId` as soon as the child session exists.
4. Attach the minimum metadata shape needed to reuse the upstream `Task` renderer:
   - `title`
   - `model` when available
   - synthetic or rolling `summary`
5. Reuse `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx` existing `Task` component instead of adding custom Penguin-only UI.

### Phase 7: Bind child execution to the child transcript

1. Ensure background isolated child runs enter `core.process(...)` with child `session_id` / `conversation_id` / execution context.
2. Confirm child tool/message events persist in the child session and are replayable after reload.
3. Keep the parent transcript limited to task-card context/status, not raw child XML/tool stream.

## Recommended Execution Order

1. `sync.tsx` bootstrap/store lineage preservation
2. backend `session_view.py` lineage payload expansion
3. unify spawn-path `session.created` emission + directory binding
4. session list child visibility/discoverability pass
5. reload/multi-child regression coverage
6. task-style block-card parity in the parent transcript
7. child-session execution-context / transcript routing fixes

## Minimum Merge Bar

- [ ] Spawned sub-agents create live child sessions
- [ ] Isolated subagent spawns render as clickable OpenCode-style task block cards in the parent transcript
- [ ] Child/parent navigation works with default keybinds
- [ ] Child messages and tool cards stay in the child session
- [ ] Reload preserves parent/child relationships
- [ ] A parent with 2+ child sessions remains navigable and stable

## Validation Flow

### 1. Spawn

- [ ] Start from a normal parent session
- [ ] Trigger a real sub-agent spawn from a TUI flow
- [ ] Confirm:
  - child session appears live without manual refresh
  - parent session remains intact
  - a `session.created` event is visible in logs or behavior
  - parent transcript does not immediately collapse into raw child XML/plain tool output

### 2. Parent Transcript Card Parity

- [ ] Confirm the parent transcript shows an OpenCode-style clickable task/subagent block card
- [ ] Confirm the card includes a usable title and, when available, summary/progress text
- [ ] Confirm clicking the card opens the child session
- [ ] Confirm the parent transcript does not dump the child transcript inline

### 3. Discovery

- [ ] Confirm the child exists in TUI session state
- [ ] Confirm the child has `parentID`
- [ ] Confirm the child is reachable from the parent view

### 4. Navigation

- [ ] `Ctrl+X Right` moves to next child session
- [ ] `Ctrl+X Left` moves to previous child session
- [ ] `Ctrl+X Up` returns to parent session
- [ ] Header controls match the same behavior
- [ ] Navigation never jumps to unrelated sessions

### 5. Message / Tool Routing

- [ ] Let the child session do real work (tool calls, file reads, etc.)
- [ ] Confirm:
  - assistant messages land in the child session, not the parent
  - tool cards land in the child session, not the parent
  - parent session shows task-card context/status but not a merged child transcript

### 6. Multiple Children

- [ ] Spawn at least two children from the same parent
- [ ] Confirm:
  - left/right cycle only within that family
  - ordering is stable enough to use repeatedly
  - parent jump always returns to the correct root session

### 7. Reload / Persistence

- [ ] Restart TUI or reconnect to the server
- [ ] Confirm:
  - parent/child relationships survive reload
  - child sessions still appear as children
  - navigation still works after reload
  - task/subagent block cards still open the correct child session after reload

### 8. Session List Behavior

- [ ] Open the session list
- [ ] Confirm:
  - root sessions behave as roots
  - child sessions appear grouped/indented under the parent rather than as confusing top-level roots

### 9. Abort / Exit With Child Active

- [ ] Interrupt while inside a child session
- [ ] Exit while the child session is busy
- [ ] Confirm:
  - current child run aborts cleanly
  - parent/child linkage remains intact
  - no stuck busy state remains in either child or parent view

## If Something Fails, Patch Here

### Child session not created live

- `penguin/utils/parser.py:1133`
- `penguin/utils/parser.py:1184`
- `penguin/web/routes.py:355`
- `penguin/web/services/session_view.py:715`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx:430`

### `parentID` missing or wrong

- `penguin/system/conversation_manager.py:332`
- `penguin/system/conversation_manager.py:373`
- `penguin/web/services/session_view.py:156`

### Navigation reaches wrong sessions or wrong family

- `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx:117`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/header.tsx:99`
- `penguin-tui/packages/opencode/src/config/config.ts:820`

### Child messages or tools land in parent session

- `penguin/multi/executor.py`
- `penguin/core.py`
- `penguin/tui_adapter/part_events.py`

### Parent transcript shows generic tool output instead of a task card

- `penguin/core.py`
- `penguin/utils/parser.py`
- `penguin/tools/tool_manager.py`
- `penguin/tui_adapter/part_events.py`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx`

### Reload loses hierarchy

- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
- `penguin/web/services/session_view.py:647`
- `penguin/web/services/session_view.py:715`
- `penguin/system/conversation_manager.py:332`

### Session list / root view is confusing

- `penguin/web/services/session_view.py:647`
- `penguin/web/routes.py:4336`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/dialog-session-list.tsx`
- `penguin-tui/packages/opencode/src/cli/cmd/tui/app.tsx:294`

### Agent roster / metadata feels incomplete

- `penguin/agent/manager.py:50`
- `penguin/web/services/session_view.py:156`

### Session store updates are flaky after bootstrap

- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
- watch for `Binary.search` assumptions against unsorted Penguin session arrays

## Useful Existing Tests

- `tests/test_action_executor_subagent_events.py`
- `tests/tools/test_sub_agent_tools.py`
- `tests/api/test_session_view_service.py`
- `penguin-tui/packages/opencode/test/cli/tui/sync-hydration.test.ts`
- `penguin-tui/packages/opencode/test/cli/tui/session-list-children.test.ts`
- `penguin-tui/packages/opencode/test/cli/tui/session-family-navigation.test.ts`
- `penguin-tui/packages/opencode/test/cli/tui/sync-session-store.test.ts`

## Manual Evidence To Capture

- [ ] screenshot of parent session before spawn
- [ ] screenshot of the parent transcript showing the task-style subagent block card
- [ ] screenshot of child session after spawn
- [ ] screenshot showing `Ctrl+X Up/Left/Right` navigation working
- [ ] one example of a child session tool run
- [ ] one reload/reconnect proof with preserved hierarchy
