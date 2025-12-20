# Penguin Performance Optimizations

This document outlines performance optimization strategies specifically designed for Penguin's architecture. Unlike generic optimization lists, these recommendations target Penguin's actual bottlenecks.

---

## Understanding Penguin's Performance Profile

### What Penguin Actually Does
Penguin is an **I/O-bound orchestration framework**. The vast majority of execution time is spent:
1. **Waiting for LLM API responses** (seconds per request)
2. **File system operations** (reads, writes, searches)
3. **SQLite queries** (conversation/project persistence)
4. **Network calls** (OpenRouter, embeddings APIs)

### What Penguin Does NOT Do
- Heavy numerical computation
- CPU-intensive data processing
- Matrix operations or scientific computing
- Video/image processing at scale

### Implications
**Optimizations that help:** Async I/O, caching, connection pooling, lazy loading, batching
**Optimizations that don't help:** Compiled Python (Codon/Cython), multiprocessing, SIMD

---

## 1. I/O-Bound Optimizations (Highest Impact)

### 1.1 LLM API Call Optimization

**Problem:** Each LLM call takes 1-30+ seconds. Multiple sequential calls compound latency.

**Optimizations:**

| Strategy | Implementation | Status |
|----------|---------------|--------|
| Connection pooling | Reuse HTTP connections via `aiohttp.ClientSession` | Partial |
| Request batching | Combine independent prompts into single API call | Not implemented |
| Response streaming | Process tokens as they arrive | ✅ Implemented |
| Retry with backoff | Handle rate limits gracefully | ✅ Implemented |

**Recommended:**
```python
# In APIClient - reuse session across requests
class APIClient:
    _session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=300),
                connector=aiohttp.TCPConnector(limit=10, keepalive_timeout=30)
            )
        return self._session
```

### 1.2 File System Optimization

**Problem:** Repeated file reads during tool execution, especially for large codebases.

**Optimizations:**

| Strategy | Impact | Status |
|----------|--------|--------|
| File content caching | Avoid re-reading unchanged files | Not implemented |
| Directory listing cache | Cache `glob` and `find` results with TTL | Not implemented |
| Batched file reads | Read multiple files in single operation | Not implemented |
| Async file I/O | Use `aiofiles` for non-blocking reads | Partial |

**Recommended:** Add file content cache with mtime-based invalidation:
```python
from functools import lru_cache
import os

@lru_cache(maxsize=500)
def read_file_cached(path: str, mtime: float) -> str:
    """Mtime parameter ensures cache invalidation on file change."""
    return Path(path).read_text()

def read_file(path: str) -> str:
    mtime = os.path.getmtime(path)
    return read_file_cached(path, mtime)
```

### 1.3 SQLite Connection Pooling

**Problem:** Opening new database connections is expensive. Penguin uses SQLite for conversations, projects, and memory.

**Current:** Each query opens/closes connection
**Recommended:** Use connection pool or persistent connection per thread

```python
# In ProjectManager or ConversationManager
import sqlite3
from contextlib import contextmanager

class DatabasePool:
    def __init__(self, db_path: str, pool_size: int = 5):
        self._pool = [sqlite3.connect(db_path) for _ in range(pool_size)]
        self._available = list(range(pool_size))
        self._lock = threading.Lock()

    @contextmanager
    def connection(self):
        with self._lock:
            idx = self._available.pop()
        try:
            yield self._pool[idx]
        finally:
            with self._lock:
                self._available.append(idx)
```

---

## 2. Token Efficiency

### 2.1 Context Window Management

**Problem:** Context windows are finite and expensive. Every token sent to the LLM costs money and latency.

**Current Implementation:** `ContextWindowManager` with category-based budgets
**Location:** `penguin/system/context_window.py`

**Category Budget Defaults:**
| Category | Budget | Priority |
|----------|--------|----------|
| SYSTEM | 10% | Highest (never trimmed) |
| CONTEXT | 35% | High |
| DIALOG | 50% | Medium |
| SYSTEM_OUTPUT | 5% | Lowest (trimmed first) |

