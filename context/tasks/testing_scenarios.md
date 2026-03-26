# Multi/Sub-Agent Testing Scenarios

## Purpose
This document defines a practical manual test pack for Penguin multi-agent behavior,
with emphasis on sub-agent lifecycle, delegation, and session hierarchy behavior in
Penguin-mode/OpenCode-TUI workflows.

## Scope
- Primary: sub-agent creation, execution, visibility, and navigation.
- Secondary: inter-agent messaging/channels and delegation behavior.
- Surfaces: ActionXML parser path, tool-calling path, and API/session event path.

## Canonical Tool Surface (Current)

### ActionXML tags (supported)
- `<spawn_sub_agent>{...}</spawn_sub_agent>`
- `<stop_sub_agent>{...}</stop_sub_agent>`
- `<resume_sub_agent>{...}</resume_sub_agent>`
- `<get_agent_status>{...}</get_agent_status>`
- `<wait_for_agents>{...}</wait_for_agents>`
- `<get_context_info>{...}</get_context_info>`
- `<sync_context>{...}</sync_context>`
- `<delegate>{...}</delegate>`
- `<delegate_explore_task>{...}</delegate_explore_task>`
- `<send_message>{...}</send_message>`

### Tool-calling names (supported)
- `spawn_sub_agent`
- `stop_sub_agent`
- `resume_sub_agent`
- `delegate`
- `delegate_explore_task`
- `send_message`
- `get_agent_status`
- `wait_for_agents`
- `get_context_info`
- `sync_context`

### Out of scope / non-canonical
- `<get_sub_agent_responses>` is not a supported action tag and should not be used.

## Test Setup
1. Start server: `uv run penguin-web`
2. Open TUI in Penguin mode against that server.
3. Use a fresh session for each scenario group when possible.
4. Prefer unique child IDs per scenario (`child-smoke-1`, `child-bg-1`, etc.).

## Scenario Groups

## 1) Sub-Agent Lifecycle (Core)

| ID | Scenario | How to run | Expected result |
|---|---|---|---|
| SA-01 | Spawn isolated child | ActionXML: one `<spawn_sub_agent>` with `share_session=false`, `share_context_window=false`, `initial_prompt` | Child session appears promptly; child responds in its own session |
| SA-02 | Spawn shared-session child | ActionXML with `share_session=true`, `share_context_window=true` | No duplicate isolated child session row; responses appear in shared transcript |
| SA-03 | Background spawn | ActionXML with `background=true` + `initial_prompt` | Parent turn returns quickly; child runs asynchronously |
| SA-04 | Pause/resume child | `<stop_sub_agent>` then `<resume_sub_agent>` | Agent transitions pause/resume cleanly; no crash |
| SA-05 | Duplicate ID behavior | Spawn same `id` twice | Behavior is deterministic (no crash/corruption); record whether reused/rejected |
| SA-06 | Missing required id | `<spawn_sub_agent>{"share_session":false}</spawn_sub_agent>` | Validation error; no ghost session created |
| SA-07 | Invalid JSON | malformed `<spawn_sub_agent>` body | Parse error; no side effects |
| SA-08 | Parent override | Spawn with explicit `parent` set to non-default existing agent | Child links to the specified parent |

### Copy/paste prompt for SA-01
```text
Use exactly one tool call and then stop.
<spawn_sub_agent>{"id":"child-smoke-1","share_session":false,"share_context_window":false,"initial_prompt":"Reply exactly: CHILD_SMOKE_OK_1"}</spawn_sub_agent>
```

### Copy/paste prompt for SA-03
```text
Use exactly one tool call and then stop.
<spawn_sub_agent>{"id":"child-bg-1","share_session":false,"share_context_window":false,"background":true,"initial_prompt":"Reply exactly: CHILD_BG_OK_1"}</spawn_sub_agent>
```

## 2) Delegation and Work Distribution

| ID | Scenario | How to run | Expected result |
|---|---|---|---|
| DG-01 | Foreground delegation | Spawn child, then `<delegate>` with `child` + `content` | Delegation succeeds and child receives task |
| DG-02 | Background delegation no wait | `<delegate>` with `background=true`, `wait=false` | Returns immediately; child continues in background |
| DG-03 | Background delegation with wait | `<delegate>` with `background=true`, `wait=true`, `timeout` | Returns result if completed; timeout message if exceeded |
| DG-04 | Autonomous explore delegate | `<delegate_explore_task>` with `task` and optional `directory` | Returns structured exploration summary |
| DG-05 | Status query by id | `<get_agent_status>{"agent_id":"child"}</get_agent_status>` | Returns status for that agent |
| DG-06 | Wait via alias ids | `<wait_for_agents>{"agent_ids":["child"],"timeout":30}</wait_for_agents>` | Waits for listed agents and returns completion/timeout |
| DG-07 | Context info + sync | `<get_context_info>` then `<sync_context>` | Context relationship is visible; sync returns success or explicit error |

### Copy/paste prompt for DG-03
```text
Use exactly one tool call and then stop.
<delegate>{"child":"child-smoke-1","content":"Summarize the top-level repository layout.","background":true,"wait":true,"timeout":30}</delegate>
```

