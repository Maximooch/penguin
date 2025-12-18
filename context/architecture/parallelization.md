# Multi-Agent Parallelization Architecture

## Current State

### What's Already Parallel-Ready

| Layer | Status | Implementation |
|-------|--------|----------------|
| **FastAPI** | ✅ Async-native | Each WebSocket connection is independent |
| **Routes** | ✅ Per-agent endpoints | `/api/v1/agents/{id}/*` routes |
| **Coordinator** | ✅ `MultiAgentCoordinator` | Tracks agents by role, delegation support |
| **Health Checks** | ✅ Configurable | `PENGUIN_MAX_CONCURRENT_TASKS` env var (default: 10) |
| **Plugin Loading** | ✅ Parallel | `load_all_plugins(parallel=True)` via ThreadPoolExecutor |
| **Search** | ✅ Concurrent | `asyncio.gather(*search_tasks)` in advanced_search.py |

### Existing Multi-Agent Features

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

## Bottlenecks for Massive Parallelization

### 1. Singleton PenguinCore

**Problem:** `router.core` is a single shared instance.

```python
# penguin/web/routes.py:129
async def get_core():
    return router.core  # Single instance for all requests
```

**Impact:**
- `stream_lock = asyncio.Lock()` serializes all streaming output
- `_streaming_state` is a single dict, not per-agent

**Location:** `penguin/core.py:615-632`

### 2. Global Streaming State

**Problem:** Streaming state is stored on PenguinCore, not per-agent.

```python
# penguin/core.py:618-632
self._streaming_state = {
    "active": False,
    "content": "",
    "reasoning_content": "",
    "message_type": None,
    "role": None,
    "metadata": {},
    "emit_buffer": "",
    "last_emit_ts": 0.0,
}
```

**Impact:** Only one agent can stream at a time.

### 3. LLM Provider Rate Limits

**Problem:** OpenRouter and other providers have rate limits.

**Impact:**
- Requests per minute caps
- Tokens per minute caps
- Connection limits

### 4. Conversation Manager Locking

**Problem:** ConversationManager may have internal locks for session access.

**Location:** `penguin/conversation/manager.py`

---

## Parallelization Roadmap

### Phase 1: Per-Agent Streaming State

**Goal:** Allow multiple agents to stream simultaneously.

**Changes:**

```python
# Move streaming state into agent context
class AgentStreamingState:
    def __init__(self):
        self.active = False
        self.content = ""
        self.reasoning_content = ""
        self.emit_buffer = ""
        self.lock = asyncio.Lock()

# In PenguinCore
self._agent_streaming_states: Dict[str, AgentStreamingState] = {}

def get_streaming_state(self, agent_id: str) -> AgentStreamingState:
    if agent_id not in self._agent_streaming_states:
        self._agent_streaming_states[agent_id] = AgentStreamingState()
    return self._agent_streaming_states[agent_id]
```

**Files to modify:**
- `penguin/core.py` - Add per-agent streaming state
- `penguin/llm/api_client.py` - Use agent-specific state
- `penguin/web/routes.py` - Pass agent_id through streaming

### Phase 2: Connection Pooling

**Goal:** Efficient HTTP connections for parallel LLM calls.

**Changes:**

```python
# penguin/llm/api_client.py
import httpx

class APIClient:
    def __init__(self):
        self._client = httpx.AsyncClient(
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
                keepalive_expiry=30.0,
            ),
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0),
        )
```

### Phase 3: Rate Limiting Layer

**Goal:** Prevent hitting provider rate limits.

**Implementation:**

```python
# penguin/llm/rate_limiter.py
from asyncio import Semaphore
from collections import defaultdict

class ProviderRateLimiter:
    def __init__(self):
        self._semaphores: Dict[str, Semaphore] = defaultdict(lambda: Semaphore(10))
        self._request_counts: Dict[str, int] = defaultdict(int)
        self._token_buckets: Dict[str, TokenBucket] = {}

    async def acquire(self, provider: str) -> None:
        await self._semaphores[provider].acquire()

    def release(self, provider: str) -> None:
        self._semaphores[provider].release()

    @asynccontextmanager
    async def limit(self, provider: str):
        await self.acquire(provider)
        try:
            yield
        finally:
            self.release(provider)
```

### Phase 4: Background Agent Execution

**Goal:** Run agents as background tasks with queue-based work distribution.

**Options:**

1. **asyncio.TaskGroup** (Python 3.11+) - Lightweight, in-process
2. **Celery + Redis** - Distributed, persistent queues
3. **ARQ** - Async Redis queue, lighter than Celery

