# Project Management API Reference (v0.1.x)

Penguin's project subsystem manages projects and tasks with a SQLite backend and increasingly explicit lifecycle semantics. Recent work has hardened task status/phase integrity, dependency policy handling, clarification pause/resume flow, and richer web/API surface truth.

---

## Quick-start
```python
from penguin.project import ProjectManager, TaskStatus

pm = ProjectManager()

# create project
proj = pm.create_project(name="My Project", description="Demo")
print(proj.id)

# create a task
task = pm.create_task(project_id=proj.id, title="Initial research")

# update status
pm.update_task_status(task.id, TaskStatus.ACTIVE)
pm.update_task_status(task.id, TaskStatus.COMPLETED)

# list tasks
for t in pm.list_tasks(project_id=proj.id):
    print(t.title, t.status)
```

---

## Public classes & enums

| Object | Purpose |
|--------|---------|
| `ProjectManager` | Synchronous helper class for projects & tasks |
| `AsyncProjectManager` | Async counterpart (method names mirror sync version) |
| `TaskStatus` | Lifecycle enum including `ACTIVE`, `RUNNING`, `PENDING_REVIEW`, `COMPLETED`, `FAILED`, and related task states |

**Note:** The current build now also includes explicit `TaskPhase`, typed dependency policies, artifact evidence semantics, and clarification metadata in task records. The surface is still evolving, but it is no longer just a thin status-only task tracker.

---

## ProjectManager API (sync)

| Method | Description |
|--------|-------------|
| `create_project(name, description="") -> Project` | Insert new project |
| `list_projects(status: str | None = None) -> list[Project]` | Fetch projects (filter by status optional) |
| `get_project_async(id)` *(internal)* | Used by CLI; callable via `await` pattern |
| `delete_project(project_id) -> bool` | Remove project (fails if tasks exist) |
| `create_task(project_id, title, description="", parent_task_id=None, priority=1) -> Task` | Add task to project |
| `list_tasks(project_id: str | None = None, status: TaskStatus | None = None) -> list[Task]` | Enumerate tasks |
| `update_task_status(task_id, status: TaskStatus) -> bool` | Change status with lifecycle validation |
| `update_task_phase(task_id, phase: TaskPhase) -> bool` | Persist ITUV/task phase changes |
| `delete_task(task_id) -> bool` | Remove task |

Async equivalents (
`AsyncProjectManager`) expose identical signatures but return awaitables.

---

## Data objects (lightweight)
Projects and tasks are simple `dataclass`-like records with attributes you can read (`id`, `name`, `description`, `status`, `phase`, dependency fields, metadata`, etc.). They are created by the manager; direct instantiation is **not** guaranteed stable.

---

## Limitations & future work
Current implementation still has important limitations, but the old "no dependency management / graphs" statement is no longer true.

What now exists:
* dependency graphs / DAG readiness evaluation
* typed dependency policies such as `completion_required`, `review_ready_ok`, and `artifact_ready`
* task phase persistence (`TaskPhase`)
* clarification metadata persistence and resume hooks

What is still incomplete or under active hardening:
* broader surface alignment across CLI, web, and library layers
* scheduler-aware waiting semantics for clarification-paused tasks
* larger public docs refresh beyond the current targeted updates
* formal verification work, which is later-stage rather than current v1 scope

---

*Last updated: July 30 2025*

---

## Web/API Surface Notes

The web layer now exposes richer task truth than earlier project API docs implied.

Current task payloads exposed by the web routes include:

- `status`
- `phase`
- `dependencies`
- `dependency_specs`
- `artifact_evidence`
- `recipe`
- `metadata`
- `clarification_requests`

Important route behaviors:

- `POST /api/v1/tasks/{task_id}/execute`
  - now routes through `RunMode` so non-terminal outcomes like `waiting_input` survive to clients
- `POST /api/v1/tasks/{task_id}/clarification/resume`
  - answers the latest open clarification request and resumes execution through the same runtime path
- `GET /api/v1/events/sse`
  - now includes clarification-related session status visibility for web clients

These surface changes matter because a task route that hides clarification, phase, or dependency truth is still a broken project-management interface.
