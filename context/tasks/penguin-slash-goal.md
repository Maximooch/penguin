# Penguin `/goal` / `/247` Architecture Plan

## Status

Revised architecture plan based on Codex source inspection plus a current Penguin v0.9.0 codebase pass.

Last verified on July 9, 2026 against current tree at `08c3c72f6` (`v0.9.0`). The old direction is still mostly right, but the plumbing targets have changed: Penguin now has a refactored `core_runtime/` boundary, a backend command registry consumed by the TUI, durable runtime event-envelope work, and stronger OpenCode-compatible session/request state.

## Goal

Implement a session-scoped `/goal` command, with `/247` as an alias or branded wrapper, similar in spirit to Codex's `/goal`: a durable objective attached to a saved session that can drive long-running autonomous work, expose explicit lifecycle state, and resume/pause/clear without pretending it is just a one-off prompt.

## Non-Goals

- Do not implement an unbounded infinite loop.
- Do not treat `/goal` as a thin alias for `/run task`.
- Do not require a database migration for the MVP unless session metadata proves insufficient.
- Do not copy Codex internals wholesale; use Penguin's RunMode, Engine, sessions, and web/TUI surfaces.

## Source Evidence

### Codex Behavior

Local reference: `reference/codex/`.

Key observed semantics:

- `/goal <objective>` sets a thread-scoped goal.
- `/goal clear`, `/goal edit`, `/goal pause`, and `/goal resume` are first-class control commands.
- Goals require persisted sessions; ephemeral threads reject goal operations.
- Replacing an unfinished goal prompts confirmation; completed goals can be replaced directly.
- Runtime goal state tracks active goal ID, turn accounting, wall-clock accounting, continuation locks, and budget reporting.
- Lifecycle events include turn start, tool completion, goal-tool completion, turn finish, maybe-continue-if-idle, abort, usage limit, external mutation, external clear, and thread resume.
- Setting/creating a goal validates objective/budget, persists state, marks accounting active, emits a goal-updated event, and updates preview/title.

Important files:

- `reference/codex/codex-rs/tui/src/chatwidget/slash_dispatch.rs`
- `reference/codex/codex-rs/tui/src/app/thread_goal_actions.rs`
- `reference/codex/codex-rs/core/src/goals.rs`

### Penguin Existing Pieces

Penguin already has much of the executor and session machinery:

- `penguin/run_mode.py`
  - `RunMode._execute_task()` delegates formal autonomous work to `Engine.run_task()`.
  - It already handles clarification-needed and pending-review style outcomes.
- `penguin/core_runtime/`
  - Current `PenguinCore` behavior has been split into focused runtime modules. New goal plumbing should not be jammed directly into the old `core.py` monolith.
  - `process_runtime.py` owns normal message processing and session-scoped active request tracking.
  - `process_lifecycle.py` owns process finalization, token update emission, and OpenCode busy/idle request tracking.
  - `runmode_facade.py` and `runmode_lifecycle.py` own the compatibility facade for autonomous RunMode execution.
- `penguin/web/services/session_view.py`
  - Session metadata already stores OpenCode-compatible todos.
  - `get_session_todo()` and `update_session_todo()` provide a good persistence pattern.
- `penguin/web/routes.py`
  - Existing session/message/todo route style can be extended for goals.
- `penguin/web/services/command_registry.py`
  - Backend-owned command metadata is now exposed through `/api/v1/commands`.
  - Goal commands should be added here as the canonical command-list source, not only hardcoded in the TUI.
- `penguin-tui/`
  - The OpenCode-derived TUI fetches `/api/v1/commands` during sync, but Penguin-local commands still need parser/runtime handling in the prompt component.

Current-code references worth rechecking during implementation:

- `penguin/run_mode.py:240` starts one autonomous task.
- `penguin/run_mode.py:559` starts continuous mode; useful background, not the MVP path.
- `penguin/run_mode.py:1014` builds the formal task prompt and calls `Engine.run_task()`.
- `penguin/run_mode.py:1194` maps clarification-needed into `waiting_input`.
- `penguin/core_runtime/process_runtime.py:162` registers session-scoped active OpenCode requests.
- `penguin/core_runtime/process_lifecycle.py:172` increments active request counts and emits busy state.
- `penguin/core_runtime/process_lifecycle.py:131` finalizes process responses and emits token updates.
- `penguin/core_runtime/runmode_facade.py:24` is the current `PenguinCore.start_run_mode()` facade seam.
- `penguin/web/services/session_view.py:970` is the current session metadata update pattern.
- `penguin/web/services/session_view.py:1047` computes session busy/idle state from stream states, adapters, and active request counts.
- `penguin/web/routes.py:3393` exposes `/api/v1/commands`.
- `penguin/web/routes.py:6069` and `penguin/web/routes.py:6213` expose OpenCode-style todo routes and aliases.
- `penguin/web/services/command_registry.py:38` returns backend command metadata consumed by the TUI.
- `penguin/system/runtime_events.py:21` defines canonical event categories; `goal.*` is not currently a special category.
- `penguin/system/runtime_events.py:143` builds redacted public runtime event envelopes.
- `penguin/system/runtime_event_ledger.py:157` persists public runtime events for replay.
- `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx:729` fetches `/api/v1/commands` during bootstrap.
- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/penguin-local-command.ts:151` parses Penguin local slash commands.
- `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/penguin-local-command-runtime.ts:66` executes parsed Penguin HTTP local commands.

## Design Principle

`/goal` is a lifecycle controller. `RunMode` is the executor.

Bad design:

```text
/goal "ship X" -> send "ship X" as a normal prompt
```

Better design:

```text
/goal "ship X"
  -> persist session goal
  -> mark status active
  -> emit UI/session update
  -> run bounded autonomous step through RunMode/Engine
  -> update goal status from result
  -> optionally continue when idle and allowed
```

## MVP Data Model

Persist one goal per session under session metadata.

Suggested metadata key:

```text
_penguin_goal_v1
```

Suggested shape:

```json
{
  "id": "goal_...",
  "objective": "Implement the /goal command",
  "status": "active",
  "token_budget": null,
  "tokens_used": 0,
  "time_used_seconds": 0,
  "created_at": "2026-06-05T00:00:00Z",
  "updated_at": "2026-06-05T00:00:00Z",
  "revision": 1,
  "active_run_id": null,
  "last_run_id": null,
  "last_result": null,
  "metadata": {}
}
```

Allowed statuses:

```text
active | paused | blocked | usage_limited | budget_limited | complete | cleared
```

For MVP, `cleared` may simply mean the metadata key is removed.

`revision` and `active_run_id` are not decorative. They prevent a run that finishes late from resurrecting a cleared goal, overwriting a replacement goal, or changing a goal back to `active` after the user paused it. Every mutation increments `revision`; run completion may update the goal only when both the goal ID and `active_run_id` still match.

## Proposed Modules

### 1. Goal Service

Add one of:

- `penguin/core_runtime/session_goals.py`
- `penguin/web/services/session_goal.py`

Preferred split:

- `penguin/core_runtime/session_goals.py` for model/normalization/status policy and runtime result-to-status mapping.
- `penguin/web/services/session_goal.py` for route-facing session lookup/persistence wrappers, unless this is kept next to the existing todo metadata helpers in `session_view.py` for the first slice.

Avoid a top-level `penguin/goals.py` unless there is a clear reason. The current codebase is moving runtime concerns into `core_runtime/`; follow that boundary instead of adding another top-level grab bag.

Responsibilities:

- Normalize goal payloads.
- Validate objective and status.
- Create/update/clear goals in session metadata.
- Decide replacement behavior.
- Convert runtime results into goal status transitions.

### 2. Session Persistence Helpers

Mirror todo/session metadata helpers in `penguin/web/services/session_view.py` or add `penguin/web/services/session_goal.py` that imports the private session lookup helpers only if that does not create ugly coupling. The simplest first slice is probably to keep goal helpers in `session_view.py` near the existing todo helpers, then extract later if it grows.

Functions:

```python
def get_session_goal(core: Any, session_id: str) -> Optional[dict[str, Any]]:
    ...


