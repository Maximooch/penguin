# Runtime Lifecycle Contract

Date: 2026-05-14
Status: Draft v0.1
Scope: Penguin local-first runtime, remote-ready for Link cloud containers

## Executive Position

Penguin should make local autonomous execution durable and truthful before adding
remote/container execution. Remote execution should be a data-plane backend behind
the same runtime contract, not a second lifecycle model.

Public API/SDK language should use **Run**. Internal storage can continue using
`runtime_jobs` until a migration is worth it. That gives us clear product
language without forcing churn in the existing SQLite/project code.

Core rule:

```text
Task != Run != Agent != Message != ToolCall != Artifact != ExecutionEnvironment
```

Conflating those entities is how clients end up showing lies like "completed"
when the runtime is actually waiting for clarification, reconnecting, stale, or
holding unreviewed evidence.

## Design Goals

- Preserve local behavior first; do not require cloud/container infrastructure.
- Make all autonomous work resumable, inspectable, and recoverable after process
  crashes or client disconnects.
- Keep the current TUI event bridge working as-is. Add durable runtime truth
  behind API/SDK surfaces first; let the TUI continue consuming live SSE plus
  hydration snapshots.
- Expose one public Run model through API/SDK even if internal storage remains
  named `runtime_jobs`.
- Require evidence before implementation tasks can become review-ready.
- Keep lifecycle decisions testable as pure functions, with side effects handled
  by managers/executors.
- Make remote containers for Link a backend implementation detail of
  `ExecutionEnvironment`, not a forked runtime.

## Non-Goals For v1

- Rewriting the TUI event bridge.
- Introducing cloud sandboxes before local runs are reliable.
- Replacing the existing project/task schema wholesale.
- Perfect event sourcing across every legacy chat/session path.
- Renaming every internal `runtime_job` symbol immediately.

## Naming Contract

### Public Language

Use `Run` in API, SDK, docs, and user-facing interfaces.

A Run is one durable execution attempt for a user/task objective. It may invoke
one or more agents, model turns, tool calls, messages, and artifacts.

Example public routes later:

```text
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs?task_id=...
POST /api/v1/tasks/{task_id}/runs
POST /api/v1/runs/{run_id}/cancel
GET  /api/v1/runs/{run_id}/events
```

### Internal Language

Keep `runtime_jobs` as the persistence implementation for now.

Reason: it is descriptive, already exists, and avoids churn. The mapping is:

```text
public Run == internal RuntimeJobRecord/runtime_jobs row
```

Future migration can rename storage when there is a real payoff. Until then,
API payloads should not leak `runtime_job` unless explicitly marked as internal
or debug metadata.

## Run vs RunMode

A public **Run** is not Penguin's `RunMode` object.

```text
RunMode = in-memory local executor/orchestrator
Run     = durable execution attempt record exposed by API/SDK
Task    = durable work item being attempted
```

`RunMode` performs local autonomous execution. A Run records one attempt to do
work, including status, timestamps, result, errors, evidence, and events.

Expected local flow:

```text
User/API asks to execute task
        ↓
Create runtime_jobs row as public Run
        ↓
Instantiate/use RunMode
        ↓
RunMode calls Engine.run_task(...)
        ↓
RunMode/RunService updates Run status, events, and evidence
        ↓
Task moves active → waiting_input / pending_review / failed
```

So:

```text
RunMode performs the work.
Run/runtime_job records the work.
```

This distinction matters because `RunMode` is process-local and ephemeral. If the
process dies, the `RunMode` object is gone. The Run must survive laptop sleep,
process crashes, TUI restarts, web client disconnects, and later Link cloud
container restarts.

Do not rename `RunMode` to `Run`. That would muddy the model. Long term,
`RunMode` should sit behind a run execution service:

```text
RunService
  ├── LocalRunExecutor using RunMode
  └── RemoteContainerRunExecutor using Link/cloud containers
```

Same public Run contract. Different executor backend.

## Entity Model

### Task

A Task is the durable project-management unit: what should be accomplished.

Current backing fields already exist in `tasks`:

- `status`
- `phase`
- `phase_started_at`
- `acceptance_criteria`
- `definition_of_done`
- `dependencies`
- `dependency_specs`
- `recipe`
- `artifact_evidence`

Task status should answer: **where is this work item in the human/project
workflow?**

### Run

A Run is a durable execution attempt against a task or freeform objective.

Current backing can be `runtime_jobs`:

- `job_id` -> public `run_id`
- `kind`
- `status`
- `project_id`
- `task_id`
- `session_id`
- `started_at`
- `updated_at`
- `finished_at`
- `cancel_requested`
- `cancel_reason`
- `result_summary`
- `result_json`
- `error`
- `metadata_json`

