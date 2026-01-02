---
# Multi-Agent Parallelization Architecture

## Current State: Implemented Features

### What's Parallel-Ready

| Layer | Status | Implementation |
|-------|--------|----------------|
| **FastAPI** | ✅ Async-native | Each WebSocket connection is independent |
| **Routes** | ✅ Per-agent endpoints | `/api/v1/agents/{id}/*` routes |
| **Coordinator** | ✅ `MultiAgentCoordinator` | Tracks agents by role, delegation support |
| **Health Checks** | ✅ Configurable | `PENGUIN_MAX_CONCURRENT_TASKS` env var (default: 10) |
| **Plugin Loading** | ✅ Parallel | `load_all_plugins(parallel=True)` via ThreadPoolExecutor |
| **Search** | ✅ Concurrent | `asyncio.gather(*search_tasks)` in advanced_search.py |
| **Per-Agent Streaming** | ✅ Implemented | `AgentStreamingStateManager` in stream_handler.py |
| **Connection Pooling** | ✅ Implemented | `ConnectionPoolManager` in api_client.py |
| **Background Execution** | ✅ Implemented | `AgentExecutor` in multi/executor.py |
| **Sub-Agent Tools** | ✅ Implemented | 10 tools in tool_manager.py |
| **Context Sharing** | ✅ Implemented | Shared context methods in conversation_manager.py |

### Multi-Agent Session/Context Features

```python
# Agents can share or isolate sessions
share_session_with: Optional[str]
share_context_window_with: Optional[str]
shared_context_window_max_tokens: Optional[int]

# Coordinator workflows
await coordinator.simple_round_robin_workflow(prompts, role="analyzer")
await coordinator.role_chain_workflow(content, roles=["planner", "implementer", "reviewer"])
await coordinator.delegate_message(parent_agent_id, child_agent_id, content)
```

---

## Implemented Sub-Agent Tools

Sub-agent tools are available via **two interfaces**:

### 1. Action Tags (parser.py)

XML-style action tags parsed from LLM output:

```xml
<spawn_sub_agent>{"id": "worker", "background": true, "initial_prompt": "..."}</spawn_sub_agent>
<delegate>{"child": "worker", "content": "...", "background": true}</delegate>
<stop_sub_agent>{"id": "worker"}</stop_sub_agent>
```

| Action | Location | Features |
|--------|----------|----------|
| `send_message` | parser.py:596 | MessageBus integration |
| `spawn_sub_agent` | parser.py:726 | background execution via AgentExecutor |
| `stop_sub_agent` | parser.py:1039 | cancels background tasks |
| `resume_sub_agent` | parser.py:1076 | resume paused agents |
| `delegate` | parser.py:1077 | background, wait, timeout support |
| `delegate_explore_task` | parser.py:812 | autonomous haiku exploration |

### 2. Function Calls (tool_manager.py)

JSON tool schemas for LLM function calling:

| Tool | Description |
|------|-------------|
| `send_message` | Send messages to other agents via MessageBus |
| `spawn_sub_agent` | Create child agents with isolated/shared context |
| `stop_sub_agent` | Pause/cancel a running sub-agent |
| `resume_sub_agent` | Resume a paused sub-agent |
| `get_agent_status` | Query background agent status (NEW) |
| `wait_for_agents` | Wait for background agents to complete (NEW) |
| `get_context_info` | Get context sharing relationships (NEW) |
| `sync_context` | Synchronize context between agents (NEW) |
| `delegate` | Delegate tasks with background execution |
| `delegate_explore_task` | Autonomous exploration using haiku |

### Tool Schemas (tool_manager.py:1010-1260)

All sub-agent tool schemas are defined in `_define_tool_schemas()` with full input validation.

### Key Parameters

Both interfaces support:
- `background: bool` - Run agent/task in background using AgentExecutor
- `wait: bool` - Wait for background task to complete (delegate only)
- `timeout: float` - Timeout in seconds when waiting

---

## Per-Agent Streaming State

**Status: ✅ IMPLEMENTED**

**Location:** `penguin/llm/stream_handler.py`

```python
class AgentStreamingStateManager:
    """Manages per-agent streaming state for parallel streaming."""
    DEFAULT_AGENT_ID = "default"

    def __init__(self, config: Optional[StreamingConfig] = None):
        self._config = config
        self._managers: Dict[str, StreamingStateManager] = {}

    def get_manager(self, agent_id: Optional[str] = None) -> StreamingStateManager:
        """Get or create streaming state for a specific agent."""
        aid = agent_id or self.DEFAULT_AGENT_ID
        if aid not in self._managers:
            self._managers[aid] = StreamingStateManager(self._config)
        return self._managers[aid]

    def handle_chunk(self, chunk: str, agent_id: Optional[str] = None, ...) -> List[StreamEvent]:
        """Process a chunk for a specific agent."""
        ...

    def is_agent_active(self, agent_id: str) -> bool
    def get_agent_content(self, agent_id: str) -> str
    def get_active_agents(self) -> List[str]
    def cleanup_agent(self, agent_id: str) -> None
```

