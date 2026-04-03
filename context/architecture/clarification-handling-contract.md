# Clarification Handling Contract

## Purpose

This document defines how Penguin should behave when execution reaches a point where clarification is materially required.

It exists to ensure the system is:

- strict about state truth
- flexible about real-world ambiguity
- explicit about waiting, escalation, and resumption behavior
- robust under human-in-the-loop execution

If implementation disagrees with this document, implementation is wrong or this document is stale. Fix one of them explicitly.

## Scope

This contract governs:

- clarification requests during ITUV execution
- workflow/execution waiting behavior
- task lifecycle truth while clarification is pending
- escalation from short-lived waiting to real blocking
- persistence and notification requirements for clarification events

This contract does **not** define the full task lifecycle. That remains in:

- `context/architecture/ituv-task-state-machine-contract.md`

This contract does **not** define artifact validation semantics. That remains in:

- `context/architecture/artifact-evidence-contract.md`

## Related Documents

- `context/architecture/ituv-task-state-machine-contract.md`
  - lifecycle legality and review/completion semantics
- `context/architecture/runmode-project-ituv-system-map.md`
  - visual map of how RunMode, ProjectManager, and ITUV interact
- `context/tasks/runmode-project-ituv-gap-matrix.md`
  - phased plan and remaining backlog
- `context/architecture/blueprint-typed-dependency-syntax-contract.md`
  - authoring rules for typed dependency syntax that may trigger clarification in ambiguous authoring cases

## Core Principle

Clarification is not failure.

Clarification is also not silent success, and it is not a reason to lie about task completion.

When an agent needs clarification, the system should preserve the truth of the current execution phase while making the waiting state explicit.

## Short Version

When clarification is needed:

- keep task `status` and `phase` truthful
- enter a workflow/execution-level waiting state
- persist a structured clarification request
- notify the relevant human or governance channel
- resume the same phase when clarification arrives
- escalate to a real blocker only if waiting becomes prolonged or external

## Clarification Categories

### Category A: Short-Lived Clarification

Examples:

- ambiguous implementation option
- missing requirement detail
- unclear preferred behavior
- need a human decision before continuing

Expected behavior:

- pause execution truthfully
- keep the task in the current active phase context
- wait for structured input

### Category B: True External Blocker

Examples:

- missing credentials
- missing environment access
- missing artifact from another task
- unresolved product decision that will not be answered quickly

Expected behavior:

- clarification may begin as short-lived waiting
- if not resolved in a reasonable window, escalate to a blocker state

## Required Behavioral Rules

### Rule 1: Do Not Guess When Clarification Materially Changes the Outcome

If multiple plausible interpretations would produce materially different implementation or validation behavior, the agent must ask rather than choose arbitrarily.

### Rule 2: Do Not Mark the Task Failed Merely Because Clarification Is Required

A clarification request is not a terminal failure.

### Rule 3: Do Not Mark the Task Completed or Review-Ready While Clarification Is Outstanding

Waiting for clarification is not equivalent to successful ITUV completion.

### Rule 4: Preserve the Current Execution Truth

If the task was in:

- `status=RUNNING`
- `phase=IMPLEMENT`

then clarification should not rewrite history into:

- `status=FAILED`
- or `status=COMPLETED`
- or `phase=PENDING`

unless an explicit escalation or reopen policy is triggered later.

### Rule 5: Persist the Clarification Request

Clarification state must not live only in transient chat text.

A structured clarification record must be stored.

## Canonical State Model

### Preferred Minimal Model

For short-lived clarification:

- `Task.status` remains unchanged, typically `RUNNING`
- `Task.phase` remains unchanged, e.g. `IMPLEMENT`, `TEST`, `USE`, or `VERIFY`
- workflow/execution state becomes:
  - `WAITING_INPUT`
  - or equivalent execution-local waiting state

This preserves lifecycle truth while still representing pause.

### Escalation Model

If clarification is not answered within a configured threshold, or if the issue is clearly external:

- execution may escalate from transient waiting to a true blocked condition

At that point the system may move the task toward an explicit blocked representation if the task-state model supports it.

## Timebox Rules

### Authoring-Level Rule

Clarification-specific timebox values may be omitted from Blueprints.

### Runtime Rule

Execution still needs an effective waiting policy derived from:

1. task-level override, if present
2. blueprint default, if present
3. system default otherwise

### Charging Rule

Time spent waiting for clarification should not be charged the same way as active implementation time.

At minimum:

- active execution time and waiting time must be distinguishable

Preferred behavior:

- pause phase timebox accounting while waiting for input

This avoids training the agent to guess recklessly just to avoid timeout pressure.

## Structured Clarification Record

Minimum required fields:

```json
{
  "task_id": "AUTH-1",
  "phase": "implement",
  "requested_by": "agent-id-or-runtime",
  "requested_at": "2026-04-01T16:00:00Z",
  "reason": "Need decision on token refresh model",
  "question": "Which refresh-token strategy should be implemented?",
  "options": [
    "rotating_refresh_tokens",
    "fixed_session_tokens"
  ],
  "status": "open"
}
```

Optional fields:

- `project_id`
- `workflow_id`
- `assumptions_blocked`
- `answered_at`
- `answered_by`
- `answer`
- `escalated`
- `escalation_reason`

## Notification Rules

When clarification is requested, the system should:

1. persist the clarification record
2. emit a user-facing question or message
3. notify the relevant operator, reviewer, or governance channel if configured
4. leave an audit trail for resumption

Minimal acceptable implementation:

- use the structured `question` tool for human clarification
- record the clarification in task/execution metadata
- emit a message/event for visibility

## Resume Rules

When clarification is answered:

- resume the same task
- resume the same phase unless an explicit reopen/restart policy applies
- attach the answer to execution evidence
- continue ITUV from the paused point

Default rule:

- clarification answer does not reset the task to `phase=PENDING`

## Escalation Rules

Clarification waiting should escalate to a more explicit blocked condition when one or more of the following is true:

- no answer arrives within the configured threshold
- the missing input is clearly an external blocker
- execution slot release is required for scheduler health
- human governance explicitly marks the task as blocked

## Enforcement Points

This contract should be enforced at:

- workflow/execution layer
  - waiting state, pause/resume behavior, timeout handling
- task/project layer
  - persistence of clarification records and escalation
- tool/messaging layer
  - structured human questions and notifications
- validation/review layer
  - prohibit false completion while clarification is still open

## Non-Goals

This contract does not yet require:

- a fully separate database table for clarifications
- multi-turn threaded clarification UI
- complex SLA/escalation routing
- role-based clarification approval chains

Those may come later if needed. The initial requirement is truthful, persistent, resumable clarification handling.

## Strategic Bottom Line

A robust system must let agents stop and ask when the world is unclear.

The wrong behavior is:

- guess and drift
- fail falsely
- complete falsely
- burn execution budget while waiting on humans

The right behavior is:

- pause truthfully
- persist the question
- notify clearly
- resume cleanly
- escalate only when waiting becomes a real blocker