Recommended additions over time:

- `parent_run_id`
- `attempt_number`
- `agent_id`
- `environment_id`
- `last_event_id`
- `status_reason`
- `heartbeat_at`
- `idempotency_key`

Run status should answer: **what happened to this execution attempt?**

### Agent

An Agent is the model/tool actor executing part of a run.

Agent status should answer: **what is this actor doing right now?**

Agent state must not be used as task or run state.

### Message

A Message is a conversation/user/assistant/system record. It may belong to a
session, run, or agent stream.

Message status should answer: **is this message pending, streaming, complete, or
failed?**

### ToolCall

A ToolCall is one attempted tool invocation by an agent.

ToolCall status should answer: **did this operation start, complete, fail,
require approval, or get cancelled?**

Tool calls are evidence-producing events, not just UI text.

### Artifact

An Artifact is durable evidence or output produced by a run/task.

Examples:

- commit SHA
- branch name
- PR URL
- test output
- lint output
- generated file path
- screenshot path
- browser trace
- deployment preview URL
- log bundle
- human review note

Artifact status should answer: **is this evidence produced, validated, rejected,
or superseded?**

### ExecutionEnvironment

An ExecutionEnvironment is where tools/code run.

For local Penguin, this may be the current workspace shell/process context. For
Link cloud, this may be a container/devcontainer/remote sandbox. Same contract.

Environment status should answer: **is the execution substrate available and
healthy?**

## Lifecycle States

### Task Status

Task status is human/project workflow truth.

Recommended public values:

- `created` — task exists but is not ready to run.
- `pending` — task is ready but not active.
- `active` — task has an active or recent run in progress.
- `waiting_input` — task is blocked on user clarification or approval.
- `pending_review` — agent claims work is done and evidence exists; human review
  is required before completed.
- `completed` — human/system policy approved the task as done.
- `failed` — task cannot proceed without intervention.
- `cancelled` — user/system cancelled the task.

Existing enum names can differ internally, but API projections should preserve
these meanings.

### Task Phase

Task phase is ITUV/progress truth within a task.

Recommended values:

- `pending`
- `planning`
- `implementing`
- `testing`
- `using`
- `validating`
- `reviewing`
- `blocked`
- `done`

Phase must not replace status. A task can be `active` + `testing`, or
`waiting_input` + `planning`.

### Run Status

Run status is execution-attempt truth.

Recommended public values:

- `queued` — accepted but not started.
- `starting` — runtime is preparing context/environment.
- `running` — agent/model/tool execution is active.
- `waiting_input` — run paused for clarification/approval.
- `cancelling` — cancel requested and cleanup is in progress.
- `cancelled` — run was cancelled.
- `succeeded` — run reached `finish_task(status=done)` or equivalent success
  signal.
- `failed` — run ended with error.
- `stale` — run lost heartbeat/process ownership and needs recovery decision.
- `timed_out` — run exceeded execution policy.

Compatibility note: existing `runtime_jobs.status` terminal values are
`completed`, `failed`, and `cancelled`. Public API may map internal `completed`
to public `succeeded` or keep `completed` if compatibility wins. Do not map
`waiting_input` or `pending_review` to `completed`.

### Agent Status

Recommended values:

- `idle`
- `thinking`
- `streaming`
- `tool_running`
- `waiting_approval`
- `waiting_input`
- `blocked`
- `finished`
- `failed`
- `cancelled`

### Message Status

Recommended values:

- `pending`
- `processing`
- `streaming`
- `completed`
- `failed`
- `cancelled`

### ToolCall Status

Recommended values:

- `queued`
- `waiting_approval`
- `running`
- `succeeded`
- `failed`
- `cancelled`
- `timed_out`

### Artifact Status

Recommended values:

- `declared` — expected but not produced.
- `produced` — created by a run.
- `validated` — checked by tests, policy, or human review.
- `rejected` — invalid, stale, or insufficient.
- `superseded` — replaced by newer evidence.

### ExecutionEnvironment Status

Recommended values, local and remote compatible:

- `pending`
- `spawning`
- `connecting`
- `warming`
- `syncing`
- `ready`
- `running`
- `stale`
- `snapshotting`
- `stopped`
- `failed`

For local execution, many transitions can be collapsed:

```text
pending -> ready -> running -> ready/stale/failed/stopped
```

For Link cloud containers, use the fuller vocabulary.

## State Separation Rules

- A Task may have many Runs.
- A Run may use many Agents.
- A Run may produce many Messages, ToolCalls, Events, and Artifacts.
- An ExecutionEnvironment may serve many Runs over time, but a Run should record
  the environment it used.
