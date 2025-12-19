# Core.py Refactoring Plan

*Created: 2025-12-18*
*Updated: 2025-12-18*
*Target: Reduce `penguin/core.py` from 3,802 lines to ~1,900 lines (50% reduction)*

---

## Executive Summary

PenguinCore has grown into a god object that:
1. Reimplements logic already in subcomponents (`model_config.py`, `config.py`)
2. Treats agents as persistent entities when they should be **config + conversation**
3. Maintains 5 parallel state dictionaries for agent management

**Goal:** Core becomes a thin orchestration layer where:
- Agents are **config applied at runtime**, not registered entities
- Model/config logic delegates to existing modules (no new abstractions)
- Only truly unique logic (streaming) gets extracted

---

## Architectural Shift: Agents as Config, Not Entities

### Current Model (Flawed)
```python
# Agent as persistent entity with lifecycle
core.register_agent("analyzer", persona="code_analyzer", model_overrides={...})
# Creates: API client, action executor, MessageBus handler, stores in 5 dicts
result = await core.engine.run_agent_turn("analyzer", message)
```

### New Model
```python
# Agent as config applied at call time
result = await core.process(message, agent="code_analyzer")
# or
result = await core.process(message, agent_config=AgentConfig(...))
```

### What Persists vs What's Derived

| State | Persist? | Location |
|-------|----------|----------|
| Conversation history | **YES** | ConversationManager |
| System prompt | NO | Derive from config.yml persona |
| Model config | NO | Derive from config.yml persona |
| API client | NO | Create on demand |
| Action executor | NO | Create on demand |
| Tool defaults | NO | Derive from config.yml persona |

### State Dictionaries to Delete
```python
# DELETE from Core - no longer needed:
self._agent_api_clients: Dict[str, APIClient]
self._agent_model_overrides: Dict[str, ModelConfig]
self._agent_tool_defaults: Dict[str, Sequence[str]]
self._agent_bus_handlers: Dict[str, Any]
self._agent_paused: Dict[str, bool]
```

---

## New File Structure (Minimal)

```
penguin/
├── core.py                          # ~1,900 lines (was 3,802)
├── streaming/
│   ├── __init__.py
│   └── stream_handler.py            # NEW: 120 lines
├── llm/
│   └── model_config.py              # EXPAND: +30 lines (OpenRouter fetch)
└── utils/
    └── callbacks.py                 # NEW: 40 lines
```

**What we're NOT creating:**
- ~~`model/model_registry.py`~~ - `model_config.py` already has `ModelConfig.for_model()`
- ~~`config/resolver.py`~~ - `config.py` already has `AgentPersonaConfig`, `RuntimeConfig`
- ~~Hardcoded `MODEL_SPECS`~~ - OpenRouter provides this dynamically

**New code:** ~190 lines (2 small modules)
**Removed from core.py:** ~1,900 lines
**Net reduction:** ~1,700 lines

---

## Phase 1: Extract Streaming Logic

### Current State (400 lines in core.py)

| Method | Lines | Location |
|--------|-------|----------|
| `_handle_stream_chunk()` | 120 | 3200-3318 |
| `finalize_streaming_message()` | 150 | 3319-3467 |
| `_streaming_state` dict | 20 | 618-636 |
| `_prepare_runmode_stream_callback()` | 40 | 3476-3515 |
| `_invoke_runmode_stream_callback()` | 10 | 3516-3525 |
| Coalescing constants/logic | 60 | scattered |

### Target: `penguin/streaming/stream_handler.py`

