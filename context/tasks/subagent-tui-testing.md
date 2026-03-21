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
- TUI child-session navigation already exists:
  - child-family grouping in `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx:117`
  - next/previous/parent commands in `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx:861`
  - header parent/prev/next controls in `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/header.tsx:99`
  - keybinds in `penguin-tui/packages/opencode/src/config/config.ts:820`

## Current Gaps

- Reload/bootstrap still loses useful child lineage in Penguin mode because bootstrap mapping does not preserve enough subagent metadata.
- Session-store updates in Penguin bootstrap are fragile because the local session array is not guaranteed id-sorted while some update paths assume search-friendly ordering.
- Not every spawn path emits the same child-session lifecycle events; parser and `/api/v1/agents` are better wired than lower-level tool/core paths.
- `parent_agent_id` is persisted in backend metadata, but it is not consistently surfaced through session payloads/events, so the TUI only partially understands agent lineage.
- Shared-session subagents intentionally do not become child sessions; the merge target should focus on isolated subagents as first-class TUI child sessions.

## Locked Decisions

- [x] Merge target focuses on isolated subagents (`share_session = false`) as first-class child sessions in the TUI.
- [x] Shared-session subagents remain out of scope for child-session navigation parity.
- [x] Session list remains the primary navigation surface; no graph/tree UI is required in v1.
- [x] Child sessions must preserve both session lineage (`parentID`) and agent lineage (`parent_agent_id`, and ideally child `agent_id`) through reload.

## Implementation Plan

### Phase 1: Preserve lineage during Penguin bootstrap

1. Patch `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx` so Penguin bootstrap preserves:
   - `parentID`
   - `agent_id` (when present)
   - `parent_agent_id` (when present)
2. Stop relying on `Binary.search` against unsorted Penguin session arrays, or sort/store them consistently before binary-search-based updates.
3. Ensure `session.created`, `session.updated`, and `session.deleted` keep working after that store-shape fix.

### Phase 2: Expose full lineage from backend session payloads

1. Extend `penguin/web/services/session_view.py` so `_build_session_info(...)` exports:
   - `parentID`
   - `agent_id` (or equivalent child agent identifier)
   - `parent_agent_id`
2. Ensure `/session`, `/session/{id}`, and emitted session lifecycle events all carry the same lineage shape.

### Phase 3: Unify child-session event emission across spawn paths

1. Identify all spawn paths that can create isolated subagent sessions.
2. Route them through one helper that:
   - binds the child session directory from the parent
   - emits `session.created`
   - preserves parent session + parent agent metadata
3. Most likely patch points:
   - `penguin/utils/parser.py`
   - `penguin/web/routes.py`
   - `penguin/tools/tool_manager.py`
   - possibly `penguin/core.py`

### Phase 4: Improve TUI child-session discoverability

1. Patch `penguin-tui/packages/opencode/src/cli/cmd/tui/component/dialog-session-list.tsx` so child sessions do not become confusing pseudo-roots after reload.
2. Decide a simple v1 presentation:
   - indent/group child sessions under parent, or
   - hide them from root list and rely on parent/child navigation affordances.
3. Keep header controls and `Ctrl+X Up/Left/Right` as the primary in-session navigation.

### Phase 5: Validate reload, routing, and multi-child stability

1. Extend/retain backend coverage around emitted `session.created` events.
2. Add/extend tests for bootstrap-rehydrated `parentID` and lineage.
3. Validate a parent with at least two children through reload and repeated navigation.

## Recommended Execution Order

1. `sync.tsx` bootstrap/store lineage preservation
2. backend `session_view.py` lineage payload expansion
3. unify spawn-path `session.created` emission + directory binding
4. session list child visibility/discoverability pass
5. reload/multi-child regression coverage

## Minimum Merge Bar

- [ ] Spawned sub-agents create live child sessions
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

### 2. Discovery

- [ ] Confirm the child exists in TUI session state
- [ ] Confirm the child has `parentID`
- [ ] Confirm the child is reachable from the parent view

### 3. Navigation

- [ ] `Ctrl+X Right` moves to next child session
- [ ] `Ctrl+X Left` moves to previous child session
- [ ] `Ctrl+X Up` returns to parent session
- [ ] Header controls match the same behavior
- [ ] Navigation never jumps to unrelated sessions

### 4. Message / Tool Routing

- [ ] Let the child session do real work (tool calls, file reads, etc.)
- [ ] Confirm:
  - assistant messages land in the child session, not the parent
  - tool cards land in the child session, not the parent
  - parent session shows task context but not a merged child transcript

### 5. Multiple Children

- [ ] Spawn at least two children from the same parent
- [ ] Confirm:
  - left/right cycle only within that family
  - ordering is stable enough to use repeatedly
  - parent jump always returns to the correct root session

### 6. Reload / Persistence

- [ ] Restart TUI or reconnect to the server
- [ ] Confirm:
  - parent/child relationships survive reload
  - child sessions still appear as children
  - navigation still works after reload

### 7. Session List Behavior

- [ ] Open the session list
- [ ] Confirm:
  - root sessions behave as roots
  - child sessions do not appear as confusing top-level roots when that would break navigation expectations

### 8. Abort / Exit With Child Active

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

- `penguin/core.py:4064`
- `penguin/core.py:4727`
- `penguin/core.py:4783`
- `penguin/tui_adapter/part_events.py:345`
- `penguin/tui_adapter/part_events.py:430`

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

## Manual Evidence To Capture

- [ ] screenshot of parent session before spawn
- [ ] screenshot of child session after spawn
- [ ] screenshot showing `Ctrl+X Up/Left/Right` navigation working
- [ ] one example of a child session tool run
- [ ] one reload/reconnect proof with preserved hierarchy
