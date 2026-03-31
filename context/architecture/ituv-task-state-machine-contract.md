# ITUV Task State Machine Contract

## Purpose

This document is the canonical contract for task lifecycle behavior in Penguin project execution.

It defines:

- the operational meaning of task `status`
- the operational meaning of task `phase`
- allowed and forbidden `status × phase` combinations
- transition rules
- review semantics
- synthetic-task persistence requirements
- invariants that later tests and formal specs can reuse

If implementation disagrees with this document, implementation is wrong or this document is stale. One of those two things must be fixed explicitly.

## Scope

This contract applies to:

- blueprint-backed project tasks
- project-managed tasks executed through `RunMode`
- orchestrated ITUV workflows
- synthetic tasks created during project-scoped continuous execution

This contract does not attempt to define the full behavior of ad hoc conversational prompts outside project management.

## Core Principle

Penguin task execution uses two related but distinct axes:

- `status` answers: what is the lifecycle/review state of this task?
- `phase` answers: where is this task inside the ITUV execution pipeline?

They are not interchangeable.

## Status Definitions

### `PENDING`

Task exists but is not yet eligible for active execution.

Typical reasons:

- waiting on dependencies
- newly created but not activated
- reopened but not yet rescheduled

### `ACTIVE`

Task is eligible to be selected for execution.

This is the scheduler-facing ready state.

### `RUNNING`

Task is currently being worked by the orchestrator or executor.

A `RUNNING` task must also have a meaningful execution `phase`.

### `PENDING_REVIEW`

Task has passed execution gates and reached `phase=DONE`, but final completion still requires approval or trusted automated verification.

This should be the default post-ITUV terminal review state.

### `COMPLETED`

Task is fully finished.

This state is reserved for:

- human approval after `PENDING_REVIEW`, or
- an explicitly trusted automatic verification path

### `FAILED`

Task execution or validation failed in a terminal way for the current attempt.

This does not necessarily mean the task can never be retried. It means the current run did not satisfy the contract.

### `BLOCKED`

Task cannot currently proceed because of an external or structural constraint.

Examples:

- missing dependency artifact
- missing credentials or environment
- unresolved human decision
- required recipe cannot be executed

## Phase Definitions

### `PENDING`

No ITUV work has started yet.

### `IMPLEMENT`

The executor is performing the implementation step.

Examples:

- code changes
- config changes
- docs changes required by the task

### `TEST`

The executor is running or evaluating tests relevant to the implementation.

### `USE`

The executor is performing a usage-path validation.

Typical evidence:

- recipe execution
- smoke test command
- HTTP flow check
- CLI invocation
- UI/runtime behavior check

### `VERIFY`

The executor is evaluating whether the task satisfies acceptance criteria using accumulated evidence.

### `DONE`

The ITUV execution pipeline has finished successfully.

This does not automatically imply `COMPLETED`.

### `BLOCKED`

The ITUV pipeline cannot currently proceed.

This phase is allowed only when execution is blocked and the task status reflects that reality.

## Allowed Status/Phase Combinations

| Status | Allowed Phases | Notes |
| --- | --- | --- |
| `PENDING` | `PENDING` | Task exists but has not entered execution |
| `ACTIVE` | `PENDING` | Scheduler-ready task |
| `RUNNING` | `IMPLEMENT`, `TEST`, `USE`, `VERIFY` | Active execution only |
| `PENDING_REVIEW` | `DONE` | Passed pipeline, awaiting approval or trusted auto-completion |
| `COMPLETED` | `DONE` | Final successful terminal state |
| `FAILED` | `IMPLEMENT`, `TEST`, `USE`, `VERIFY`, `BLOCKED` | Failed during or because of a phase; never `DONE` |
| `BLOCKED` | `PENDING`, `IMPLEMENT`, `TEST`, `USE`, `VERIFY`, `BLOCKED` | Task is blocked before or during execution |

## Forbidden Status/Phase Combinations

These combinations must be treated as invalid:

| Status | Forbidden Phase(s) | Why |
| --- | --- | --- |
| `COMPLETED` | anything except `DONE` | Completion requires full ITUV success |
| `PENDING_REVIEW` | anything except `DONE` | Review only applies after pipeline completion |
| `RUNNING` | `PENDING`, `DONE`, `BLOCKED` | Running must correspond to an active execution phase |
| `ACTIVE` | anything except `PENDING` | Active means ready to start, not mid-phase |
| `PENDING` | anything except `PENDING` | Pending has not entered execution |
| `FAILED` | `DONE` | Failed work is not done |

## Required Invariants

The following invariants must hold once enforcement is implemented:

- `status=COMPLETED` implies `phase=DONE`
- `status=PENDING_REVIEW` implies `phase=DONE`
- `phase=DONE` implies `status in {PENDING_REVIEW, COMPLETED}`
- `status=RUNNING` implies `phase in {IMPLEMENT, TEST, USE, VERIFY}`
- `status=ACTIVE` implies `phase=PENDING`
- `status=PENDING` implies `phase=PENDING`
- `status=FAILED` implies `phase != DONE`
- project-managed execution resolves tasks by ID, not ambiguous global title lookup
- synthetic tasks must preserve provenance and project linkage

## Transition Rules

### Status Transitions

| From | To | Allowed | Trigger |
| --- | --- | --- | --- |
| `PENDING` | `ACTIVE` | Yes | dependency satisfaction, manual activation, blueprint sync normalization |
| `ACTIVE` | `RUNNING` | Yes | orchestrator claims task for execution |
| `RUNNING` | `PENDING_REVIEW` | Yes | ITUV pipeline reaches `DONE` successfully |
| `RUNNING` | `FAILED` | Yes | execution or validation fails |
| `RUNNING` | `BLOCKED` | Yes | execution cannot continue |
| `PENDING_REVIEW` | `COMPLETED` | Yes | human approval or trusted automatic verification |
| `PENDING_REVIEW` | `ACTIVE` | Yes | reviewer reopens task |
| `FAILED` | `ACTIVE` | Yes | retry or manual reopen |
| `BLOCKED` | `ACTIVE` | Yes | blocker resolved |
| `COMPLETED` | `ACTIVE` | Yes, exceptional | explicit reopen with audit trail |

Any transition not listed above should be treated as invalid by default.

### Phase Transitions

Canonical happy path:

1. `PENDING`
2. `IMPLEMENT`
3. `TEST`
4. `USE`
5. `VERIFY`
6. `DONE`

Allowed deviations:

- `IMPLEMENT -> VERIFY` only when a task explicitly has no required `TEST` or `USE` path and the contract permits this
- `TEST -> VERIFY` when no `USE` recipe is required
- any active phase may transition to `BLOCKED`
- any active phase may transition to failure via `status=FAILED`
- reopening a task resets `phase` to `PENDING` unless an explicit resume policy is defined later

## Review Semantics

### When `PENDING_REVIEW` Is Entered

A task enters `PENDING_REVIEW` when:

- ITUV pipeline reaches `phase=DONE`, and
- required evidence exists for required gates, and
- the task is not yet approved for final completion

### When `PENDING_REVIEW -> COMPLETED` Is Allowed

This transition is allowed only when one of the following is true:

- a human explicitly approves the task, or
- a trusted automatic verification path is configured and all required checks pass

### Default Rule

Default behavior should be conservative:

- successful execution ends at `DONE + PENDING_REVIEW`
- `COMPLETED` is earned, not assumed

## Dependency Readiness Policy

Dependency edges must have explicit semantics. A bare dependency reference is not enough to describe the strongest system.

### Default Policy

Unless stated otherwise, every dependency uses:

- `completion_required`

This means:

- upstream task must reach `status=COMPLETED`
- `status=PENDING_REVIEW` does **not** unlock dependents
- review remains a real gate, not a decorative afterthought

### Supported Dependency Policies

#### `completion_required`

Use when downstream work must not proceed until upstream work is fully approved or trusted-complete.

Unlock condition:

- upstream `status == COMPLETED`

Recommended for:

- infrastructure changes
- schema and migration work
- auth, billing, security, orchestration, and state-machine changes
- tasks where downstream work would amplify a bad upstream assumption

#### `review_ready_ok`

Use when downstream work may begin once upstream execution is done, even if formal approval is still pending.

Unlock condition:

- upstream `status in {PENDING_REVIEW, COMPLETED}`
- upstream `phase == DONE`

This policy must be opt-in and justified. It should be used sparingly.

Recommended only for lower-risk follow-on work such as:

- docs updates
- UI polish
- non-critical refactors
- downstream tasks that do not cement irreversible decisions

#### `artifact_ready`

Use when downstream work depends on a specific artifact or evidence object rather than full approval.

Unlock condition:

- declared artifact/evidence exists and validates
- upstream task has not failed terminally
- artifact contract is explicit and machine-checkable

Examples:

- generated client artifact exists
- schema snapshot file exists
- benchmark report artifact exists
- usage recipe output contains a required evidence key

This policy must never rely on vague human interpretation.

### Trusted Automatic Verification

`trusted_auto_verify` is a completion policy, not a dependency-edge policy.

It answers:

- when `PENDING_REVIEW -> COMPLETED` may happen automatically

It does **not** answer:

- when a dependent task may unlock

If a task uses trusted automatic verification, it may promote itself to `COMPLETED` once strict checks pass. Downstream dependency policies still evaluate against the resulting task status or artifact contract.

### Backward Compatibility Rule

Existing dependency syntax such as:

- `depends_on: [TASK-1, TASK-2]`
- markdown `- Depends: <TASK-1>, <TASK-2>`

must be interpreted as:

- `completion_required` for every listed dependency

No existing blueprint should silently change meaning during migration.

## Synthetic Task Contract

Synthetic tasks are allowed only if they are persisted and linked back to project scope.

### Required Fields

Every synthetic task must include:

- `origin=synthetic`
- `generated_by`
- `reason`
- `project_id`
- `created_at`
- `parent_task_id` or equivalent linkage when derived from an existing task

### Persistence

Synthetic tasks must be written to a persistent markdown or project-backed artifact before execution.

Ephemeral synthetic tasks are not valid project work items.

### Execution Eligibility

A synthetic task may only be executed after:

- it is persisted
- it is linked into project scope
- dependencies or parent linkage are established as needed
- it reaches a valid scheduler state

## Migration and Repair Rules

Once enforcement is added, stored tasks may already violate this contract.

Minimum migration behavior:

- detect invalid `status × phase` combinations on load, sync, or validation
- log or surface invalid tasks clearly
- normalize safe cases when rules are obvious
- require manual review for ambiguous cases

Examples:

- `COMPLETED + IMPLEMENT` should not be silently trusted
- `RUNNING + PENDING` should be treated as inconsistent state

## Enforcement Points

This contract should be enforced at the following layers:

- `penguin/project/models.py`
  - model-level validation and normalization hooks
- `penguin/project/manager.py`
  - status/phase updates, dependency normalization, synthetic task persistence rules
- `penguin/run_mode.py`
  - task resolution, no direct completion for project-managed tasks
- `penguin/project/workflow_orchestrator.py`
  - canonical ITUV phase runner and terminal-state ownership
- storage layer
  - reject or repair obviously invalid persisted states where practical

## What Stays in the Gap-Matrix Document

`context/tasks/runmode-project-ituv-gap-matrix.md` should keep:

- the problem statement
- the technical overview
- the gap matrix
- the phased plumbing plan
- the Phase 0 deliverables checklist
- a short summary of the most important invariants
- a link to this file as the canonical contract
- future fixes and out-of-scope junk backlog

It should not become a second copy of the full contract tables.

## Relationship to Future Formalization

This document is intended to feed later work such as:

- implementation tests
- invariant/property tests
- future TLA+ specs in `context/tasks/penguin_tla.md`

Formal methods come after the plumbing is real. Otherwise you are proving properties about a fantasy.