## 3) Messaging and Channels (Agent/User Surface)

| ID | Scenario | How to run | Expected result |
|---|---|---|---|
| MSG-01 | Agent-to-agent message | `<send_message>` with `target` | Message routes to target agent path without errors |
| MSG-02 | Broadcast message | `<send_message>` with `targets` array | Message fan-out succeeds to listed recipients |
| MSG-03 | Agent-to-human message | `<send_message>` without `target(s)` | Message routes to human surface |
| MSG-04 | Channel metadata | Include `channel` in `send_message`/`delegate` | Channel is preserved in routing/event payloads |

Notes:
- Messaging is push-based via MessageBus handlers/events.
- There is no inbox polling tag to "read" queued messages.

## 4) Session Hierarchy and OpenCode-TUI Parity

| ID | Scenario | How to run | Expected result |
|---|---|---|---|
| PAR-01 | Session lifecycle create from spawn | Spawn isolated child | UI session store updates immediately via `session.created` path |
| PAR-02 | Parent linkage metadata | Spawn isolated child with parent | Child session metadata includes `parentID` and `parent_agent_id` |
| PAR-03 | Shared session does not rewrite parentID | Spawn with `share_session=true` | Shared session keeps expected parent metadata behavior |
| PAR-04 | Session delete lifecycle | Delete a session via route/UI action | Session removed via `session.deleted` event path |
| PAR-05 | Replay agent attribution | Reopen child session messages | Assistant agent label remains child agent (not default fallback) |

## 5) Cross-Path Coverage (Important)

| ID | Scenario | How to run | Expected result |
|---|---|---|---|
| CP-01 | ActionXML spawn path | Use `<spawn_sub_agent>` tag | Child discoverability/session lifecycle works |
| CP-02 | Tool-calling spawn path | Instruct model: no XML, call `spawn_sub_agent` tool directly | Behavior should match ActionXML path |
| CP-03 | API agent create path | Create agent via `/api/v1/agents` | New session info appears with session lifecycle parity |

### Copy/paste prompt for CP-02
```text
Do not use XML tags. Call the `spawn_sub_agent` tool directly with:
{"id":"tool-path-1","share_session":false,"share_context_window":false,"initial_prompt":"Reply exactly: TOOL_PATH_OK_1"}
Then stop.
```

## 6) Edge Cases and Resilience

| ID | Scenario | How to run | Expected result |
|---|---|---|---|
| EC-01 | Rapid multi-spawn | Spawn 3+ unique children quickly | No race/corruption; all expected children visible |
| EC-02 | Stop nonexistent child | `<stop_sub_agent>{"id":"does-not-exist"}</stop_sub_agent>` | Graceful error/false result; no crash |
| EC-03 | Resume nonexistent child | `<resume_sub_agent>{"id":"does-not-exist"}</resume_sub_agent>` | Graceful error/false result; no crash |
| EC-04 | Background already running | Delegate background to same running child again | Returns "already running" style response |
| EC-05 | Provider empty response | Force complex/long child run on weak model | System surfaces explicit empty-response error text, stays stable |

## 7) Plan-Mode Guardrails

| ID | Scenario | How to run | Expected result |
|---|---|---|---|
| PM-01 | Plan mode visibility | Create session with `agent_mode=plan`, send normal prompt | Model behavior reflects read-only planning constraints |
| PM-02 | Execute write attempt blocked | In plan mode, run `<execute>` writing a file | Permission denied response for `code_execution` / process execution |
| PM-03 | Execute command mutation blocked | In plan mode, run `<execute_command>touch x</execute_command>` | Permission denied response |
| PM-04 | Read-only inspection still allowed | In plan mode, run `<search>` or `<enhanced_read>` | Read-only actions continue to work |

### Copy/paste prompt for PM-02
```text
Use exactly one tool call and then stop.
<execute>from pathlib import Path\nPath("plan-mode-write-test.txt").write_text("blocked?")</execute>
```

### Copy/paste prompt for PM-03
```text
Use exactly one tool call and then stop.
<execute_command>touch plan-mode-shell-write-test.txt</execute_command>
```

## 8) Suggested Run Order (Fast Manual Smoke)
1. SA-01 isolated spawn.
2. SA-03 background spawn.
3. DG-01 delegation to existing child.
4. MSG-03 send message to human surface.
5. PAR-05 replay attribution check.
6. CP-02 tool-calling spawn parity check.

## 9) Pass/Fail Notes Template
Use this template per scenario:

```text
Scenario: SA-01
Result: pass/fail
Observed behavior:
Expected behavior:
Logs/events of interest:
Follow-up action:
```

## 10) Related Automated Coverage
- `tests/test_action_executor_subagent_events.py`
- `tests/system/test_context_sharing.py`
- `tests/api/test_opencode_session_routes.py`
- `tests/api/test_session_view_service.py`

Targeted run:
`pytest -q tests/api/test_opencode_session_routes.py tests/api/test_session_view_service.py tests/system/test_context_sharing.py tests/test_action_executor_subagent_events.py`
