# Web / Library Surface Audit

## Purpose

This file tracks concrete findings from the public-surface audit for the web API and library surfaces after the RunMode / Project / ITUV refactor work.

This is not a rewrite spec. It is a drift-detection and remediation file.

## Scope

### In Scope
- web API task/project surface
- web SSE/event surface
- programmatic `PenguinAPI` surface in `penguin/web/app.py`
- library/public export drift relevant to task/project/clarification flows

### Out of Scope
- large CLI decomposition
- broad UX redesign
- deep library API redesign unrelated to current runtime truth

## Current Findings

### Web API

#### 1. Task status filter bug
- File: `penguin/web/routes.py`
- Endpoint: `GET /api/v1/tasks`
- Problem:
  - status parsing uses `TaskStatus(status.upper())`
  - enum values are lowercase (`active`, `running`, `pending_review`, etc.)
  - valid API input can incorrectly fail with 400
- Priority: must-fix now

#### 2. Task/project payloads are stale and too thin
- File: `penguin/web/routes.py`
- Endpoints:
  - `GET /api/v1/projects/{project_id}`
  - `POST /api/v1/tasks`
  - `GET /api/v1/tasks`
  - `GET /api/v1/tasks/{task_id}`
- Problem:
  - responses omit:
    - `phase`
    - typed dependency state
    - artifact evidence
    - recipe
    - metadata
    - clarification state
- Priority: must-fix soon

#### 3. Start-task semantics are confusing
- File: `penguin/web/routes.py`
- Endpoint: `POST /api/v1/tasks/{task_id}/start`
- Problem:
  - docstring says “set status to running”
  - implementation transitions task to `ACTIVE`
  - surface language does not match backend semantics
- Priority: must-fix soon

#### 4. Execute-task route bypasses runtime truth
- File: `penguin/web/routes.py`
- Endpoint: `POST /api/v1/tasks/{task_id}/execute`
- Problem:
  - sets task active directly
  - calls engine directly
  - collapses results to `completed -> pending_review`, everything else -> failed
  - does not expose:
    - `waiting_input`
    - clarification lifecycle
    - ITUV-aware execution truth
- Priority: high-risk; fix after basic payload/status cleanup

#### 5. Clarification resume is not exposed in the web API
- File: `penguin/web/routes.py`
- Problem:
  - backend has `RunMode.resume_with_clarification(...)`
  - no web route exposes this capability
- Priority: must-fix soon

#### 6. SSE clarification coverage is unproven
- Files:
  - `penguin/web/sse_events.py`
  - `penguin/run_mode.py`
  - `penguin/core.py`
- Problem:
  - SSE router streams `opencode_event`
  - clarification events are emitted as UI status events
  - current bridge from clarification status events to SSE compatibility surface is not obvious
- Priority: audit deeper before changing

### Library / Programmatic Surface

#### 7. `PenguinAPI` is stale relative to backend progress
- File: `penguin/web/app.py`
- Problem:
  - wrapper supports chat/conversation/run_task basics
  - no helpers for:
    - project/task lifecycle
    - clarification resume
    - richer task/project inspection
- Priority: likely separate follow-up after web API truth is fixed

## Recommended Fix Order

1. fix `GET /api/v1/tasks` status parsing
2. add `phase` and clarification-facing task fields to task responses
3. add clarification resume route
4. fix task start semantics or endpoint messaging
5. revisit `/api/v1/tasks/{task_id}/execute` to stop collapsing lifecycle truth
6. audit SSE bridging for clarification events
7. audit and modernize `PenguinAPI` wrapper

## Notes

The immediate goal is not beauty. It is surface honesty.

Any endpoint that hides `waiting_input`, flattens phase/state truth, or exposes stale status semantics is a real bug, even if the request technically succeeds.