**Impact:** Multiple agents can stream simultaneously without interference.

---

## Connection Pooling

**Status: ✅ IMPLEMENTED**

**Location:** `penguin/llm/api_client.py`

```python
class ConnectionPoolManager:
    """Singleton HTTP connection pool for efficient parallel LLM calls."""
    _instance: Optional["ConnectionPoolManager"] = None

    @classmethod
    def get_instance(cls, config: Optional[ConnectionPoolConfig] = None) -> "ConnectionPoolManager":
        if cls._instance is None:
            cls._instance = cls(config or ConnectionPoolConfig())
        return cls._instance

    async def get_client(self, base_url: str) -> httpx.AsyncClient
    async def client_context(self, base_url: str)  # Context manager
    async def close_all(self) -> None
```

**Configuration:**
```python
@dataclass
class ConnectionPoolConfig:
    max_keepalive_connections: int = 20  # PENGUIN_MAX_KEEPALIVE_CONNECTIONS
    max_connections: int = 100           # PENGUIN_MAX_CONNECTIONS
    keepalive_expiry: float = 30.0
    connect_timeout: float = 10.0
    read_timeout: float = 120.0
    write_timeout: float = 10.0
```

**Usage in OpenRouter:** `penguin/llm/openrouter_gateway.py:808`
**Usage in OpenAI Adapter:** `penguin/llm/adapters/openai.py:405`
**Shutdown Hook:** `penguin/web/app.py:120` (via FastAPI lifespan)

---

## Background Agent Execution

**Status: ✅ IMPLEMENTED**

**Location:** `penguin/multi/executor.py`

```python
class AgentExecutor:
    """Executes multiple agents in parallel with concurrency control."""

    def __init__(self, core: Any, max_concurrent: Optional[int] = None):
        self._core = core
        self._max_concurrent = max_concurrent or int(
            os.getenv("PENGUIN_MAX_CONCURRENT_TASKS", "10")
        )
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._tasks: Dict[str, AgentTask] = {}

    async def spawn_agent(self, agent_id: str, prompt: str, metadata: Optional[Dict] = None) -> str
    async def spawn_agents(self, agents: List[Tuple[str, str]], metadata: Optional[Dict] = None) -> List[str]
    async def wait_for(self, agent_id: str, timeout: Optional[float] = None) -> Optional[str]
    async def wait_for_all(self, agent_ids: Optional[List[str]] = None, timeout: Optional[float] = None) -> Dict[str, Optional[str]]
    async def cancel(self, agent_id: str) -> bool
    def pause(self, agent_id: str) -> bool
    def resume(self, agent_id: str) -> bool
    def get_status(self, agent_id: str) -> Optional[Dict[str, Any]]
    def get_all_status(self) -> Dict[str, Dict[str, Any]]
    def get_stats(self) -> Dict[str, Any]
```

**Agent States:**
- `PENDING` - Task created but not started
- `RUNNING` - Actively executing
- `PAUSED` - Temporarily stopped
- `COMPLETED` - Successfully finished
- `FAILED` - Encountered error
- `CANCELLED` - Manually stopped

**Global Access:**
```python
from penguin.multi.executor import get_executor, set_executor

executor = get_executor()  # Returns singleton or None
set_executor(AgentExecutor(core))  # Initialize global executor
```

---

## Shared Context Window Management

**Status: ✅ IMPLEMENTED**

**Location:** `penguin/system/conversation_manager.py:1161-1289`

### Context Sharing Methods

```python
def shares_context_window(self, agent_id_1: str, agent_id_2: str) -> bool:
    """Check if two agents share the same context window object."""

def get_context_sharing_info(self, agent_id: str) -> Dict[str, Any]:
    """Get information about an agent's context sharing relationships.

    Returns:
        - has_context_window: Whether agent has a CWM
        - parent: Parent agent ID (if sub-agent)
        - shares_with_parent: Whether shares CWM with parent
        - children: List of child agent IDs
        - shares_with_children: List of children that share CWM
    """

def get_context_window_stats(self, agent_id: str) -> Optional[Dict[str, Any]]:
    """Get token usage statistics for an agent's context window."""

def sync_context_to_child(self, parent_agent_id: str, child_agent_id: str, *, categories: Optional[List[MessageCategory]] = None, replace_existing: bool = False) -> bool:
    """Synchronize context from parent to child agent."""

def get_shared_context_agents(self, agent_id: str) -> List[str]:
    """Get all agents that share the same context window."""
```

### Sub-Agent Creation (conversation_manager.py:323-410)

