# Surface Verification Checklist

## Purpose

This file is a practical verification checklist for the public surfaces hardened so far:

- web/API surface
- `PenguinAPI` programmatic wrapper
- CLI surface

This is **not** a replacement for automated tests. It is a human/agent verification checklist for proving that the public surfaces actually behave as documented and do not drift from backend runtime truth.

## Scope

### In Scope
- CLI task/project command behavior
- web/API task/project routes
- clarification pause/resume visibility
- SSE clarification visibility
- cross-surface parity checks
- basic docs/example truth checks

### Out of Scope
- deep CLI decomposition
- major UX redesign
- exhaustive end-to-end product validation
- formal verification work

## Verification Principle

A surface is not “working” just because the command or endpoint returns something.

A surface passes only if it:
- exposes the right lifecycle truth
- uses the right terminology
- preserves non-terminal states honestly
- matches the current docs/examples closely enough that users are not being misled

## Environment Notes

Before running this checklist, confirm:

- Penguin starts locally
- project/task storage is available
- web server is running if web/API checks are included
- SSE endpoint is reachable if event checks are included
- a test project/blueprint is available for repeatable checks

Recommended setup baseline:
Recommended helper scripts in this repo:

- `scripts/verify_web_api_surface.sh`
- `scripts/verify_cli_surface.sh`
- `scripts/seed_surface_fixture.py`

Default local web verification should prefer port `9000` unless a different non-reserved port is required.

- one small project with a few tasks
- at least one task that can reach `pending_review`
- at least one task that can produce `clarification_needed`

Preferred invocation for shipped-surface checks:
- use `uv run penguin ...` for CLI verification
- use `uv run penguin-web` for web/API verification

That tests the installed/runtime entrypoints more honestly than calling internal modules directly.

## Test Fixture Recommendation

Use a small, explicit project fixture rather than improvising ad hoc tasks.

Suggested fixture shape:
- Project: `Surface Verification Demo`
- Tasks:
  - one active/runnable task
  - one running task
  - one pending-review task
  - one completed task
  - one failed task
- One task with an open clarification request
- One task with a recipe and dependency metadata

This makes parity checks much less noisy.

---

## CLI Verification

### 0. Command Discovery and Root Consistency
- [x] `uv run penguin project --help` shows the expected public subcommands
- [x] `uv run penguin project task --help` shows the expected task subcommands
- [x] help output reflects current wording for:
  - `start` → active-state semantics
  - `complete` → pending-review approval semantics
- [x] workspace / execution-root detection is stable across nested CLI subcommands
- [x] CLI does not silently switch to a different repository/workspace root between related help or command invocations

Evidence to capture:
- `uv run penguin project --help`
- `uv run penguin project task --help`
- any printed execution-root / workspace-root lines
- note whether root resolution is identical or inconsistent across invocations

### 1. Task Status Filter Semantics
- [ ] `penguin project task list --status running` works
- [x] `penguin project task list --status RUNNING` works
- [ ] `penguin project task list --status pending_review` works
- [x] invalid status input fails cleanly
- [x] invalid status error message lists real current lifecycle values

Evidence to capture:
- command output for lowercase success
- command output for uppercase success
- command output for invalid status failure

### 2. Project Status Summary Truth
- [ ] project status output counts active/running/completed/failed tasks correctly
- [ ] summary counts match underlying stored task states
- [ ] no uppercase-string drift remains in status counting

Evidence to capture:
- project status command output
- direct task list output for the same project

### 3. Task Start Semantics
- [x] `penguin project task start <TASK_ID>` succeeds for a valid task
- [x] CLI messaging says the task moved to **active state**
- [x] CLI does not falsely say “running” if the actual state is `active`
- [ ] resulting task state matches command output

Evidence to capture:
- command output
- follow-up task list / status output

### 4. Task Complete / Review Approval Semantics
- [ ] `penguin project task complete <TASK_ID>` only succeeds for `pending_review` or already-completed tasks
- [x] command behavior is clearly approval-oriented, not side-door completion
- [ ] tasks not in `pending_review` fail cleanly with honest messaging
- [x] already-completed tasks report that they are already completed

Evidence to capture:
- approval success path
- invalid-state failure path
- already-completed no-op path

### 5. Clarification Visibility
- [ ] CLI visibly surfaces `clarification_needed`
- [ ] CLI visibly surfaces `clarification_answered`
- [ ] clarification answer/resume does not leave the CLI looking stuck
- [ ] resume acknowledgement appears before or during continued execution as expected

Evidence to capture:
- screenshots or console transcript excerpts
- status text before answer
- status text after answer

---

## Web/API Verification

### Current Scripted Verification Status

The scripted web/API verification path is now passing via:

- `scripts/verify_web_api_surface.sh`

