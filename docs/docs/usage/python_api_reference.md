# Penguin Python API Reference (v0.1.x)

This page documents the **public APIs that ship today**.  Anything not listed here is work-in-progress and tracked in the [future considerations](../advanced/future_considerations.md) roadmap.

---

## Installation
```bash
pip install penguin-ai   # includes CLI and Python package
```

---

## Quick-start
```python
from penguin.agent import PenguinAgent

agent = PenguinAgent()
print(agent.chat("Hello Penguin!"))
```

---

## Modules & Classes

| Import path | Exists? | Notes |
|-------------|---------|-------|
| `penguin.agent.PenguinAgent` | ✅ | Synchronous wrapper around `PenguinCore` – chat, stream, run_task |
| `penguin.agent.PenguinAgentAsync` | ✅ | Async variant with identical method names (returning coroutines) |
| `penguin.project.manager.ProjectManager` | ✅ | SQLite-backed project CRUD and basic task helpers |
| `penguin.core.PenguinCore` | ✅ | Low-level orchestrator (conversation, tools, run-mode) |
| `penguin.tools.ToolManager` | ✅ | Runtime registry & execution of tools |

Anything else you may have seen in earlier drafts (Memory providers, BatchProcessor, PerformanceMonitor, custom plugin framework, etc.) has **not** landed yet.

---

## PenguinAgent

```python
from penguin.agent import PenguinAgent

agent = PenguinAgent()
```

### Methods
| Method | Description |
|--------|-------------|
| `chat(message: str, *, context: dict | None = None) -> str` | Single turn – returns assistant reply. |
| `stream(message: str, *, context: dict | None = None) -> Iterator[str]` | Yields chunks of the assistant reply. |
| `run_task(prompt: str, *, max_iterations: int = 5) -> dict` | Multi-step reasoning/action loop using core.run_mode. |
| `new_conversation() -> str` | Start fresh conversation, returns session id. |
| `load_conversation(session_id: str) -> bool` | Load a saved session into memory. |

> All other attributes or methods are considered **internal** and may change without notice.

#### Example
```python
conv = agent.new_conversation()
agent.chat("Explain asyncio in Python", context={"conversation_id": conv})
```

---

## PenguinAgentAsync

```python
from penguin.agent import PenguinAgentAsync
agent = await PenguinAgentAsync.create()
```
* Same public surface as `PenguinAgent`, but every method is `async` and returns an awaitable.

---

## ProjectManager
Basic project / task operations.  All methods are **sync and async** twins (`ProjectManager` / `AsyncProjectManager`).

```python
from penguin.project import ProjectManager, TaskStatus

pm = ProjectManager()
project = pm.create_project(name="Demo", description="Example project")
print("Project id:", project.id)

# Tasks
task = pm.create_task(project_id=project.id, title="Initial research")
pm.update_task_status(task.id, TaskStatus.ACTIVE)
pm.update_task_status(task.id, TaskStatus.COMPLETED)
```

Implemented high-level methods:
* `create_project(name, description="")`
* `list_projects(status: str | None = None)`
* `delete_project(project_id)`
* `create_task(project_id, title, description="", parent_task_id=None, priority=1)`
* `list_tasks(project_id: str | None = None, status: TaskStatus | None = None)`
* `update_task_status(task_id, status: TaskStatus)`
* `delete_task(task_id)`

Anything else (dependency graphs, bulk updates, Gantt charts, etc.) is future work.

---

## PenguinCore (advanced)
For power-users that need direct access to the orchestration layer.

```python
from penguin.core import PenguinCore
core = await PenguinCore.create(enable_cli=False)
resp = await core.process("Summarise this repository in 3 points")
print(resp["assistant_response"])
```

Key async methods you can rely on:
* `process(input_data, *, streaming=False, stream_callback=None)`
* `start_run_mode(name, description=None, continuous=False, time_limit=None)`

The rest of `PenguinCore` is internal and subject to change.

---

## ToolManager

```python
from penguin.tools import ToolManager

manager = ToolManager()
print([t.name for t in manager.list_tools()])
```

You can register custom tools via the decorator:
```python
@manager.register("my_tool")
def my_tool(**kwargs):
    return {"echo": kwargs}
```

---

## Deprecated / Future APIs
The following names appeared in earlier documentation but **do not exist in v0.1.x**.  They are tracked on the roadmap and should not be imported yet:

* `BatchProcessor`
* `PerformanceMonitor`
* `ErrorRecovery`
* `Plugin` / `plugin_hook`
* `MemoryProvider` subclasses beyond default SQLite provider
* `AgentBuilder`

See the "Python API Roadmap" section in [future considerations](../advanced/future_considerations.md) for planned timelines.

---

*Last updated: June 13th 2025* 