def set_session_goal(
    core: Any,
    session_id: str,
    *,
    objective: str | None = None,
    status: str | None = None,
    token_budget: int | None | object = UNSET,
    metadata: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    ...


def clear_session_goal(core: Any, session_id: str) -> Optional[bool]:
    ...
```

Persistence rules:

- Return `None` if session does not exist.
- Create metadata dict if absent.
- Save via `manager.mark_session_modified(session.id)` and `manager.save_session(session)`.
- Validate objective is non-empty when creating/replacing.
- Validate status belongs to the allowed set.
- Use the same manager/session resolution path as current session APIs. Do not assume the default session manager; multi-agent and OpenCode session aliases matter.
- Apply compare-and-set semantics for run completion: never overwrite a goal that was paused, cleared, or replaced while the run was in flight.
- Copy and update only the goal metadata key. Do not replace the session metadata dictionary or clobber unrelated OpenCode/session fields.

### 3. Web/API Routes

Add OpenCode-style routes and v1 aliases, matching the current route pattern in `penguin/web/routes.py`.

Candidate routes:

```text
GET    /session/{session_id}/goal
POST   /session/{session_id}/goal
DELETE /session/{session_id}/goal
POST   /session/{session_id}/goal/pause
POST   /session/{session_id}/goal/resume
POST   /session/{session_id}/goal/run

GET    /api/v1/session/{session_id}/goal
POST   /api/v1/session/{session_id}/goal
DELETE /api/v1/session/{session_id}/goal
POST   /api/v1/session/{session_id}/goal/pause
POST   /api/v1/session/{session_id}/goal/resume
POST   /api/v1/session/{session_id}/goal/run
```

MVP can skip pause/resume-specific routes if `POST /goal` accepts `status`, but adding explicit pause/resume routes will make TUI command runtime cleaner and matches Codex's control surface.

Use singular `/api/v1/session/...`, not `/api/v1/sessions/...`, unless the route layer is intentionally adding both. Current OpenCode aliases are singular.

Suggested response shape:

```json
{
  "goal": { ... },
  "status": "ok"
}
```

For missing session:

```json
{
  "error": "session_not_found"
}
```

HTTP semantics should follow the existing FastAPI surface rather than returning error-shaped success bodies:

- missing session: `404`
- missing goal on a control/run operation: `404`
- unfinished goal replacement without `replace=true`: `409`
- busy session or already-running goal: `409`
- invalid objective/status/budget: `422`
- `GET` for an existing session with no goal: `200` with `{"goal": null, "status": "ok"}`

### 4. Core Runtime Bridge

Add a high-level runtime bridge through the current facade/module split, not directly as ad hoc logic in `core.py`.

Recommended shape:

- `penguin/core_runtime/session_goal_runtime.py` implements the work.
- `penguin/core_runtime/session_goal_facade.py` exposes compatibility methods on `PenguinCore`.
- `PenguinCore` inherits the facade in the same style as current process/runmode facades.

Facade method:

```python
async def run_session_goal(
    self,
    session_id: str,
    *,
    max_iterations: int | None = None,
    continue_if_active: bool = False,
) -> dict[str, Any]:
    ...
```

Responsibilities:

- Load current session goal.
- Refuse if missing, paused, complete, or cleared.
- Build a formal task prompt from goal objective and current session context.
- Call RunMode through the current `start_run_mode`/RunMode facade path or construct `RunMode` narrowly if a return value is needed.
- Execute under an explicit `ExecutionContext` bound to the target `session_id`, conversation ID, agent, and remembered/explicit directory. Verify that messages and token usage persist to that session rather than whichever conversation manager is currently active.
- Register and finalize the goal run with the existing OpenCode request lifecycle so busy/idle state, abort handling, heartbeat behavior, and duplicate-run guards are truthful. Merely checking `_opencode_active_requests` is insufficient because a direct `RunMode.start(...)` call does not register itself there.
- Add a per-session `asyncio.Lock` (or an equivalent atomic claim helper) around busy validation, `active_run_id` assignment, persistence, and request registration. The existing request counter is lifecycle accounting, not mutual exclusion.
- Persist resulting status.
- Emit goal lifecycle events through the runtime event envelope path plus legacy UI events where needed.

Important current-code wrinkle: `PenguinCore.start_run_mode()` returns `None` through the compatibility facade today. A goal runner needs a result to update status. Either:

1. introduce a result-returning `run_session_goal()` that directly creates `RunMode` and calls `RunMode.start(...)`, or
2. extend `runmode_lifecycle.start_run_mode()` to optionally return the task result without breaking callers.

Do not call `Engine.run_task()` directly unless you also replicate RunMode's streaming, clarification, and event behavior. That duplication is exactly how lifecycle bugs breed.

Implemented invariant: `Engine.run_task()` preserves the machine-readable
`finish_task` status (`done`, `partial`, or `blocked`) and summary, and
`RunMode._execute_task()` carries `finish_status`, `finish_summary`, and
`action_results` into its result. `pending_review` alone is still not enough to
drive a goal transition; the preserved `finish_status` is authoritative.

### 5. Prompt Shape For Goal Runs

Generated prompt should be explicit about its completion contract:

```text
You are executing the active session goal.

Goal: {objective}
Status: {status}

Work toward this goal using the available tools. Make concrete progress.
When the goal is fully satisfied, call finish_task with status done.
If blocked on missing information, call finish_task with status blocked or request clarification using existing Penguin clarification flow.
Continue until the goal is complete, blocked on required input or an external dependency, interrupted, or encounters a real runtime failure. Do not invent an arbitrary local stopping condition.
```

Potential context fields:

```json
{
  "goal_id": "...",
  "session_id": "...",
  "goal_objective": "...",
  "goal_status": "active",
  "run_kind": "session_goal"
}
```

### 6. Slash Command Plumbing

Expose both commands:

```text
/goal <objective>
/goal status
/goal pause
/goal resume
/goal clear
/247 <objective>
/247 status
/247 pause
/247 resume
/247 clear
```

Policy:

- `/247` is an alias to `/goal`, not a separate data model.
- `/goal` with no args shows current goal and usage help.
- `/goal <objective>` creates a new active goal.
- If an unfinished goal exists, confirm replacement in the TUI if possible. API can require `replace=true`.
- `/goal resume` marks active and optionally triggers a goal run.
- `/goal pause` marks paused and stops future continuation.
- `/goal clear` removes metadata key or marks cleared.

Current TUI/backend command plumbing changes the implementation details:

1. Add backend command metadata in `penguin/web/services/command_registry.py` so `/api/v1/commands` exposes `goal` and `247`.
2. Add route tests in `tests/api/test_opencode_command_routes.py` for `requiresSession`, `requiredContext`, templates, and execution metadata.
3. Add parser variants to `penguin-local-command.ts`:
   - `{ kind: "goal_status" }`
   - `{ kind: "goal_set", objective: string, replace?: boolean }`
   - `{ kind: "goal_pause" }`
   - `{ kind: "goal_resume" }`
   - `{ kind: "goal_clear" }`
   - optional `{ kind: "goal_run" }`
   - same for `/247` as an alias to the same kinds.
4. Add HTTP runtime execution in `penguin-local-command-runtime.ts` and mark goal commands as requiring a session.
5. Add focused Bun tests for the parser/runtime. There are no dedicated Penguin local-command test files in the current tree, so create them rather than assuming an existing neighboring suite.

Blunt point: the backend command registry improves discoverability, but it does not execute commands by itself. The TUI still parses and dispatches Penguin-local commands explicitly. Add both or the command will either show up but not work, or work but be invisible.

### 7. TUI Display

Minimum:

- Show goal set/paused/resumed/cleared messages.
- Show current goal in status/details panel if the frontend has a natural place for it.
- Show blocked/clarification-needed state visibly.

Better:

- Add a goal summary component:

```text
Goal: active — Implement /goal plumbing
Tokens: 12,340 / budget unset
Updated: 2m ago
```

### 8. Continuation Policy

MVP:

- `/goal <objective>` starts autonomous execution with no Penguin-local
  iteration, wall-clock, or token limit unless the user explicitly configured
  one.
- `/goal resume` resumes eligible paused or blocked durable state.
- `/goal run` restarts an active goal after an explicit configured limit or
  non-terminal partial return.
- `/goal pause` prevents future continuation. If a run is already active, MVP does not silently kill it; its late result must be ignored unless the goal still has the matching `active_run_id` and active status.
- `/goal clear` and replacement during an active run either return `409` or explicitly abort the run first. Do not clear/replace and then allow an old run to write into the new state.

Execution stops on:
  - `complete`
  - `paused`
  - `blocked`
  - clarification needed
  - an explicitly configured iteration, time, or token limit
  - user abort
  - a real provider, process, or persistence error

No default limit may be justified as an internal safety checkpoint. Durable
checkpointing and persistence must occur without stopping goal execution.

Current-code update: Penguin now tracks `_opencode_active_requests`, `_opencode_process_tasks`, busy/idle session status, and heartbeats for OpenCode sessions. Reuse the public lifecycle helpers for accounting, but add a per-session lock or atomic claim operation for exclusion. Under that lock, refuse when `list_session_statuses(core)[session_id]` is busy, assign/persist `active_run_id`, and register the request before release. Do not build new behavior around direct mutation of private request dictionaries.

Do not add a separate scheduler merely to compensate for artificial execution
limits. Process-restart recovery may need its own durable continuation mechanism.

## Status Transition Policy

Suggested mapping from run result:

| Runtime Outcome | Goal Status |
|---|---|
| `finish_task(status="done")` (`finish_status=done`) | `complete` |
| `finish_task(status="partial")` (`finish_status=partial`) | `active` |
| `finish_task(status="blocked")` (`finish_status=blocked`) | `blocked` |
| clarification needed / waiting input | `blocked` |
| user abort | `paused` |
| rate/usage limit | `usage_limited` |
| token budget exceeded | `budget_limited` |
| explicitly configured iteration limit reached | `active` with visible reason |
| explicitly configured wall-clock limit reached | `paused` with visible reason |
| ordinary partial progress | `active` |
| runtime error | `blocked` |

Penguin's task loop reports `pending_review` for every `finish_task` call, including `partial` and `blocked`. For session goals, treat that as transport/lifecycle state, not enough evidence of completion. The preserved `finish_status` is authoritative: only `done` completes the goal. This does not auto-approve a durable project task because a session goal run is not itself a project-task approval operation.

## Replacement Policy

MVP API behavior:

- If existing goal status is `active`, `paused`, `blocked`, `usage_limited`, or `budget_limited`, require `replace=true` to overwrite objective.
- If status is `complete`, allow replacement without `replace=true`.
- If `active_run_id` is set, replacement returns `409` unless the caller explicitly aborts that run and the abort is confirmed first.

TUI behavior:

- Prompt before replacing unfinished goal.
- No prompt needed for completed goal.

## Accounting

MVP:

- Store timestamps.
- Optionally copy token usage snapshots from existing token usage machinery.
- Do not block MVP on precise per-goal token/time accounting.

Post-MVP:

- Track tokens before/after each goal run.
- Track wall-clock seconds for active runs.
- Persist `tokens_used` and `time_used_seconds`.
- Add optional `token_budget` enforcement.

## Events

Add a UI/web event when goal changes:

```json
{
  "type": "goal.updated",
  "session_id": "...",
  "goal": { ... }
}
```

Potential event names should align with the new runtime event-envelope projection. Prefer a canonical envelope/event type such as `session.goal.updated` or `goal.updated`, then project to any OpenCode/TUI-compatible shape. Do not invent a second event pipeline just for goals.

For MVP compatibility, also emit the existing `session.updated` event after persisted goal changes so current clients know to refresh session state even if they ignore an unknown goal-specific event. The custom goal event is useful for targeted UI updates; `session.updated` is the compatibility floor.

Current nuance: `goal.*` is not listed in `RUNTIME_EVENT_CATEGORIES`, so it will currently fall back to `session_lifecycle`. That is acceptable for MVP if the event type is `session.goal.updated`. If adding standalone `goal.updated`, update `event_category()` explicitly so analytics/replay do not classify it accidentally.

Emit on:

- create
- objective replace
- status update
- clear
- run start
- run finish
- blocked/clarification

## Tests

### Unit Tests

- Goal normalization accepts valid payloads.
- Empty objective rejected.
- Unknown status rejected.
- Missing session returns `None`/404 behavior.
- Existing unfinished goal requires replacement confirmation/flag.
- Completed goal can be replaced.
- Stale run completion cannot overwrite a paused, cleared, or replacement goal.

### Service Tests

- `set_session_goal()` persists metadata and saves session.
- `clear_session_goal()` removes metadata.
- `get_session_goal()` returns normalized goal.

### Route Tests

- `GET /goal` returns current goal or null.
- `POST /goal` creates active goal.
- `POST /goal` with status pauses/resumes.
- `DELETE /goal` clears.
- Missing session returns explicit error.

### Runtime Tests

- `run_session_goal()` refuses paused/missing/complete goal.
- `run_session_goal()` refuses when the session is already busy.
- Concurrent run attempts are serialized atomically; two callers cannot both pass the idle check.
- Goal execution is bound to the requested session/directory and persists output there.
- Active goal invokes RunMode/Engine with goal context.
- Done result marks complete.
- Partial result remains active; blocked finish status marks blocked.
- Clarification result marks blocked.
- Error marks blocked.

### TUI/Command Tests

- `/goal` with no args shows status/help.
- `/goal <objective>` creates active goal.
- `/goal pause`, `resume`, `clear`, `status` route correctly.
- `/247` aliases `/goal`.
- Backend command registry exposes `goal` and `247` with `requiresSession=True`.
- TUI parser recognizes both dashed/space-free slash forms that are intended to work.
- TUI HTTP runtime sends session ID and directory in goal command bodies.

## Implementation Slices

### Slice 1: Persistence + API

- Add goal normalization/service.
- Add session metadata helpers.
- Add web routes.
- Add `/api/v1/session/{session_id}/goal` aliases as well as `/session/{session_id}/goal` routes.
- Add unit/route tests.

Acceptance:

- Goal can be created/read/updated/cleared through API and persists in session metadata.

### Slice 2: Runtime Result Contract + One-Shot Bridge

- Preserve `finish_status` from Engine through RunMode.
- Add `session_goal_runtime` + `session_goal_facade` and expose `PenguinCore.run_session_goal()`.
- Bind execution to the requested session, agent, and directory through `ExecutionContext` and the correct conversation manager.
- Register/finalize the run with existing busy/idle request lifecycle helpers.
- Generate the formal goal prompt and persist race-safe status transitions.
- Add runtime tests with mocked Engine/RunMode plus stale-run and concurrent-run coverage.

Acceptance:

- Active goal can run without implicit local limits, the correct `finish_status`
  survives the runtime stack, and the target session receives the output/status
  update.

### Slice 3: Backend Command Registry

- Add `/goal` and `/247` command metadata in `penguin/web/services/command_registry.py`.
- Mark commands `requiresSession=True` with `requiredContext=["session", "workspace"]` where runtime execution needs a live session.
- Add/extend API command registry tests.

Acceptance:

- `/api/v1/commands` exposes goal commands with correct templates, execution metadata, and session requirements.

### Slice 4: TUI Command Dispatch

- Wire TUI parser/runtime handling to the new session goal API.
- Show status/help messages.
- Add replacement confirmation where frontend supports it.
- Add Bun parser/runtime tests.

Acceptance:

- User can set/pause/resume/clear/status goal from the TUI.

### Slice 5: Continuation + Accounting

- Add safe `maybe_continue_goal_if_idle()` behavior.
- Guard against duplicate active session requests using current OpenCode active-request/session-status state.
- Add token/time accounting.
- Add budget enforcement.

Acceptance:

- Active goal continues safely while idle and stops on terminal/blocking conditions.

## Open Questions

1. Should `/goal <objective>` immediately start running, or only persist the goal until `/goal resume` / `/goal run`?
   - Decision: start immediately and apply no local iteration, wall-clock, or token limit unless the user explicitly configured one.
2. Should `finish_task(status="done")` always mark goal complete?
   - Recommendation: yes for MVP when running under `run_kind=session_goal`. Preserve and inspect `finish_status`; never infer completion from `pending_review` alone.
3. Should goals be persisted in project/task DB instead of session metadata?
   - Recommendation: session metadata for MVP. Move to DB only when cross-session/project goal querying becomes necessary.
4. Should `/247` differ semantically from `/goal`?
   - Recommendation: no. Alias only. Branding is not architecture.
5. Should `run_session_goal()` extend `start_run_mode()` to return a result, or instantiate `RunMode` directly?
   - Recommendation: add a narrow result-returning goal runtime path that uses `RunMode.start(...)` and shares event callbacks. Avoid changing broad `start_run_mode()` semantics unless tests cover all existing callers.
6. Should goal events be projected into the new durable event ledger immediately?
   - Recommendation: yes for status changes if the event-ledger API is stable enough; otherwise emit legacy UI events and leave a TODO. Goal state without visible events will feel broken in the TUI.
7. What should pause/clear/replace do to an in-flight goal run?
   - Recommendation: pause blocks future continuation and makes late completion a no-op; clear/replace return `409` while running unless an explicit abort completes first. Add stronger cancellation UX later.

## Risks

- Runaway continuation if idle scheduling is added too early.
- Confusing task/project state with session goal state.
- TUI-only implementation that leaves API/programmatic callers blind.
- API-only implementation that leaves users unable to see active goal state.
- Treating `pending_review` as `complete` too aggressively.
- Losing `finish_task(status=partial|blocked)` in the Engine/RunMode result and therefore applying the wrong terminal state.
- A late run overwriting pause/clear/replacement state without goal ID, revision, and run ID checks.
- Running against the wrong conversation manager/session because `ExecutionContext` was set but the target session was not actually loaded/bound.
- Checking busy state without registering the goal run, allowing two concurrent callers through the same idle window.
- Adding only backend command metadata and forgetting TUI parser/runtime dispatch.
- Bypassing `RunMode` and regressing streaming/clarification behavior that has already been hardened.
- Fighting the `core_runtime/` refactor by stuffing new lifecycle logic back into `core.py`.

## Recommendation

Build in this order:

1. Session metadata goal store.
2. Web/API CRUD.
3. Runtime result contract and execution bridge.
4. Backend command registry metadata.
5. TUI parser/runtime command handling.
6. Safe continuation/accounting.

This keeps the MVP small while preserving the architectural truth: `/goal` is durable session objective state plus controlled autonomous execution, not a prompt macro.

The runtime bridge now precedes TUI dispatch because the chosen command semantics
say `/goal <objective>` immediately starts execution. Shipping the command before
the bridge would expose a UI whose documented behavior is impossible. Backend
registry metadata can still land independently, but command execution should not
be advertised as complete until the runtime path exists.