Currently verified by script:
- health endpoint / server startup on a free local port
- case-insensitive task status filtering
- honest invalid-status `400` response
- enriched task payload truth
- enriched project payload embedding
- active-state truth for task start route
- review-approval truth for task complete route
- honest missing-task `404` on clarification resume route

Still requiring separate follow-up beyond the current script:
- execute-route verification with a task that actually reaches `waiting_input`
- SSE clarification event verification against a live clarification-producing session


### 1. Task List Status Filter Semantics
- [ ] `GET /api/v1/tasks?status=running` works
- [x] `GET /api/v1/tasks?status=RUNNING` works
- [x] invalid status input returns 400 with real current options
- [ ] no false rejection of valid lowercase/uppercase values remains

Evidence to capture:
- HTTP status
- JSON response body
- invalid-status error payload

### 2. Task Payload Truth
- [x] task payloads include `status`
- [x] task payloads include `phase`
- [x] task payloads include `dependencies`
- [x] task payloads include `dependency_specs`
- [x] task payloads include `artifact_evidence`
- [x] task payloads include `recipe`
- [x] task payloads include `metadata`
- [x] task payloads include `clarification_requests`

Applicable routes:
- [ ] `GET /api/v1/tasks`
- [x] `GET /api/v1/tasks/{task_id}`
- [x] project task embedding where relevant

Evidence to capture:
- representative JSON payloads

### 3. Execute Route Lifecycle Truth
- [ ] `POST /api/v1/tasks/{task_id}/execute` routes through current runtime semantics
- [ ] `waiting_input` survives to the response when clarification is needed
- [ ] response does not flatten non-terminal outcomes into fake completion/failure
- [ ] returned task payload reflects current status/phase truth

Evidence to capture:
- JSON response for normal execution
- JSON response for clarification-needed execution

### 4. Clarification Resume Route
- [ ] `POST /api/v1/tasks/{task_id}/clarification/resume` accepts an answer
- [x] resume route fails cleanly for missing task
- [ ] resume route returns updated task payload
- [ ] clarification answer is reflected in task metadata/state as expected

Evidence to capture:
- success response JSON
- missing-task response JSON

### 5. SSE Clarification Visibility
- [ ] SSE stream shows clarification-needed session status
- [ ] SSE stream shows clarification-answered session status
- [ ] session scoping/filtering still works
- [ ] clarification events are visible to web clients without custom backend digging

Evidence to capture:
- SSE event payload excerpts
- session ID and status type fields

---

## PenguinAPI Verification

### 1. Run Task Semantics
- [ ] `PenguinAPI.run_task(...)` routes through `RunMode`
- [ ] programmatic callers can receive `waiting_input`
- [ ] result shape does not silently flatten clarification-needed outcomes

### 2. Clarification Resume Semantics
- [ ] `PenguinAPI.resume_with_clarification(...)` works for valid tasks
- [ ] answer is passed through to runtime cleanly
- [ ] returned result shape is consistent with web/runtime semantics

Evidence to capture:
- short Python snippet
- returned dictionaries for both methods

---

## Cross-Surface Parity Checks

These are high-value because surfaces drift silently.

### 1. Status Meaning Parity
- [ ] CLI and web/API use the same meaning for `active`
- [ ] CLI and web/API use the same meaning for `pending_review`
- [ ] CLI and web/API use the same meaning for `completed`
- [ ] docs/examples do not describe obsolete states as if they were current

### 2. Clarification Flow Parity
- [ ] CLI pause/resume visibility matches web/API reality
- [ ] web/API and `PenguinAPI` both preserve `waiting_input`
- [ ] clarification answer/resume is not exposed in one surface and missing in another

### 3. Messaging / Terminology Parity
- [x] “active” vs “running” wording is not contradictory across surfaces
- [x] “complete” vs “approve pending review” wording is not contradictory across surfaces

---

## Docs Truth Checks

### CLI / Task / Project Docs
- [x] CLI command docs reflect current task-start semantics
- [x] CLI command docs reflect review-approval semantics
- [x] task-management docs do not teach obsolete pending/in-progress lifecycle as literal current truth
- [x] project-management docs do not claim web/API is merely “coming soon”

### Web/API Docs
- [x] web/API docs mention richer task payloads
- [x] web/API docs mention clarification resume route
- [x] web/API docs mention SSE clarification visibility
- [x] `PenguinAPI` docs mention `resume_with_clarification(...)`

---

## Exit Criteria

The checklist should be considered passed only when:

- CLI, web/API, and `PenguinAPI` all expose current lifecycle truth honestly
- clarification flow is visible across the surfaces that claim to support it
- task state terminology is consistent enough to avoid user confusion
- docs/examples no longer materially misdescribe the current public behavior

## Notes

If a check fails because the surface is wrong, fix the surface.

If a check fails because the docs are wrong, fix the docs.

If a check fails because the intended semantics are still ambiguous, that is not a documentation problem. That is a contract problem.
