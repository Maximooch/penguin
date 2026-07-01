# Penguin `/goal` / `/247` Architecture Plan

## Status

Draft architecture plan based on Codex source inspection and Penguin codebase onboarding.

## Goal

Implement a session-scoped `/goal` command, with `/247` as an alias or branded wrapper, similar in spirit to Codex's `/goal`: a durable objective attached to a saved session that can drive bounded autonomous work, expose explicit lifecycle state, and resume/pause/clear without pretending it is just a one-off prompt.

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
- `penguin/core.py`
  - `Core.process()` distinguishes formal task execution from conversational turns.
  - `Core.start_run_mode()` wraps RunMode task/project execution.
  - Sessions are saved after processing.
- `penguin/web/services/session_view.py`
  - Session metadata already stores OpenCode-compatible todos.
  - `get_session_todo()` and `update_session_todo()` provide a good persistence pattern.
- `penguin/web/routes.py`
  - Existing session/message/todo route style can be extended for goals.
- `penguin-tui/`
  - Slash-command command definitions and command routing should expose `/goal` and `/247` visibly.

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

## Proposed Modules

### 1. Goal Service

Add one of:

- `penguin/goals.py`
- `penguin/services/goals.py`
- `penguin/web/services/session_goal.py`

Preferred split:

- `penguin/goals.py` for model/normalization/status policy.
- `penguin/web/services/session_goal.py` for session lookup/persistence wrappers if `session_view.py` is getting bloated.

Responsibilities:

- Normalize goal payloads.
- Validate objective and status.
- Create/update/clear goals in session metadata.
- Decide replacement behavior.
- Convert runtime results into goal status transitions.

### 2. Session Persistence Helpers

Mirror todo helpers in `penguin/web/services/session_view.py` or move both todo/goal helpers into focused services later.

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

### 3. Web/API Routes

Add OpenCode-style or Penguin-style routes. Exact route style should match existing `penguin/web/routes.py` conventions.

Candidate routes:

```text
GET    /api/v1/sessions/{session_id}/goal
POST   /api/v1/sessions/{session_id}/goal
DELETE /api/v1/sessions/{session_id}/goal
POST   /api/v1/sessions/{session_id}/goal/pause
POST   /api/v1/sessions/{session_id}/goal/resume
POST   /api/v1/sessions/{session_id}/goal/run
```

MVP can skip pause/resume-specific routes if `POST /goal` accepts `status`.

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

### 4. Core Runtime Bridge

Add a high-level method on `PenguinCore`:

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
- Call RunMode or `engine.run_task()` with explicit goal context.
- Persist resulting status.
- Emit goal lifecycle events for UI/web subscribers.

MVP implementation can call `RunMode.start(...)` or `Engine.run_task(...)` directly, but prefer reusing existing `Core.start_run_mode()` if event behavior remains correct.

### 5. Prompt Shape For Goal Runs

Generated prompt should be explicit and bounded:

```text
You are executing the active session goal.

Goal: {objective}
Status: {status}

Work toward this goal using the available tools. Make concrete progress.
When the goal is fully satisfied, call finish_task with status done.
If blocked on missing information, call finish_task with status blocked or request clarification using existing Penguin clarification flow.
Do not loop indefinitely. Stop after meaningful progress or when the current acceptance condition is met.
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

- `/goal <objective>` starts one bounded autonomous run.
- `/goal resume` starts another bounded run.
- User manually resumes as needed.

Next slice:

- If status is `active` and no request is running for session, `maybe_continue_goal_if_idle()` can enqueue another run.
- Stop continuation on:
  - `complete`
  - `paused`
  - `blocked`
  - clarification needed
  - usage/token budget exceeded
  - user abort
  - process error

Avoid uncontrolled continuation. Codex uses locks and runtime state to prevent duplicate idle continuations; Penguin should use existing active-request/session heartbeat machinery before adding a new scheduler.

## Status Transition Policy

Suggested mapping from run result:

| Runtime Outcome | Goal Status |
|---|---|
| `finish_task(status="done")` / `pending_review` with acceptance satisfied | `complete` |
| clarification needed / waiting input | `blocked` |
| user abort | `paused` |
| rate/usage limit | `usage_limited` |
| token budget exceeded | `budget_limited` |
| ordinary partial progress | `active` |
| runtime error | `blocked` |

Be careful: Penguin's current `finish_task` marks work pending human review in formal task mode. Decide whether `pending_review` means `complete` for goals or `blocked_on_review`. For MVP, use `complete` only when the result status clearly indicates done; otherwise leave `active` or `blocked`.

## Replacement Policy

MVP API behavior:

- If existing goal status is `active`, `paused`, `blocked`, `usage_limited`, or `budget_limited`, require `replace=true` to overwrite objective.
- If status is `complete`, allow replacement without `replace=true`.

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

Potential event names should align with existing Penguin event conventions. If OpenCode compatibility matters, consider a `session.goal.updated` bridge.

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
- Active goal invokes RunMode/Engine with goal context.
- Done result marks complete.
- Clarification result marks blocked.
- Error marks blocked.

### TUI/Command Tests

- `/goal` with no args shows status/help.
- `/goal <objective>` creates active goal.
- `/goal pause`, `resume`, `clear`, `status` route correctly.
- `/247` aliases `/goal`.

## Implementation Slices

### Slice 1: Persistence + API

- Add goal normalization/service.
- Add session metadata helpers.
- Add web routes.
- Add unit/route tests.

Acceptance:

- Goal can be created/read/updated/cleared through API and persists in session metadata.

### Slice 2: Runtime Bridge

- Add `PenguinCore.run_session_goal()`.
- Generate formal goal prompt.
- Invoke existing RunMode/Engine path.
- Persist status transition from result.
- Add runtime tests with mocked engine.

Acceptance:

- Active goal can run one bounded autonomous step and update status.

### Slice 3: Slash Commands

- Add `/goal` and `/247` command definitions.
- Wire command handling to API/core bridge.
- Show status/help messages.
- Add replacement confirmation where frontend supports it.

Acceptance:

- User can set/pause/resume/clear/status goal from the TUI.

### Slice 4: Continuation + Accounting

- Add safe `maybe_continue_goal_if_idle()` behavior.
- Guard against duplicate active session requests.
- Add token/time accounting.
- Add budget enforcement.

Acceptance:

- Active goal continues safely while idle and stops on terminal/blocking conditions.

## Open Questions

1. Should `/goal <objective>` immediately start running, or only persist the goal until `/goal resume` / `/goal run`?
   - Recommendation: start one bounded run immediately; continuation can be opt-in or future.
2. Should `finish_task(status="done")` always mark goal complete?
   - Recommendation: yes for MVP when running under `run_kind=session_goal`, but preserve final human-review semantics separately if needed.
3. Should goals be persisted in project/task DB instead of session metadata?
   - Recommendation: session metadata for MVP. Move to DB only when cross-session/project goal querying becomes necessary.
4. Should `/247` differ semantically from `/goal`?
   - Recommendation: no. Alias only. Branding is not architecture.

## Risks

- Runaway continuation if idle scheduling is added too early.
- Confusing task/project state with session goal state.
- TUI-only implementation that leaves API/programmatic callers blind.
- API-only implementation that leaves users unable to see active goal state.
- Treating `pending_review` as `complete` too aggressively.

## Recommendation

Build in this order:

1. Session metadata goal store.
2. Web/API CRUD.
3. One-shot runtime bridge.
4. Slash command UI.
5. Safe continuation/accounting.

This keeps the MVP small while preserving the architectural truth: `/goal` is durable session objective state plus controlled autonomous execution, not a prompt macro.