```python
"""
Unified streaming handler for LLM response chunks.
Replaces duplicated logic in core.py, engine.py, and api_client.py.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
import asyncio
import time

# Constants (previously magic numbers)
MIN_STREAM_INTERVAL = 0.04  # ~25 fps
MIN_STREAM_CHARS = 12
MAX_EMPTY_RESPONSES = 3


@dataclass
class StreamState:
    """Immutable streaming state container."""
    active: bool = False
    content: str = ""
    reasoning_content: str = ""
    message_type: str = "assistant"
    role: str = "assistant"
    metadata: Dict[str, Any] = field(default_factory=dict)
    started_at: Optional[float] = None
    last_update: Optional[float] = None
    empty_response_count: int = 0
    error: Optional[str] = None
    emit_buffer: str = ""
    last_emit_ts: float = 0.0

    def reset(self) -> "StreamState":
        """Return fresh state."""
        return StreamState()


class StreamHandler:
    """
    Manages streaming lifecycle: buffering, coalescing, finalization.

    Usage:
        handler = StreamHandler(emit_callback=core.emit_ui_event)

        # During streaming
        await handler.handle_chunk(chunk, message_type="assistant")

        # After streaming completes
        result = await handler.finalize()
    """

    def __init__(
        self,
        emit_callback: Callable,
        conversation_manager: Optional[Any] = None,
    ):
        self._emit = emit_callback
        self._cm = conversation_manager
        self._state = StreamState()
        self._lock = asyncio.Lock()

    async def handle_chunk(self, chunk: str, message_type: str = "assistant") -> None:
        """Process incoming chunk with coalescing."""
        async with self._lock:
            if not self._state.active:
                self._state = StreamState(
                    active=True,
                    started_at=time.time(),
                    message_type=message_type,
                )

            self._state.content += chunk
            self._state.emit_buffer += chunk
            self._state.last_update = time.time()

            # Coalesce: emit when buffer is large enough or interval elapsed
            should_emit = (
                len(self._state.emit_buffer) >= MIN_STREAM_CHARS
                or (time.time() - self._state.last_emit_ts) >= MIN_STREAM_INTERVAL
            )

            if should_emit and self._state.emit_buffer:
                await self._emit("stream_chunk", {
                    "content": self._state.emit_buffer,
                    "message_type": message_type,
                    "role": self._state.role,
                })
                self._state.emit_buffer = ""
                self._state.last_emit_ts = time.time()

    async def finalize(self) -> Dict[str, Any]:
        """Complete streaming and persist message."""
        async with self._lock:
            if not self._state.active:
                return {"content": "", "finalized": False}

            # Flush remaining buffer
            if self._state.emit_buffer:
                await self._emit("stream_chunk", {
                    "content": self._state.emit_buffer,
                    "message_type": self._state.message_type,
                    "final": True,
                })

            # Persist to conversation
            if self._cm and self._state.content:
                self._cm.add_message(
                    role=self._state.role,
                    content=self._state.content,
                    message_type=self._state.message_type,
                    metadata=self._state.metadata,
                )

            result = {
                "content": self._state.content,
                "reasoning_content": self._state.reasoning_content,
                "message_type": self._state.message_type,
                "duration": time.time() - (self._state.started_at or time.time()),
                "finalized": True,
            }

            self._state = StreamState()
            return result

    @property
    def is_active(self) -> bool:
        return self._state.active

    @property
    def content(self) -> str:
        return self._state.content
```

### Core.py Changes

**Remove:**
- `_streaming_state` dict initialization (lines 618-636)
- `_handle_stream_chunk()` method (lines 3200-3318)
- `finalize_streaming_message()` method (lines 3319-3467)
- `_prepare_runmode_stream_callback()` (lines 3476-3515)
- `_invoke_runmode_stream_callback()` (lines 3516-3525)

**Add:**
```python
from penguin.streaming import StreamHandler

class PenguinCore:
    def __init__(self, ...):
        ...
        self._stream_handler: Optional[StreamHandler] = None

    def _get_stream_handler(self) -> StreamHandler:
        if self._stream_handler is None:
            self._stream_handler = StreamHandler(
                emit_callback=self.emit_ui_event,
                conversation_manager=self.conversation_manager,
            )
        return self._stream_handler

    async def handle_stream_chunk(self, chunk: str, message_type: str = "assistant"):
        await self._get_stream_handler().handle_chunk(chunk, message_type)

    def finalize_streaming_message(self) -> Dict[str, Any]:
        if self._stream_handler:
            return asyncio.run(self._stream_handler.finalize())
        return {}
```

**Lines saved:** 400 - 20 = **380 lines**

---

## Phase 2: Extract Callback Utilities

### Current State (80 lines duplicated)

Same `inspect.signature()` pattern in:
- `core.py` lines 3477-3506 (`_prepare_runmode_stream_callback`)
- `api_client.py` lines 276-320 (callback wrapper)

### Target: `penguin/utils/callbacks.py`