- A successful Run does not automatically complete a Task.
- A successful implementation Run should normally move a Task to
  `pending_review`, not `completed`.
- A Task reaches `completed` only after review/approval policy passes.
- A Task with acceptance criteria must not enter `pending_review` without
  evidence records.

## Evidence Gate

For implementation tasks, `DONE != COMPLETED`.

Minimum evidence required before `pending_review`:

- `run` evidence: successful run ID and summary.
- `change` evidence when code/files changed: file paths, diff summary, commit SHA
  if available.
- `test` evidence when tests are applicable: command, exit code, output excerpt,
  timestamp.
- `usage` evidence when a feature/UI/API changed: command/request/screenshot or
  manual verification notes.
- `acceptance` evidence: criteria checked with pass/fail/unknown.

If no automated test exists, the run must produce explicit `not_tested` evidence
with a reason. That is not as good as a test, but it is honest. Honest beats
pretend-green.

Recommended v1 table:

```text
task_evidence
- id
- task_id
- run_id
- evidence_type
- artifact_key
- producer_task_id
- status
- payload_json
- created_at
- updated_at
```

Use one generic table first. Split later only if query patterns demand it.

## Runtime Event Contract

A RuntimeEvent is an append-only fact emitted by the runtime.

Recommended envelope:

```json
{
  "event_id": "evt_...",
  "sequence": 123,
  "type": "run.started",
  "timestamp": "2026-05-14T00:00:00Z",
  "project_id": "proj_...",
  "task_id": "task_...",
  "run_id": "run_...",
  "session_id": "session_...",
  "agent_id": "default",
  "environment_id": "env_local_...",
  "parent_event_id": null,
  "idempotency_key": null,
  "payload": {}
}
```

### Required Event Families

Run events:

- `run.queued`
- `run.started`
- `run.status_changed`
- `run.waiting_input`
- `run.cancel_requested`
- `run.cancelled`
- `run.succeeded`
- `run.failed`
- `run.stale`
- `run.timed_out`

Task events:

- `task.status_changed`
- `task.phase_changed`
- `task.review_ready`
- `task.completed`
- `task.failed`

Agent events:

- `agent.started`
- `agent.status_changed`
- `agent.finished`
- `agent.failed`

Message events:

- `message.created`
- `message.part.created`
- `message.part.updated`
- `message.completed`
- `message.failed`

Tool events:

- `tool.started`
- `tool.output`
- `tool.succeeded`
- `tool.failed`
- `tool.cancelled`

Artifact/evidence events:

- `artifact.declared`
- `artifact.produced`
- `artifact.validated`
- `artifact.rejected`
- `evidence.recorded`

Environment events:

- `environment.status_changed`
- `environment.heartbeat`
- `environment.stale`
- `environment.snapshot_created`
- `environment.failed`

Clarification events:

- `clarification.needed`
- `clarification.answered`
- `clarification.expired`

### TUI Compatibility

Do not require TUI bridge changes for v1.

The current TUI can keep consuming `/api/v1/events/sse` as a live OpenCode-style
projection. Durable runtime events should initially back API/SDK run inspection
and recovery. Later, SSE can optionally support replay via `after_event_id`, but
that is not required to land the contract.

Practical bridge strategy:

```text
RuntimeEvent ledger -> API/SDK run views
RuntimeEvent/live core events -> existing OpenCode-compatible SSE projection
Session hydration -> current TUI reopen semantics
```

This avoids jamming event-sourcing requirements into the most fragile UI seam.

## Pure Lifecycle Decisions

Lifecycle policy should be pure functions: input state + policy + clock ->
decision. Managers perform the side effects.

Candidate module:

```text
penguin/runtime/lifecycle/decisions.py
```

Candidate decisions:

- `evaluate_run_timeout(run_state, policy, now)`
- `evaluate_run_staleness(run_state, policy, now)`
- `evaluate_cancel_request(run_state, policy, now)`
- `evaluate_clarification_timeout(task_or_run_state, policy, now)`
- `evaluate_retry_decision(run_state, failure_history, policy, now)`
- `evaluate_environment_health(environment_state, policy, now)`
- `evaluate_spawn_or_resume(environment_state, policy, now)`
- `evaluate_review_readiness(task_state, evidence, policy)`

These functions should have boring unit tests. Boring is the goal. Lifecycle
spaghetti is where production bugs go to breed.

## Recovery Sweeps

Penguin should run recovery sweeps on startup and periodically while the web/API
server is alive.

Minimum local sweep behavior:

- Find runs in `starting` or `running` with stale `updated_at`/heartbeat.
- Mark them `stale` or `failed` based on policy.
- Find runs in `cancelling` too long and force `cancelled`/`failed` with reason.
- Find tasks marked `active` where all associated runs are terminal; move to
  `pending`, `pending_review`, `waiting_input`, or `failed` based on run result
  and evidence.
- Preserve skipped/recovery decisions as runtime events.

Remote/container sweep behavior later:

- Reconcile environment status with provider/container status.
- Resume stopped/stale persistent environments when supported.
- Restore from snapshot when available.
- Fail connecting environments that exceed timeout.
- Mark disconnected environments stale after heartbeat timeout.

## Local-First Implementation Sequence

### Phase 1 — Contract And API Projection

- Keep `runtime_jobs` internal.
- Add API/SDK payloads named `Run`.
- Ensure task execution creates/updates a durable run row.
- Add `GET /api/v1/runs/{run_id}` and list-by-task/project routes.
- Do not touch TUI bridge.

### Phase 2 — Runtime Events Ledger

- Add append-only `runtime_events` storage.
- Emit core run/task/tool/artifact events from `RunMode` and project execution.
- Add `GET /api/v1/runs/{run_id}/events`.
- Use events for API/SDK inspection and recovery; keep SSE projection live-only.

### Phase 3 — Evidence Gate

- Add `task_evidence` table or equivalent storage.
- Record evidence from tool/test/usage/artifact outputs.
- Enforce: implementation tasks cannot move to `pending_review` without evidence
  or explicit `not_tested`/`not_applicable` evidence.
- Keep `/complete` approval separate from run success.

### Phase 4 — Pure Decision Functions And Recovery

- Add lifecycle decision functions and tests.
- Add startup/periodic recovery sweep.
- Mark stale/timeout/cancelled states honestly.
- Add idempotency keys for run creation where API/webhook callers may retry.

### Phase 5 — ExecutionEnvironment Abstraction

- Model local workspace as `ExecutionEnvironment(provider="local")`.
- Add environment status events.
- Only then add container/cloud provider support for Link.

### Phase 6 — Link Remote Backend

- Implement cloud containers as an environment provider.
- Reuse the same Run, RuntimeEvent, Evidence, and Recovery contracts.
- Add provider-specific spawn/resume/restore/snapshot logic behind the
  environment manager.

## API Shape Draft

### Run Payload

```json
{
  "id": "run_123",
  "kind": "task_execution",
  "status": "running",
  "status_reason": null,
  "project_id": "proj_123",
  "task_id": "task_123",
  "session_id": "session_123",
  "agent_id": "default",
  "environment_id": "env_local_123",
  "started_at": "2026-05-14T00:00:00Z",
  "updated_at": "2026-05-14T00:01:00Z",
  "finished_at": null,
  "cancel_requested": false,
  "cancel_reason": null,
  "result_summary": null,
  "result": null,
  "error": null,
  "metadata": {},
  "links": {
    "events": "/api/v1/runs/run_123/events",
    "task": "/api/v1/tasks/task_123"
  }
}
```

### Evidence Payload

```json
{
  "id": "ev_123",
  "task_id": "task_123",
  "run_id": "run_123",
  "evidence_type": "test",
  "artifact_key": "pytest:tests/test_api.py",
  "producer_task_id": null,
  "status": "validated",
  "payload": {
    "command": "pytest tests/test_api.py",
    "exit_code": 0,
    "summary": "12 passed"
  },
  "created_at": "2026-05-14T00:00:00Z",
  "updated_at": "2026-05-14T00:00:00Z"
}
```

## Open Questions

- Should public Run status use `succeeded` or `completed`? My recommendation:
  use `succeeded` for runs and reserve `completed` for tasks. That reduces
  ambiguity.
- Should `runtime_jobs.status` migrate to the public Run vocabulary or remain a
  storage detail with mapping? Recommendation: mapping first, migration later.
- How strict should the evidence gate be for docs-only/refactor/debug tasks?
  Recommendation: task type controls required evidence classes.
- Should `not_tested` evidence be allowed to satisfy review-readiness? My
  recommendation: yes for v1, but make it visible and ugly.
- Should event replay enter `/api/v1/events/sse` immediately? Recommendation:
  no. Add run event APIs first; avoid the TUI bridge unless product pressure
  proves otherwise.

## Bottom Line

The right architecture is local-first, run-centric, event-backed, and
remote-ready.

Keep `runtime_jobs` internally. Call them Runs publicly. Make evidence mandatory
before review. Add runtime events and pure lifecycle decisions before containers.
Then Link cloud can use the same contract instead of becoming a parallel agent
platform with nicer branding and the same old lifecycle ghosts.