**Recommended:** Start with asyncio.TaskGroup, migrate to ARQ if needed.

```python
# penguin/multi/executor.py
class AgentExecutor:
    def __init__(self, max_concurrent: int = 10):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: Dict[str, asyncio.Task] = {}

    async def spawn_parallel(
        self,
        agents: List[str],
        prompts: List[str],
    ) -> List[str]:
        """Execute multiple agents in parallel."""
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._run_agent(agent, prompt))
                for agent, prompt in zip(agents, prompts)
            ]
        return [t.result() for t in tasks]

    async def _run_agent(self, agent_id: str, prompt: str) -> str:
        async with self._semaphore:
            return await self.core.process(
                input_data={"text": prompt},
                agent_id=agent_id,
            )
```

### Phase 5: Shared Context Window Optimization

**Goal:** Efficient context sharing between agents without duplication.

**Current:** `share_context_window_with` copies context.

**Improved:**

```python
# Copy-on-write context windows
class SharedContextWindow:
    def __init__(self, max_tokens: int):
        self._base_messages: List[Message] = []
        self._agent_deltas: Dict[str, List[Message]] = {}
        self._lock = asyncio.Lock()

    async def get_messages(self, agent_id: str) -> List[Message]:
        async with self._lock:
            base = self._base_messages.copy()
            delta = self._agent_deltas.get(agent_id, [])
            return base + delta

    async def add_message(self, agent_id: str, message: Message) -> None:
        async with self._lock:
            self._agent_deltas.setdefault(agent_id, []).append(message)
```

---

## Configuration

### Environment Variables

```bash
# Concurrency limits
PENGUIN_MAX_CONCURRENT_TASKS=10       # Max parallel agent executions
PENGUIN_MAX_CONNECTIONS_PER_PROVIDER=20  # HTTP connection pool size
PENGUIN_RATE_LIMIT_RPM=60             # Requests per minute per provider

# Background execution
PENGUIN_USE_BACKGROUND_AGENTS=false   # Enable queue-based execution
PENGUIN_REDIS_URL=redis://localhost:6379  # For ARQ/Celery
```

### Per-Agent Configuration

```yaml
# config.yml
agents:
  analyzer:
    max_concurrent_instances: 3
    rate_limit_rpm: 20
    priority: high

  implementer:
    max_concurrent_instances: 5
    rate_limit_rpm: 30
    priority: normal
```

---

## API Changes for CLI

### New WebSocket Events

```typescript
// Agent spawn notification
{ event: "agent_spawned", data: { agent_id: string, role: string, parent_id?: string } }

// Parallel execution status
{ event: "parallel_status", data: {
  running: string[],      // Active agent IDs
  queued: string[],       // Waiting agents
  completed: string[],    // Finished agents
  failed: string[]        // Error agents
}}

// Agent-specific streaming (prefix with agent_id)
{ event: "agent_token", data: { agent_id: string, token: string } }
```

### CLI Multi-Agent Display

```
┌─ Agents ────────────────────────────────────────┐
│ 🟢 analyzer-1    [streaming] "Analyzing code..."│
│ 🟢 implementer-1 [streaming] "Writing tests..." │
│ 🟡 reviewer-1    [queued]                       │
│ ✅ planner-1     [done]                         │
└─────────────────────────────────────────────────┘
```

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
    agents = [f"agent-{i}" for i in range(10)]
    prompts = ["Hello, world!"] * 10

    results = await executor.spawn_parallel(agents, prompts)

    assert len(results) == 10
    assert all(r is not None for r in results)

@pytest.mark.asyncio
async def test_rate_limiting():
    """Verify rate limiter prevents provider overload."""
    # Should complete without 429 errors
    pass
```

### Metrics to Track

- Concurrent agent count (gauge)
- Request latency per agent (histogram)
- Queue depth (gauge)
- Rate limit hits (counter)
- Stream lock contention time (histogram)

---

## Migration Path

1. **v1.0** - Current: Single-threaded streaming, shared state
2. **v1.1** - Per-agent streaming state, remove global lock
3. **v1.2** - Connection pooling, basic rate limiting
4. **v2.0** - Background agent execution, queue-based
5. **v2.1** - Distributed execution (optional, for massive scale)

---

## References

- [FastAPI Concurrency](https://fastapi.tiangolo.com/async/)
- [asyncio TaskGroup](https://docs.python.org/3/library/asyncio-task.html#asyncio.TaskGroup)
- [httpx Connection Pooling](https://www.python-httpx.org/advanced/#pool-limit-configuration)
- [ARQ - Async Redis Queue](https://arq-docs.helpmanual.io/)