```python
"""
Callback signature adaptation utilities.
Normalizes callbacks to consistent async (chunk, message_type) signature.
"""
import asyncio
import inspect
from typing import Callable, Optional


def adapt_stream_callback(
    callback: Callable,
    force_arity: Optional[int] = None,
) -> Callable[[str, str], None]:
    """
    Normalize a stream callback to async (chunk: str, message_type: str) signature.

    Handles:
    - Sync and async callbacks
    - 1-param (chunk only) and 2-param (chunk, message_type) signatures
    """
    sig = inspect.signature(callback)
    arity = force_arity or len(sig.parameters)
    is_async = asyncio.iscoroutinefunction(callback)

    if is_async:
        if arity >= 2:
            return callback
        async def async_wrapper(chunk: str, message_type: str):
            await callback(chunk)
        return async_wrapper
    else:
        if arity >= 2:
            async def sync_wrapper_2(chunk: str, message_type: str):
                await asyncio.get_running_loop().run_in_executor(None, callback, chunk, message_type)
            return sync_wrapper_2
        async def sync_wrapper_1(chunk: str, message_type: str):
            await asyncio.get_running_loop().run_in_executor(None, callback, chunk)
        return sync_wrapper_1
```

### Changes

**Remove from core.py:** `_prepare_runmode_stream_callback()` and inline signature detection
**Remove from api_client.py:** Callback wrapper code (lines 276-320)
**Add:** `from penguin.utils.callbacks import adapt_stream_callback`

**Lines saved:** ~75 lines

---

## Phase 3: Simplify Model Management

### Current State (400 lines in core.py)

| Method | Lines | Location |
|--------|-------|----------|
| `load_model()` | 120 | 2919-3038 |
| `_apply_new_model_config()` | 60 | 3039-3098 |
| `list_available_models()` | 30 | 3099-3128 |
| `get_current_model()` | 20 | 3129-3148 |
| `_fetch_model_specifications()` | 80 | 3149-3228 |
| Model spec constants | 90 | 3700-3790 |

### Key Insight: `model_config.py` Already Has This

```python
# model_config.py already provides:
ModelConfig.for_model(model_name, provider, client_preference, model_configs)
ModelConfig.from_env()
_detect_reasoning_support()
get_reasoning_config()
```

**We do NOT need a `ModelRegistry` class.** Just add OpenRouter fetch to `model_config.py`.

### Target: Add to `penguin/llm/model_config.py` (~30 lines)

```python
async def fetch_openrouter_specs(model_id: str) -> Optional[Dict[str, Any]]:
    """Fetch model specs from OpenRouter API."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://openrouter.ai/api/v1/models/{model_id}"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "context_length": data.get("context_length"),
                        "max_output_tokens": data.get("top_provider", {}).get("max_completion_tokens"),
                    }
    except Exception:
        pass
    return None
```

### Core.py Changes

**Remove:**
- `load_model()` body (120 lines) → reduce to 10 lines
- `_apply_new_model_config()` (60 lines) → inline
- `_fetch_model_specifications()` (80 lines) → use `fetch_openrouter_specs()`
- Model spec constants (90 lines) → delete entirely

**Simplified `load_model()`:**
```python
async def load_model(self, model_id: str) -> bool:
    """Load a new model configuration."""
    try:
        self.model_config = ModelConfig.for_model(
            model_id,
            model_configs=self.config.model_configs
        )
        self.api_client = APIClient(model_config=self.model_config)
        self.api_client.set_system_prompt(self.system_prompt)
        return True
    except Exception as e:
        logger.error(f"Failed to load model {model_id}: {e}")
        return False

def list_available_models(self) -> List[Dict[str, Any]]:
    return [{"id": k, **v} for k, v in self.config.model_configs.items()]

def get_current_model(self) -> Dict[str, Any]:
    return self.model_config.get_config()
```

**Lines saved:** 400 - 30 = **370 lines**

---

## Phase 4: Redesign Agent Architecture

### The Problem

Current `register_agent()` (197 lines) treats agents as **persistent entities**:
- Creates API clients, action executors, MessageBus handlers
- Stores in 5 parallel dictionaries
- Complex lifecycle management

But an agent should be **config applied at runtime** + persistent conversation.

