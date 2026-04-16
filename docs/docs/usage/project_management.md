# Project Management

Penguin v0.6.x introduces a powerful SQLite-backed project management system that provides robust task tracking, hierarchical organization, and integration with the AI assistant workflow. This guide covers all aspects of managing projects and tasks in Penguin.

## Overview

The project management system offers:

- **SQLite-backed storage** with ACID transactions for reliability
- **Hierarchical task organization** with dependencies and subtasks
- **Real-time status tracking** with automatic checkpointing
- **Resource constraints** for budget and time management
- **EventBus integration** for real-time updates across CLI and web interfaces
- **CLI, web/API, and Python surfaces** for interacting with the same underlying project/task runtime

## Core Concepts

### Projects
A project is a high-level container for related work with:
- **Name and description** for identification
- **Workspace path** for file organization  
- **Creation and modification timestamps**
- **Associated tasks** and their relationships
- **Overall status** derived from task completion

### Tasks
Tasks are individual work items with:
- **Hierarchical structure** (parent/child relationships)
- **Status tracking** (`active`, `running`, `pending_review`, `completed`, `failed`, `cancelled`, `archived`) plus separate task phases
- **Dependencies** between tasks
- **Resource constraints** (token budgets, time limits)
- **Execution records** with detailed logs
- **Agent assignment** for automated execution

### Dependencies
Tasks can depend on other tasks with:
- **Completion-required dependencies** - the default scheduling gate
- **Typed dependency policies** - Blueprint-driven dependency specs can express stricter semantics such as `artifact_ready`
- **Structured Blueprint diagnostics** - missing dependencies, duplicate IDs, missing acceptance criteria, and cycles are now surfaced explicitly during Blueprint parse/lint flows

## CLI Usage (Current Public Surface)

### Implemented Commands

#### Project
```bash
# Create a project
penguin-cli project create "My Project" [--description/-d TEXT]

# List projects
penguin-cli project list

# Delete a project
penguin-cli project delete <PROJECT_ID> [--force/-f]
```

#### Task (within a project)
```bash
# Create a task
penguin-cli project task create <PROJECT_ID> "Task title" [--description/-d TEXT]

# List tasks
penguin-cli project task list [<PROJECT_ID>] [--status/-s STATUS]

# Start / approve / delete
penguin-cli project task start <TASK_ID>      # moves task into the active state
penguin-cli project task complete <TASK_ID>   # approves a task that is pending review
penguin-cli project task delete <TASK_ID> [--force/-f]
```

Task status filters are case-insensitive and follow the current lifecycle values (`active`, `running`, `pending_review`, `completed`, `cancelled`, `failed`, `archived`).

> ⚠️ The above are the **only** task-related CLI commands that exist today. Everything else in earlier docs (update, show, pause, graphs, bulk ops, etc.) is **planned** or internal and should not be treated as a stable public CLI command.

---


### Blueprint / orchestration notes

Blueprint parsing, dependency DAG construction, diagnostics, recipes, and ITUV orchestration exist in the backend/runtime, but they are **not all exposed as stable first-class CLI commands yet**.

Current truth:
- Blueprint import/sync and dependency-policy support are runtime/backend capabilities.
- Structured diagnostics exist for duplicate task IDs, missing dependencies, cycles, missing acceptance criteria, and related authoring issues.
- Public CLI exposure is intentionally narrower than the backend capability set.

Treat older examples of `/blueprint`, `/task graph`, or `/workflow ...` commands as design/history material unless they are explicitly listed in the implemented CLI section above.

## Python API

### Basic Project Management
```python
from pathlib import Path

from penguin.project.manager import ProjectManager
from penguin.project.models import TaskStatus

workspace = Path("./penguin-workspace")
pm = ProjectManager(workspace)

project = pm.create_project(
    name="Web Application",
    description="Full-stack web app",
)

task = pm.create_task(
    title="Setup FastAPI backend",
    description="Initialize FastAPI project with basic structure",
    project_id=project.id,
    dependencies=[],
    acceptance_criteria=["Backend scaffold exists"],
)

projects = pm.list_projects()
tasks = pm.list_tasks(project_id=project.id)
pm.update_task_status(task.id, TaskStatus.ACTIVE)
```

### Notes on current Python surface truth
- `ProjectManager` is the real project/task entry point documented today.
- Project workspaces are managed under the manager workspace root; `create_project(...)` does **not** currently accept a separate `workspace=` keyword.
- There is no public `AsyncProjectManager`, `TaskManager`, or `AgentMatcher` API shipped today.
- Dependency-policy semantics, Blueprint diagnostics, recipes, and clarification-aware task execution exist in the runtime/backend, but the broader Python embedding surface still needs its own dedicated refresh pass.

## Web/API Interface

Penguin's web surface is available through `penguin-web` and is no longer a “coming soon” concept.

Current web/API behavior includes:

- REST endpoints for project/task access
- richer task payloads that expose lifecycle truth such as:
  - `status`
  - `phase`
  - dependency fields
  - artifact evidence
  - clarification metadata
- `POST /api/v1/tasks/{task_id}/execute`
  - routes through `RunMode` so non-terminal outcomes like `waiting_input` survive to clients
- `POST /api/v1/tasks/{task_id}/clarification/resume`
  - answers the latest open clarification request and resumes task execution
- `GET /api/v1/events/sse`
  - exposes OpenCode-compatible SSE and now includes clarification-related session status visibility

The web/API surface is still being audited, but it now reflects current runtime truth much more closely than older docs implied.

## Advanced Features

### Clarification-aware task execution
```python
from penguin.web.app import PenguinAPI

api = PenguinAPI()
result = await api.run_task("Implement auth flow")

if result.get("status") == "waiting_input":
    resumed = await api.resume_with_clarification(
        task_id=result["task_id"],
        answer="Use rotating refresh tokens",
        answered_by="human",
    )
```

This Python embedding surface is usable, but it still has a dedicated follow-up plan because it has not received the same depth of audit/ergonomics cleanup as the CLI and web/API surfaces.

### Additional notes
Project templates, richer event-driven integrations, and other higher-level orchestration surfaces remain active design/runtime territory. Prefer the explicit CLI and web/API surfaces documented above when you need current public behavior.

## Database Schema

The project/task storage layer is SQLite-backed, but the exact schema is an implementation detail and may evolve. Prefer the Python and CLI/web surfaces documented above over relying on copied table layouts from older docs.

## Performance and Scaling

Operational tuning details are still evolving. Treat older examples of WAL toggles, template loaders, or higher-level orchestration helpers as implementation notes rather than stable public APIs unless they are explicitly documented in the current CLI/web/Python sections above.


## Workspace Semantics

- `--workspace` uses the **exact provided path**. Penguin does not silently create a child directory under that path.
- When `--workspace` is omitted, Penguin uses its managed default workspace path.
- Project creation output now distinguishes:
  - `Workspace (explicit): ...`
  - `Workspace (default): ...`
  - `Execution root: ...`

This separation is intentional: the execution root and the stored project workspace are related concepts, but they are not the same thing.
