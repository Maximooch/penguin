# MCP RunMode Audit

- Created: 2026-05-04
- Branch: `feature-mcp-system`
- Purpose: identify what Penguin can truthfully expose as Phase 2B Slice 3 runtime MCP tools.

## Executive Summary

RunMode should not be exposed as a one-shot `start` tool until Penguin has an
explicit job/status/cancel contract for MCP. The current web surface can start
execution and resume clarification, but it does not provide a durable RunMode job
registry or a clean cancellation/status API for arbitrary runs.

The safe next runtime step is not `penguin_runmode_start_task`. It is a small
capabilities/status surface that reports what can be started, what execution
routes exist, and what lifecycle truth is currently observable.

## Evidence From Current Code

### Web/API Surfaces

- `penguin/web/services/projects.py` contains the current project execution service.
  `start_project_execution(...)` resolves a project, checks tasks/ready tasks, builds
  an `ExecutionContext`, and calls `core.start_run_mode(...)` with `mode_type="project"`.
- `penguin/web/routes.py` exposes `POST /api/v1/projects/{project_identifier}/start`
  through `start_project_execution(...)`.
- `penguin/web/routes.py` exposes `POST /api/v1/tasks/{task_id}/execute`, which:
  - resolves the task,
  - checks that `core.engine` exists,
  - builds an `ExecutionContext`,
  - creates a fresh `RunMode(core=core)`,
  - calls `run_mode.start(...)`,
  - returns `{task_id, result, task}`.
- `penguin/web/routes.py` exposes `POST /api/v1/tasks/{task_id}/clarification/resume`,
  which creates a fresh `RunMode(core=core)` and calls
  `run_mode.resume_with_clarification(...)`.
- `penguin/web/routes.py` still exposes older background/sync execution paths:
  - `POST /api/v1/tasks/execute` uses FastAPI `BackgroundTasks` with no returned job ID.
  - `POST /api/v1/tasks/execute-sync` has separate engine/runmode fallback behavior.

### RunMode Internals

- `penguin/run_mode.py` has `RunMode.start(...)` for single task execution.
- `RunMode.resume_with_clarification(...)` persists the clarification answer, emits
  `clarification_answered`, and immediately resumes execution via `start(...)`.
- Continuous mode uses `_shutdown_requested` internally and checks `core._interrupted`,
  but there is no obvious public `cancel(job_id)` API.
- RunMode emits status events, but there is no dedicated durable MCP/job registry that
  can be queried by an external MCP host after a start call returns or while it runs.
- The current task/project web routes are richer and more current than the older
  programmatic `PenguinAPI` surface, even though `PenguinAPI.run_task(...)` and
  `resume_with_clarification(...)` now route through RunMode.

## What Works Today

These capabilities have current implementation paths and can be tested without inventing
new runtime semantics:

1. Project/task creation and listing through `ProjectManager`.
2. Blueprint lint/graph/status/sync through `ProjectManager.sync_blueprint(...)`.
3. Task execution through web route/service paths, but it is synchronous from the caller's
   perspective and model-dependent.
4. Clarification resume for tasks with an open persisted clarification request.

## What Is Missing For Runtime MCP Tools

Before exposing autonomous runtime controls over MCP, Penguin needs:

1. **Runtime tool opt-in gate**
   - CLI-only initially: `scripts/penguin_mcp_server.py --allow-runtime-tools`.
   - Do not expose runtime start/cancel by default.

2. **Job/status model**
   - A small in-process registry is enough for MVP.
   - It should track `job_id`, `kind`, `project_id`, `task_id`, `status`, `started_at`,
     `finished_at`, `result`, `error`, and latest event/status payload.

3. **Cancellation semantics**
   - Need a real cancellation path, not just a flag nobody checks.
   - Continuous mode checks `_shutdown_requested`; single-task execution likely needs
     task cancellation via the asyncio task/job registry.

4. **Lifecycle-aligned payloads**
   - MCP responses must match web lifecycle truth: status, phase, dependencies,
     artifact evidence, recipe metadata, clarification requests.

5. **Deterministic tests**
   - Runtime execution is model-dependent. Unit tests should use a fake core/runmode or
     a no-op/failing engine path to validate job lifecycle without spending model calls.
   - Product smoke can remain opt-in/manual.

## Recommended Slice 3 Shape

### Slice 3A: Runtime Capabilities And Readiness

Default exposure: only if runtime tools are enabled with CLI flag.

Tools:

- `penguin_runmode_capabilities`
  - Reports supported start modes, required opt-in, whether engine/project manager exist,
    whether job registry is active, and known gaps.
- `penguin_runmode_list_jobs`
  - Lists in-process jobs once a registry exists. Initially returns an empty list with
    registry metadata.
- `penguin_runmode_get_job`
  - Gets one job by ID. Initially useful once `start` exists.

Acceptance criteria:

- Tools are absent unless `--allow-runtime-tools` is set.
- Capabilities tool returns truthful unsupported/missing state rather than optimistic claims.
- No model call required.

### Slice 3B: Runtime Start Behind Opt-In

Tools:

- `penguin_runmode_start_task`
  - Starts project task execution in a background job.
  - Requires `task_id` or `{project_id, task_title}`.
  - Returns `job_id` immediately.
- `penguin_runmode_start_project`
  - Starts project-scoped execution through the same service path as web project start.
  - Requires `project_id` or exact project name.
  - Returns `job_id` immediately.

Acceptance criteria:

- Uses existing web service functions where possible.
- Returns a job record, not a blocking model result.
- Captures final result/error into job registry.

### Slice 3C: Cancel And Resume Clarification

Tools:

- `penguin_runmode_cancel_job`
  - Cancels a registered background job.
- `penguin_runmode_resume_clarification`
  - Routes to the same RunMode clarification path as the web route.
  - Might create a new job or return direct result depending on implementation choice.

Acceptance criteria:

- Cancellation is real for background jobs.
- Clarification resume returns the updated task payload and runtime result.

## Recommendation

Proceed with Slice 2.75 smoke first, then implement Slice 3A only. Do not expose
`start` until a job registry exists and cancellation semantics are explicit.