### Current State (500+ lines across multiple methods)

| Code | Lines | Purpose |
|------|-------|---------|
| `register_agent()` | 197 | Entity creation |
| `unregister_agent()` | 30 | Entity cleanup |
| `create_sub_agent()` | 40 | Entity creation |
| `_lookup_persona_config()` | 12 | Config lookup |
| `_flatten_model_overrides()` | 35 | Config transform |
| `_resolve_model_config_for_agent()` | 45 | Config resolution |
| `_get_model_config_dict()` | 12 | Config lookup |
| `_summarize_model_config()` | 15 | Config display |
| `get_agent_roster()` | 55 | Metadata assembly |
| `get_agent_profile()` | 5 | Metadata lookup |
| `set_agent_paused()` | 15 | State management |
| `is_agent_paused()` | 5 | State check |
| State dictionaries | 20 | Storage |
| MessageBus handlers | 75 | Event wiring |

**Total: ~560 lines for agent management**

### New Architecture

**Principle:** Agent = Persona Config (from config.yml) + Conversation (persistent)

```python
# New: process() accepts agent identifier
async def process(
    self,
    message: str,
    agent: Optional[str] = None,  # Persona name from config.yml
    agent_config: Optional[AgentConfig] = None,  # Or explicit config
    **kwargs
) -> Dict[str, Any]:
    # 1. Resolve config (10 lines, not 200)
    config = self._resolve_agent_config(agent, agent_config)

    # 2. Get/create conversation (the ONLY persistent state)
    conv = self.conversation_manager.get_agent_conversation(
        config.agent_id, create_if_missing=True
    )

    # 3. Derive everything else at call time
    effective_model = config.model or self.model_config
    effective_prompt = config.system_prompt or self.system_prompt

    # 4. Create ephemeral components
    api_client = APIClient(model_config=effective_model)
    api_client.set_system_prompt(effective_prompt)

    # 5. Process
    return await self._process_with_config(message, conv, api_client, config)
```

### What This Eliminates

```python
# DELETE from Core:
self._agent_api_clients: Dict[str, APIClient]         # Create on demand
self._agent_model_overrides: Dict[str, ModelConfig]   # Derive from config.yml
self._agent_tool_defaults: Dict[str, Sequence[str]]   # Derive from config.yml
self._agent_bus_handlers: Dict[str, Any]              # Rethink MessageBus
self._agent_paused: Dict[str, bool]                   # Move to conversation metadata

# DELETE these methods:
register_agent()              # → 10 lines: just ensure conversation exists
unregister_agent()            # → 5 lines: just clean up conversation
_lookup_persona_config()      # → inline: self.config.agent_personas.get(name)
_flatten_model_overrides()    # → use ModelConfig.for_model() directly
_resolve_model_config_for_agent()  # → inline with ModelConfig.for_model()
_get_model_config_dict()      # → inline
_summarize_model_config()     # → use ModelConfig.get_config()
get_agent_roster()            # → simplify significantly
set_agent_paused()            # → conv.session.metadata["paused"] = True
is_agent_paused()             # → conv.session.metadata.get("paused", False)
```

### New Minimal API

```python
@dataclass
class AgentConfig:
    """Ephemeral agent configuration (not stored, derived from config.yml)."""
    agent_id: str
    system_prompt: Optional[str] = None
    model: Optional[ModelConfig] = None
    tools: Optional[List[str]] = None
    permissions: Optional[Dict[str, Any]] = None

    @classmethod
    def from_persona(cls, name: str, config: Config) -> "AgentConfig":
        """Build from config.yml persona definition."""
        persona = config.agent_personas.get(name)
        if not persona:
            return cls(agent_id=name)

        model = None
        if persona.model:
            model = ModelConfig.for_model(
                persona.model.id or persona.model.model,
                model_configs=config.model_configs
            )

        return cls(
            agent_id=name,
            system_prompt=persona.system_prompt,
            model=model,
            tools=persona.default_tools,
            permissions=persona.permissions,
        )


class PenguinCore:
    def _resolve_agent_config(
        self,
        agent: Optional[str],
        agent_config: Optional[AgentConfig],
    ) -> AgentConfig:
        """Resolve agent configuration from name or explicit config."""
        if agent_config:
            return agent_config
        if agent:
            return AgentConfig.from_persona(agent, self.config)
        return AgentConfig(agent_id="default")

    def ensure_agent_conversation(self, agent_id: str, system_prompt: Optional[str] = None) -> None:
        """Ensure a conversation exists for an agent. Replaces register_agent()."""
        conv = self.conversation_manager.get_agent_conversation(agent_id, create_if_missing=True)
        if system_prompt:
            conv.set_system_prompt(system_prompt)

    def delete_agent_conversation(self, agent_id: str) -> bool:
        """Delete an agent's conversation. Replaces unregister_agent()."""
        return self.conversation_manager.delete_agent_conversation(agent_id)
```

