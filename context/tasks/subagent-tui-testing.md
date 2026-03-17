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

## Useful Existing Tests

- `tests/test_action_executor_subagent_events.py`

## Manual Evidence To Capture

- [ ] screenshot of parent session before spawn
- [ ] screenshot of child session after spawn
- [ ] screenshot showing `Ctrl+X Up/Left/Right` navigation working
- [ ] one example of a child session tool run
- [ ] one reload/reconnect proof with preserved hierarchy