**Optimizations:**

| Strategy | Impact | Status |
|----------|--------|--------|
| Aggressive tool output trimming | Reduce SYSTEM_OUTPUT bloat | ✅ Implemented |
| Semantic compression | Summarize old messages | Not implemented |
| Smart context selection | Include only relevant context | Partial |
| Dynamic budget reallocation | Shift unused budget between categories | Not implemented |

### 2.2 System Prompt Optimization

**Problem:** System prompt is ~64KB (~16K tokens) - 10% of context before conversation starts.

**Location:** `penguin/prompt_actions.py`, `penguin/system_prompt.py`

**Optimizations:**
1. **Deduplicate instructions** - `finish_response` mentioned 20+ times
2. **Remove redundant examples** - Keep 1-2 best examples per concept
3. **Dynamic prompt assembly** - Load sections on-demand based on task type
4. **Move tool docs to retrieval** - Don't embed all tool documentation

**Target:** Reduce to <20KB (<5K tokens)

### 2.3 Token-Aware Caching

**Problem:** Identical prompts generate identical responses - wasteful for common queries.

**Recommended:** Cache responses keyed by prompt hash + model:
```python
from hashlib import sha256
from functools import lru_cache

def cache_key(messages: List[dict], model: str) -> str:
    content = json.dumps(messages, sort_keys=True) + model
    return sha256(content.encode()).hexdigest()

@lru_cache(maxsize=100)
def get_cached_response(cache_key: str) -> Optional[str]:
    # Return cached response if exists
    pass
```

---

## 3. Async & Concurrency

### 3.1 Parallel Tool Execution

**Problem:** Sequential tool execution wastes time when tools are independent.

**Current:** Tools execute one at a time
**Location:** `penguin/utils/action_executor.py`

**Recommended:**
```python
async def execute_actions(self, actions: List[Action]) -> List[Result]:
    # Group independent actions
    independent = [a for a in actions if not a.depends_on]
    dependent = [a for a in actions if a.depends_on]

    # Execute independent actions in parallel
    results = await asyncio.gather(*[
        self.execute_action(a) for a in independent
    ])

    # Execute dependent actions sequentially
    for action in dependent:
        results.append(await self.execute_action(action))

    return results
```

### 3.2 Background Processing

**Current Implementation:** Fast startup mode defers heavy operations
**Location:** `penguin/core.py`, `penguin/tools/tool_manager.py`

**Already Implemented:**
- ✅ Deferred memory indexing
- ✅ Lazy tool loading
- ✅ Background initialization tasks

**Planned:**
- Background embedding generation
- Incremental file indexing (only changed files)
- Preemptive context loading

### 3.3 Stream Processing Optimization

**Location:** `penguin/llm/stream_handler.py`

**Implemented Optimizations:**
- ✅ Chunk coalescing (batch small chunks before emit)
- ✅ Rate-limited UI updates (~25 fps)
- ✅ Async stream handling

**Constants:**
```python
MIN_STREAM_INTERVAL = 0.04  # ~25 fps
MIN_STREAM_CHARS = 12       # Minimum buffer before emit
```

---

## 4. Lazy Loading & Deferred Initialization

### 4.1 Current Implementation

**Fast Startup Mode:** Reduces initialization time by 60-80%

| Component | Normal Startup | Fast Startup |
|-----------|---------------|--------------|
| All tools | Immediate | On-demand |
| Memory provider | Immediate | First memory search |
| Browser tools | Immediate | First browser operation |
| File indexing | Immediate | First memory search |

**Enable via:**
```bash
penguin --fast-startup
# or in config.yml:
performance:
  fast_startup: true
```

### 4.2 On-Demand Component Creation

**Principle:** Create expensive objects only when needed.

**Current Pattern:**
```python
# In ToolManager
def _get_memory_tool(self):
    if self._memory_tool is None:
        self._memory_tool = MemoryTool(...)  # Expensive initialization
    return self._memory_tool
```