### Migration Path

1. Add `AgentConfig` dataclass
2. Add `_resolve_agent_config()` method
3. Update `process()` to accept `agent` parameter
4. Deprecate `register_agent()` → calls `ensure_agent_conversation()`
5. Remove state dictionaries
6. Remove config resolution helpers

### Existing Agent Infrastructure (Use It!)

The `penguin/agent/` module already has a clean architecture that `core.py` is duplicating:

| File | Purpose | Status |
|------|---------|--------|
| `agent/schema.py` | `AgentConfig`, `AgentLimits`, `AgentSecurity`, `AgentMount` | ✅ Ready |
| `agent/base.py` | `BaseAgent` abstract class with `run()` method | ✅ Ready |
| `agent/launcher.py` | `AgentLauncher` - loads YAML configs, instantiates with DI | ✅ Ready |
| `agent/basic_agent.py` | `BasicPenguinAgent` implementation | ✅ Ready |

**Key insight:** `AgentLauncher.invoke()` already does what `register_agent()` tries to do, but cleaner:

```python
# AgentLauncher already handles:
# - Loading agent configs from YAML
# - Dynamic class loading from type string
# - Dependency injection from PenguinCore
# - Sandboxed execution (Docker, Firecracker)

launcher = AgentLauncher(core_instance=core)
result = await launcher.invoke("code_analyzer", prompt, context)
```

**Action:** Use `AgentLauncher` instead of reimplementing in `core.py`.

### Sub-Agent Strategy (Resolved)

Based on `sub_agent_simplification.md` and the existing `agent/` infrastructure:

#### Option A: Simple Delegation (80% of use cases)
```python
# delegate_read_task pattern - parent controls, haiku analyzes
async def delegate_read_task(
    task: str,
    files: List[str],
    model: str = "anthropic/claude-haiku"
) -> str:
    """Parent reads files, delegates analysis to lighter model."""
    contents = [Path(f).read_text()[:10000] for f in files[:5]]
    context = "\n\n".join(f"=== {f} ===\n{c}" for f, c in zip(files, contents))

    # Direct API call - no MessageBus, no state dictionaries
    gateway = create_gateway(provider="openrouter", model=model)
    return await gateway.chat([{"role": "user", "content": f"{context}\n\nTask: {task}"}])
```

- Simple to implement (can add today)
- No MessageBus, no handler registration
- Parent maintains control
- Predictable behavior

#### Option B: Autonomous Agents (Complex scenarios)
```python
# Use AgentLauncher for autonomous agents with tool access
launcher = AgentLauncher(core_instance=core, config_dir=Path("agents"))
result = await launcher.invoke(
    agent_name="research_agent",
    prompt="Investigate the codebase architecture",
    context={"workspace": "/path/to/project"}
)
```

- Uses existing `AgentLauncher` infrastructure
- Agent configs in YAML files (`agents/*.yaml`)
- Sandboxing via Docker/Firecracker supported
- Full tool access if needed

#### What to Delete from Core.py

The following are redundant with `AgentLauncher`:
- `register_agent()` (197 lines) - Use `AgentLauncher.invoke()`
- `create_sub_agent()` (40 lines) - Use `AgentLauncher.invoke()`
- `_agent_api_clients` dict - Launcher handles this
- `_agent_model_overrides` dict - Launcher handles this
- MessageBus agent handlers - Launcher handles sandboxed execution

#### What Core.py Should Keep (Simplified)

