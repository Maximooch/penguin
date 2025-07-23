# Python API Reference

Penguin provides a comprehensive Python API for programmatic access to all functionality. This reference covers the main classes and methods available for developers.

## Quick Start

```python
from penguin import PenguinClient, create_client, PenguinCore

# Recommended: High-level client usage
async with create_client() as client:
    response = await client.chat("Help me write a Python function")
    print(response)

# Alternative: Manual client management
client = PenguinClient()
await client.initialize()
try:
    response = await client.chat("Hello!")
finally:
    await client.close()
```

## PenguinClient

The high-level Python client providing easy access to all Penguin functionality.

### Initialization

```python
from penguin import PenguinClient, create_client

# Create client with default settings
client = PenguinClient()
await client.initialize()

# Create client with custom settings
client = PenguinClient(
    model="anthropic/claude-3-sonnet-20240229",
    provider="anthropic",
    workspace_path="/custom/workspace"
)
await client.initialize()

# Convenience function (recommended)
client = await create_client(
    model="gpt-4",
    provider="openai"
)
```

### Chat and Conversation Methods

#### `chat(message, options=None)`

Send a chat message and get response.

```python
from penguin import ChatOptions

# Basic chat
response = await client.chat("What is Python?")

# Chat with options
options = ChatOptions(
    conversation_id="conv_123",
    context={"project": "web_app"},
    context_files=["src/main.py", "README.md"],
    image_path="/path/to/screenshot.png",
    max_iterations=10
)
response = await client.chat("Analyze this code", options)
```

#### `stream_chat(message, options=None)`

Stream chat response token by token.

```python
async for token in client.stream_chat("Write a Python function"):
    print(token, end="", flush=True)
```

#### Conversation Management

```python
# List conversations
conversations = await client.list_conversations()

# Get specific conversation
conv = await client.get_conversation("conv_123")

# Create new conversation
conv_id = await client.create_conversation()
```

### Checkpoint Management

Penguin supports conversation checkpointing for branching and rollback functionality.

```python
# Create checkpoint
checkpoint_id = await client.create_checkpoint(
    name="Before refactoring",
    description="Checkpoint before starting code refactoring"
)

# List checkpoints
checkpoints = await client.list_checkpoints(limit=20)
for checkpoint in checkpoints:
    print(f"{checkpoint.name}: {checkpoint.created_at}")

# Rollback to checkpoint
success = await client.rollback_to_checkpoint(checkpoint_id)

# Create branch from checkpoint
branch_id = await client.branch_from_checkpoint(
    checkpoint_id,
    name="Alternative approach",
    description="Exploring different solution"
)

# Clean up old checkpoints
cleaned_count = await client.cleanup_checkpoints()
print(f"Cleaned {cleaned_count} old checkpoints")
```

### Model Management

Switch between different models at runtime.

```python
# List available models
models = await client.list_models()
for model in models:
    print(f"{model.name} ({'current' if model.current else 'available'})")

# Switch to different model
success = await client.switch_model("gpt-4")

# Get current model info
current = await client.get_current_model()
if current:
    print(f"Using {current.name} with vision: {current.vision_enabled}")
```

### Task Execution

Execute tasks using Penguin's autonomous capabilities.

```python
from penguin import TaskOptions

# Execute task with options
options = TaskOptions(
    name="Create web scraper",
    description="Build a web scraper for news articles",
    continuous=False,
    time_limit=600,
    context={"target_site": "example.com"}
)

result = await client.execute_task(
    "Create a web scraper for news articles",
    options
)

print(f"Task completed in {result['execution_time']} seconds")
print(f"Response: {result['response']}")
```

### System Diagnostics

Monitor system status and get information.

```python
# Get system information
info = await client.get_system_info()
print(f"Penguin v{info['penguin_version']}")
print(f"Engine available: {info['engine_available']}")
print(f"Checkpoints enabled: {info['checkpoints_enabled']}")

# Get current status
status = await client.get_system_status()
print(f"Status: {status['status']}")
print(f"Token usage: {status['token_usage']}")

# Get checkpoint statistics
stats = await client.get_checkpoint_stats()
print(f"Total checkpoints: {stats['total_checkpoints']}")
```

### File and Context Management

```python
# Load context files
success = await client.load_context_files([
    "src/main.py",
    "docs/api.md",
    "requirements.txt"
])

# List available context files
files = await client.list_context_files()
```

## Data Classes and Types

### ChatOptions

Options for chat interactions.

```python
from penguin import ChatOptions

options = ChatOptions(
    conversation_id="conv_123",           # Optional conversation ID
    context={"key": "value"},             # Optional context data
    context_files=["file1.py"],          # Optional context files
    streaming=True,                       # Enable streaming
    max_iterations=5,                     # Max processing iterations
    image_path="/path/to/image.png"       # Optional image for vision models
)
```

### TaskOptions

Options for task execution.

```python
from penguin import TaskOptions

options = TaskOptions(
    name="Task name",                     # Optional task name
    description="Task description",       # Optional description
    continuous=False,                     # Continuous execution mode
    time_limit=600,                       # Time limit in seconds
    context={"key": "value"}              # Optional context data
)
```

### CheckpointInfo

Information about a checkpoint.

```python
checkpoint = CheckpointInfo(
    id="ckpt_123",                        # Checkpoint ID
    name="Before refactoring",            # Optional name
    description="Checkpoint description", # Optional description
    created_at="2024-01-01T10:00:00Z",   # Creation timestamp
    type="manual",                        # Checkpoint type
    session_id="session_123"              # Associated session ID
)
```

### ModelInfo

Information about a model.

```python
model = ModelInfo(
    id="claude-3-sonnet",                 # Model ID
    name="anthropic/claude-3-sonnet-20240229", # Full model name
    provider="anthropic",                 # Provider name
    vision_enabled=True,                  # Vision capability
    max_tokens=4000,                      # Token limit
    current=True                          # Whether currently active
)
```

This comprehensive Python API provides full programmatic access to all Penguin functionality with clean, type-safe interfaces and proper resource management.

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

*Last updated: July 22nd 2025* 