# MCP Runtime Job Records Contract

## Status

- Created: 2026-05-04
- Scope: Slice 5B durable runtime job records for Penguin's MCP runtime server
- State: implemented locally in Slice 5B

## Purpose

Slice 3 introduced RunMode MCP tools that can start, list, inspect, cancel, and resume runtime jobs. Today those records are in-memory only.

That is acceptable for live testing, but not enough for serious orchestration. If the MCP server process restarts, an external host loses job IDs, results, cancellation state, and status history.

Slice 5B persists runtime job records in local ProjectStorage and merges them with the live in-process registry exposed by RunMode MCP tools.

## Storage Decision

For local Penguin, runtime job records should live in the project persistence layer, not a sidecar JSON file or unrelated SQLite DB.

Current local ProjectManager initializes storage at:

```text
<workspace>/projects.db
```

So local runtime job records should persist in that DB through `ProjectStorage` / `ProjectManager` facade methods.

For Link/cloud, this same domain model should map to Link's database rather than local SQLite. The key requirement is the model contract, not SQLite itself.

## Non-Goals

Slice 5B should not attempt to solve:

- distributed worker coordination
- cloud multi-tenant auth
- resumable Python thread execution after process death
- full raw transcript/artifact storage
- long-term analytics

It should persist enough truth for external hosts to recover job history and reconcile current project/task state.

## Record Schema

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `job_id` | string | yes | Stable primary ID returned to MCP callers |
| `kind` | string | yes | `task`, `project`, `clarification_resume`, future kinds |
| `status` | string | yes | Lifecycle status; see below |
| `project_id` | string/null | no | Associated project |
| `task_id` | string/null | no | Associated task |
| `session_id` | string/null | no | Associated Penguin conversation/session if known |
| `started_at` | ISO timestamp | yes | UTC preferred |
| `updated_at` | ISO timestamp | yes | Every status change updates this |
| `finished_at` | ISO timestamp/null | no | Terminal jobs only |
| `cancel_requested` | boolean | yes | Operator requested cancellation |
| `cancel_reason` | string/null | no | Human/MCP-supplied reason |
| `result_summary` | string/null | no | Compact summary suitable for list views |
| `result_json` | JSON string/null | no | Capped structured result when safe/serializable |
| `error` | string/null | no | Failure detail, size-capped |
| `metadata_json` | JSON string | yes | Extensible metadata |

Recommended SQLite table name:

```sql
runtime_jobs
```

Recommended primary key:

```sql
job_id TEXT PRIMARY KEY
```

## Status Values

Initial status enum:

- `pending`
- `running`
- `waiting_input`
- `completed`
- `failed`
- `cancel_requested`
- `cancelled`

Guidance:

- `cancel_requested` means a cooperative cancellation signal was sent but the underlying job has not yet stopped.
- `cancelled` means the job ended due to cancellation.
- `waiting_input` should preserve clarification metadata when available.
- Terminal statuses are `completed`, `failed`, and `cancelled`.

## Result Storage Policy

Do not blindly persist massive raw model responses or arbitrary Python reprs.

Recommended policy:

1. Always persist `result_summary` when a job reaches a terminal or waiting state.
2. Persist `result_json` only when:
   - JSON-serializable
   - under a configured size cap
   - not obviously binary/blob content
3. If result is too large:
   - store a truncated summary
   - store metadata indicating truncation
   - leave full artifacts to future artifact/evidence storage
4. Store `error` with a size cap.

Suggested caps:

- `result_summary`: 4 KB
- `result_json`: 64 KB initially
- `error`: 16 KB

These are product defaults, not hard protocol limits.

## Relationship To Project/Task State

Runtime job records should not replace task state.

Examples:

- A job completes and marks a task `pending_review`; the task status/phase persists separately.
- A job fails; the job record stores failure details, while task state may remain active/running/failed depending on RunMode/PM semantics.
- A job is cancelled; cancellation intent persists in the job record, while the task may need a separate status/phase update.

External clients should use both:

- runtime job record for execution attempt truth
- task/project payload for durable work item state

## ProjectManager Facade

Add ProjectManager methods rather than making MCP tools talk to storage directly:

```python
create_runtime_job(...)
update_runtime_job(...)
get_runtime_job(job_id)
list_runtime_jobs(project_id=None, task_id=None, status=None, limit=50)
request_runtime_job_cancel(job_id, reason=None)
```

The MCP RunMode registry can keep live thread handles in memory, but persistence should flow through these facade methods.

## MCP Tool Implications

Existing Slice 3 tools should be backed by durable records:

- `penguin_runmode_start_task`
- `penguin_runmode_start_project`
- `penguin_runmode_list_jobs`
- `penguin_runmode_get_job`
- `penguin_runmode_cancel_job`
- `penguin_runmode_resume_clarification`

Add or align Slice 5 tools:

- `penguin_runtime_jobs_list`
- `penguin_runtime_job_get`

Implementation choice:

- Either alias these to the RunMode tools,
- or keep RunMode tools as live-control and runtime tools as durable historical query.

Preferred: keep one shared underlying ProjectManager-backed store and expose both views consistently.

## Recovery Semantics

After MCP server restart:

- completed/failed/cancelled jobs should still be listable.
- running jobs from the old process should not be reported as definitely running.
- stale non-terminal records should be marked or surfaced as `unknown_after_restart` / `failed` / `orphaned` depending on final policy.

Recommended first policy:

- On startup, detect non-terminal jobs older than process start without a live in-memory handle.
- Surface them as `orphaned` in metadata while preserving original status.
- Do not pretend they are still controllable.

## Cloud / Link Mapping

In Link/cloud, these records likely map to a real jobs table keyed by tenant/user/project. Additional cloud fields may include:

- `tenant_id`
- `user_id`
- `worker_id`
- `queue_id`
- `lease_expires_at`
- `event_stream_id`

Local Penguin should not implement that complexity now, but the local schema should not block it.

## Acceptance Criteria For Slice 5B

- Runtime job records persist in the project DB.
- Starting a RunMode MCP job creates a durable record.
- Completion/failure/cancel updates the durable record.
- `list_jobs` merges durable records with live in-memory handles.
- After MCP server restart, terminal job records remain queryable.
- Non-terminal orphaned jobs are clearly labeled, not silently shown as controllable.
- Tests cover create/update/list/get and restart-style recovery.