```python
class PenguinCore:
    def __init__(self, ...):
        # Only keep AgentLauncher reference
        self._agent_launcher = AgentLauncher(core_instance=self)

    async def invoke_agent(
        self,
        agent_name: str,
        prompt: str,
        context: Optional[Dict] = None
    ) -> Any:
        """Invoke a configured agent. Delegates to AgentLauncher."""
        return await self._agent_launcher.invoke(agent_name, prompt, context)

    async def delegate_read_task(
        self,
        task: str,
        files: List[str],
        model: str = "anthropic/claude-haiku"
    ) -> str:
        """Simple delegation for read-only analysis."""
        # Implementation from Option A above
        ...
```

**Lines saved:** 560 - 60 = **500 lines**

---

## Phase 5: Remove Deprecated & Dead Code

### Deprecated Methods (150 lines)

| Method | Lines | Action |
|--------|-------|--------|
| `multi_step_process()` | 40 | Reduce to 1-liner |
| `process_message()` (old signature) | 80 | Reduce to delegation |

**Replace with:**
```python
async def multi_step_process(self, message: str, **kwargs) -> Dict[str, Any]:
    """DEPRECATED: Use process(..., multi_step=True)"""
    return await self.process({"text": message}, multi_step=True, **kwargs)
```

### Dead Code (100 lines)

| Code | Lines | Action |
|------|-------|--------|
| Commented debug prints | 677-680 | Delete |
| Commented reset methods | 895-898 | Delete |
| Legacy conversation wrappers | various | Delete or inline |

### MessageBus Agent Handlers (150 lines)

The `_agent_inbox` nested function (lines 1325-1399) should move to Engine:

**Remove from core.py:**
- MessageBus handler registration in `register_agent()`
- `_agent_bus_handlers` dict
- Handler cleanup in `unregister_agent()`

**Lines saved:** 150 + 100 + 150 = **400 lines**

---

## Phase 6: Consolidate UI Event System

### Current State (150 lines)

| Code | Lines | Location |
|------|-------|----------|
| `ui_subscribers` list | 5 | 560 |
| `register_ui()` | 15 | various |
| `unregister_ui()` | 10 | various |
| Legacy subscriber iteration | 40 | emit_ui_event |

### Action

Remove legacy subscriber pattern entirely. `event_bus` is the canonical UI channel.

**Remove:**
- `ui_subscribers` list
- `register_ui()` method
- `unregister_ui()` method
- Subscriber iteration in `emit_ui_event()`

**Simplify `emit_ui_event()`:**
```python
async def emit_ui_event(self, event_type: str, data: Dict[str, Any]) -> None:
    """Emit UI event via event bus."""
    await self.event_bus.emit(event_type, data)
```

**Lines saved:** 150 - 5 = **145 lines**

---

## Phase 7: Inline/Remove Minor Methods

### Methods to Inline (100 lines)

| Method | Lines | Action |
|--------|-------|--------|
| `validate_path()` | 6 | Inline `Path.mkdir()` at call sites |
| `notify_progress()` | 4 | Inline loop at call sites |
| `get_output_style()` | 4 | Convert to `@property` |
| `get_prompt_mode()` | 4 | Convert to `@property` |
| Various 1-liner getters | 30 | Convert to properties |

### Token Tracking (120 lines)

Move to `conversation_manager`:
- `accumulated_tokens` dict
- `token_callbacks` list
- Token calculation logic in `get_token_usage()`

**Lines saved:** 100 + 120 = **220 lines**

---

## Summary: Line Count

| Phase | Removed | Added | Net |
|-------|---------|-------|-----|
| 1. Streaming | 400 | 20 | -380 |
| 2. Callbacks | 80 | 5 | -75 |
| 3. Model Management | 400 | 30 | -370 |
| 4. Agent Architecture | 560 | 60 | -500 |
| 5. Deprecated/Dead | 400 | 0 | -400 |
| 6. UI Events | 150 | 5 | -145 |
| 7. Minor Methods | 220 | 0 | -220 |
| **Total** | **2,210** | **120** | **-2,090** |

**Final:** 3,802 - 2,090 = **~1,710 lines**

---

## New Files Summary (Minimal)

| File | Lines | Purpose |
|------|-------|---------|
| `penguin/streaming/stream_handler.py` | 120 | Unified streaming lifecycle |
| `penguin/utils/callbacks.py` | 40 | Callback signature adaptation |
| **Total new code** | **160** | |