```python
def create_sub_agent(
    self,
    agent_id: str,
    *,
    parent_agent_id: str,
    share_session: bool = True,
    share_context_window: bool = True,
    shared_context_window_max_tokens: Optional[int] = None,
) -> None:
    """Create a sub-agent with configurable session/context sharing."""
```

**Behavior:**
- `share_context_window=True`: Child points to same CWM object as parent (updates are shared)
- `share_context_window=False`: Child gets own CWM with optionally clamped token limit
- `share_session=True`: Child uses parent's conversation history
- `share_session=False`: Child starts fresh, copies SYSTEM/CONTEXT messages

---

## Configuration

### Environment Variables

```bash
# Concurrency limits
PENGUIN_MAX_CONCURRENT_TASKS=10          # Max parallel agent executions
PENGUIN_MAX_KEEPALIVE_CONNECTIONS=20     # HTTP keepalive connections
PENGUIN_MAX_CONNECTIONS=100              # Total HTTP connections

# Background execution
PENGUIN_USE_BACKGROUND_AGENTS=true       # Enable background agent execution
```

---

## Future Enhancements (Not Yet Implemented)

### Rate Limiting Layer

**Goal:** Prevent hitting provider rate limits.

```python
# penguin/llm/rate_limiter.py (future)
class ProviderRateLimiter:
    def __init__(self):
        self._semaphores: Dict[str, Semaphore] = defaultdict(lambda: Semaphore(10))
        self._request_counts: Dict[str, int] = defaultdict(int)
        self._token_buckets: Dict[str, TokenBucket] = {}

    @asynccontextmanager
    async def limit(self, provider: str):
        await self.acquire(provider)
        try:
            yield
        finally:
            self.release(provider)
```

### Copy-on-Write Context Windows

**Goal:** More efficient context sharing for read-heavy workloads.

```python
class SharedContextWindow:
    """Copy-on-write context windows (future optimization)."""
    def __init__(self, max_tokens: int):
        self._base_messages: List[Message] = []
        self._agent_deltas: Dict[str, List[Message]] = {}
        self._lock = asyncio.Lock()

    async def get_messages(self, agent_id: str) -> List[Message]:
        base = self._base_messages.copy()
        delta = self._agent_deltas.get(agent_id, [])
        return base + delta
```

### Distributed Execution

For massive scale, consider:
- **Celery + Redis** - Distributed, persistent queues
- **ARQ** - Async Redis queue, lighter than Celery

---

## Testing Strategy

### Load Testing

```python
# tests/load/test_parallel_agents.py
import asyncio
import pytest

@pytest.mark.asyncio
async def test_10_concurrent_agents():
    """Verify 10 agents can run simultaneously."""
    from penguin.multi.executor import AgentExecutor

    executor = AgentExecutor(mock_core, max_concurrent=10)
    agents = [(f"agent-{i}", "Hello, world!") for i in range(10)]

    agent_ids = await executor.spawn_agents(agents)
    results = await executor.wait_for_all()

    assert len(results) == 10
    assert all(r is not None for r in results.values())
```

### Metrics to Track

- Concurrent agent count (gauge)
- Request latency per agent (histogram)
- Queue depth (gauge)
- Stream lock contention time (histogram)

---

## Migration Path

1. **v1.0** - Single-threaded streaming, shared state (LEGACY)
2. **v1.1** - Per-agent streaming state ✅ IMPLEMENTED
3. **v1.2** - Connection pooling ✅ IMPLEMENTED
4. **v1.3** - Sub-agent tools ✅ IMPLEMENTED
5. **v1.4** - Background agent execution ✅ IMPLEMENTED
6. **v1.5** - Shared context window management ✅ IMPLEMENTED
7. **v2.0** - Rate limiting layer (FUTURE)
8. **v2.1** - Distributed execution (FUTURE, for massive scale)

---

## File Reference Summary

| Feature | Primary File | Key Class/Function |
|---------|-------------|-------------------|
| Per-Agent Streaming | `llm/stream_handler.py` | `AgentStreamingStateManager` |
| Connection Pooling | `llm/api_client.py` | `ConnectionPoolManager` |
| Background Execution | `multi/executor.py` | `AgentExecutor` |
| Sub-Agent Tools (Actions) | `utils/parser.py` | `ActionExecutor._spawn_sub_agent`, etc. |
| Sub-Agent Tools (Function Calls) | `tools/tool_manager.py` | `_execute_spawn_sub_agent`, etc. |
| Context Sharing | `system/conversation_manager.py` | `create_sub_agent`, `shares_context_window` |
| MessageBus | `system/message_bus.py` | `MessageBus`, `ProtocolMessage` |

---

## References

- [FastAPI Concurrency](https://fastapi.tiangolo.com/async/)
- [asyncio TaskGroup](https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup)
- [httpx Connection Pooling](https://www.python-httpx.org/advanced/#pool-limit-configuration)
- [ARQ - Async Redis Queue](https://arq-docs.helpmanual.io/)