**Apply to:**
- [ ] Browser automation tools
- [ ] Vector embedding clients
- [ ] External service connections

---

## 5. Caching Strategies

### 5.1 Model Specs Caching

**Implementation:** `ModelSpecsService` in `penguin/llm/model_config.py`

**Features:**
- ✅ Memory cache with TTL (1 hour)
- ✅ Disk cache for persistence across restarts
- ✅ Fallback to hardcoded specs if API unavailable

```python
# Usage
specs = await ModelSpecsService.get_specs("anthropic/claude-3-5-sonnet")
```

### 5.2 Embedding Caching

**Problem:** Generating embeddings is expensive (API call per batch).

**Recommended:** Cache embeddings keyed by content hash:
```python
# In memory provider
def get_embedding(self, text: str) -> List[float]:
    cache_key = hashlib.md5(text.encode()).hexdigest()
    if cache_key in self._embedding_cache:
        return self._embedding_cache[cache_key]

    embedding = self._client.embed(text)
    self._embedding_cache[cache_key] = embedding
    return embedding
```

### 5.3 Configuration Caching

**Current:** Config loaded from YAML on every access
**Recommended:** Load once, cache in memory, watch for file changes

```python
class ConfigManager:
    _config: Optional[Config] = None
    _mtime: float = 0

    @classmethod
    def get(cls) -> Config:
        current_mtime = os.path.getmtime(CONFIG_PATH)
        if cls._config is None or current_mtime > cls._mtime:
            cls._config = cls._load_from_file()
            cls._mtime = current_mtime
        return cls._config
```

---

## 6. Anti-Patterns: What NOT to Do

### 6.1 Codon / Cython / Numba

**Why not:** Penguin's bottleneck is I/O (API calls, file ops), not CPU. Compiled Python won't speed up network latency.

**Additionally:**
- Codon can't compile dynamic Python features (plugin system, decorators)
- Can't use external libraries (LiteLLM, FastAPI, SQLAlchemy)
- Would require rewriting core architecture

### 6.2 Multiprocessing for Concurrency

**Why not:** For I/O-bound tasks, `asyncio` is more efficient than multiprocessing.
- Lower overhead (no process spawn)
- Simpler data sharing
- Better integration with async libraries

**Use multiprocessing only for:** Truly CPU-bound tasks (heavy parsing, image processing)

### 6.3 Premature Micro-Optimizations

**Avoid:**
- Optimizing code that isn't the bottleneck
- Complex caching without measuring benefit
- Over-engineering for hypothetical scale

**Instead:**
1. Profile first (`penguin perf-test`)
2. Identify actual bottlenecks
3. Optimize the top 1-2 issues
4. Measure improvement

---

## 7. Measurement & Profiling

### Built-in Profiling

```bash
# Run performance test
penguin perf-test --iterations 5

# Enable runtime profiling
export PENGUIN_PROFILE=1
penguin
```

### Key Metrics to Track

| Metric | Target | Current |
|--------|--------|---------|
| Cold startup time | <500ms | Varies |
| Warm startup time | <200ms | Varies |
| First response latency | <2s | Depends on model |
| Memory baseline | <200MB | ~150MB |
| Token efficiency | >85% useful | Not measured |

### Profiling Code

```python
from penguin.utils.profiling import enable_profiling, print_startup_report

enable_profiling()
# ... use Penguin ...
print_startup_report()
```

---

## 8. Implementation Priority

### High Impact, Low Effort
1. System prompt reduction (token savings)
2. File content caching (I/O reduction)
3. Connection pooling for API client

### High Impact, Medium Effort
4. Parallel tool execution
5. Embedding caching
6. SQLite connection pooling

### Medium Impact, High Effort
7. Semantic context compression
8. Dynamic prompt assembly
9. Incremental file indexing

---

## Related Documentation

- [Fast Startup & Profiling](../../misc/PERFORMANCE.md) - Detailed profiling guide
- [Core Refactor Plan](core-refactor-plan.md) - Architectural improvements
- [Improvements](../improvements.md) - Code quality issues