**Files NOT being created (use existing):**
- ~~`model/model_registry.py`~~ → use `ModelConfig.for_model()`
- ~~`config/resolver.py`~~ → use `config.py` structures directly

---

## Implementation Order

1. **Phase 1: Agent Architecture** (Biggest win)
   - Add `AgentConfig` dataclass (can live in core.py or config.py)
   - Update `process()` to accept `agent` parameter
   - Deprecate `register_agent()` → `ensure_agent_conversation()`
   - Delete 5 state dictionaries
   - Delete config resolution helper methods
   - Test agent/persona functionality

2. **Phase 2: Streaming extraction**
   - Create `streaming/stream_handler.py`
   - Update core.py to use StreamHandler
   - Remove `_streaming_state` dict
   - Test streaming in CLI

3. **Phase 3: Model simplification**
   - Add `fetch_openrouter_specs()` to `model_config.py`
   - Simplify `load_model()` to 10 lines
   - Delete hardcoded model specs
   - Test model switching

4. **Phase 4: Cleanup**
   - Create `utils/callbacks.py`
   - Remove deprecated methods
   - Remove legacy UI subscriber pattern
   - Inline minor methods
   - Final testing

---

## Validation Checklist

After refactoring, verify:

- [ ] Single-turn chat works
- [ ] Multi-step reasoning works (RunMode)
- [ ] Streaming displays correctly in CLI
- [ ] Model switching works (`/model` command)
- [ ] Persona-based agents work (`agent="code_analyzer"`)
- [ ] Conversations persist correctly
- [ ] Checkpoints/snapshots work
- [ ] Token tracking accurate
- [ ] All tests pass

---

## Key Principles

1. **Agent = Config + Conversation**, not persistent entity
2. **Derive at runtime**, don't store redundant state
3. **Use existing modules** (`ModelConfig.for_model()`, `AgentPersonaConfig`)
4. **Only extract truly scattered logic** (streaming, callbacks)
5. **Delete > Abstract** - removing code is better than creating new layers

---

## Architecture Review Summary

*Completed 2025-12-18 - Review of related docs and modules*

### Documents Reviewed

| Document | Alignment | Notes |
|----------|-----------|-------|
| `architecture.md` | 90% | Agent Registration section (lines 296-309) will need updates |
| `improvements.md` | ✅ 100% | Already identified same issues - validates our approach |
| `sub_agent_simplification.md` | ✅ Adopted | `delegate_read_task` pattern incorporated |
| `sub_agents_playbook.md` | Informational | Documents Phase C/D work - backend solid, UI gaps remain |

### Modules Reviewed

| Module | Finding | Action |
|--------|---------|--------|
| `agent/__init__.py` | Clean thin-wrapper pattern | **Model to follow** |
| `agent/schema.py` | `AgentConfig` already exists with limits/security | **Use instead of new class** |
| `agent/base.py` | `BaseAgent` with `run()` method (plan/act/observe deprecated) | **Use as-is** |
| `agent/launcher.py` | `AgentLauncher` handles DI, YAML configs, sandboxing | **Replace register_agent()** |

### Key Discovery

**`penguin/agent/` already has the clean architecture we want.** The duplication in `core.py` exists because:
1. `register_agent()` was written before `AgentLauncher` existed
2. The two approaches were never consolidated
3. Sub-agent work (Phase C/D) built on top of the old pattern

### Recommended Migration

1. Update `AgentConfig` in `agent/schema.py` if needed (it's comprehensive)
2. Use `AgentLauncher.invoke()` instead of `register_agent()`
3. Add `delegate_read_task()` to Core for simple delegations
4. Delete the 5 state dictionaries from Core
5. Update `architecture.md` after refactor

### Sub-Agent Final Decision

| Use Case | Approach | Complexity |
|----------|----------|------------|
| Analyze provided content | `delegate_read_task()` | Simple |
| Autonomous exploration | `AgentLauncher.invoke()` | Medium |
| Sandboxed execution | `AgentLauncher` + Docker | Complex |

**The MessageBus pattern for agent communication is overkill** for most use cases. Keep it only for scenarios that truly need pub/sub (e.g., parallel agents sharing findings).
