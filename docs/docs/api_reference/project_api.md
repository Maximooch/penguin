# Project Management API Reference (v0.1.x)

Penguin's project subsystem is under active development.  The current release ships **minimal but functional** CRUD helpers backed by SQLite.  Anything not mentioned here (advanced dependency graphs, event bus, async streaming, etc.) is planned—see the roadmap in [future considerations](../advanced/future_considerations.md).

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
| `TaskStatus` | Enum: `PENDING`, `ACTIVE`, `COMPLETED`, `FAILED` |

**Note:** Separate `TaskManager`, `ResourceConstraints`, complex models, etc. are **not** part of the current build.

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
| `update_task_status(task_id, status: TaskStatus) -> bool` | Change status |
| `delete_task(task_id) -> bool` | Remove task |

Async equivalents (
`AsyncProjectManager`) expose identical signatures but return awaitables.

---

## Data objects (lightweight)
Projects and tasks are simple `dataclass`-like records with attributes you can read (
`id`, `name`, `description`, `status`, etc.). They are created by the manager; direct instantiation is **not** guaranteed stable.

---

## Limitations & future work
Current implementation **does not** support:
* Hierarchical subtasks beyond parent_task_id linkage
* Dependency management / graphs
* Bulk operations
* EventBus or real-time updates
* Resource constraints or execution records

These items are tracked in the roadmap.

---

*Last updated: June 13 2025* 