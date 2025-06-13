# Penguin Python API Reference (v0.1.x)

This page documents the **public APIs that ship today**. Anything not listed here is work-in-progress and tracked in the [future considerations](../advanced/future_considerations.md) roadmap.

---

## Installation
```bash
pip install penguin-ai   # CLI + library
```

---

## Quick-start
```python
from penguin.agent import PenguinAgent

agent = PenguinAgent()
print(agent.chat("Hello Penguin!"))
```

---

## Available Modules & Classes

| Import path | Status | Notes |
|-------------|--------|-------|
| `penguin.agent.PenguinAgent` | ✅ | Sync chat/stream/run_task wrapper |
| `penguin.agent.PenguinAgentAsync` | ✅ | Async counterpart |
| `penguin.project.manager.ProjectManager` | ✅ | SQLite-backed project + task CRUD |
| `penguin.core.PenguinCore` | ✅ | Low-level orchestrator |
| `penguin.tools.ToolManager` | ✅ | Runtime tool registry |

Everything else you may have seen in earlier drafts (memory providers, batch processors, plugin system, etc.) is **not implemented yet**.

---

## PenguinAgent API

```python
from penguin.agent import PenguinAgent
agent = PenguinAgent()
```

| Method | Description |
|--------|-------------|
| `chat(message: str, *, context: dict | None = None) -> str` | One-shot chat |
| `stream(message: str, *, context: dict | None = None) -> Iterator[str]` | Streaming generator |
| `run_task(prompt: str, *, max_iterations: int = 5) -> dict` | Multi-step task execution |
| `new_conversation() -> str` | Start new session |
| `load_conversation(session_id: str) -> bool` | Load previous session |

Example:
```python
sid = agent.new_conversation()
resp = agent.chat("Explain asyncio", context={"conversation_id": sid})
```

### PenguinAgentAsync
Same surface as `PenguinAgent`, but `async`/`await`.

---

## ProjectManager (sync)
```python
from penguin.project import ProjectManager, TaskStatus

pm = ProjectManager()
proj = pm.create_project("Demo")
task = pm.create_task(project_id=proj.id, title="Research")
pm.update_task_status(task.id, TaskStatus.COMPLETED)
```
Implemented helpers: `create_project`, `list_projects`, `delete_project`, `create_task`, `list_tasks`, `update_task_status`, `delete_task`.

---

## PenguinCore (advanced)
```python
from penguin.core import PenguinCore
core = await PenguinCore.create(enable_cli=False)
res = await core.process("Summarise repository")
print(res["assistant_response"])
```
Stable public methods: `process`, `start_run_mode`.

---

## ToolManager
```python
from penguin.tools import ToolManager
mgr = ToolManager()
print([t.name for t in mgr.list_tools()])
```
Register custom tool:
```python
@mgr.register("echo")
def echo(**kwargs):
    return kwargs
```

---

## Deprecated / Future APIs
`BatchProcessor`, `PerformanceMonitor`, `ErrorRecovery`, plugin system, advanced memory providers, and `AgentBuilder` are **planned** but not yet available.

See the Python API roadmap in [future considerations](../advanced/future_considerations.md).

---

*Last updated: June 13 2025* 