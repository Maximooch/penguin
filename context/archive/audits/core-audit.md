# Core.py Code Audit

*Audit Date: 2025-12-18*
*File: `penguin/core.py`*
*Lines: 3,802*

---

## Executive Summary

PenguinCore is the central orchestration layer that coordinates between ConversationManager, ToolManager, ActionExecutor, ProjectManager, and the Engine. It handles agent registration, conversation routing, streaming, and runtime configuration.

**Overall Assessment:** Well-structured coordination layer but has significant technical debt in error handling, async safety, and method complexity. Priority areas: silent exception handling, untracked async tasks, and streaming state race conditions.

---

## Architecture Overview

```
PenguinCore
├── Factory & Initialization
│   ├── create() - async factory with progress tracking
│   └── __init__() - component wiring
├── Component References
│   ├── conversation_manager (ConversationManager)
│   ├── tool_manager (ToolManager)
│   ├── action_executor (ActionExecutor)
│   ├── project_manager (ProjectManager)
│   ├── api_client (APIClient)
│   ├── engine (Engine)
│   └── event_bus (EventBus)
├── Agent Management
│   ├── register_agent()
│   ├── unregister_agent()
│   ├── create_sub_agent()
│   ├── set_active_agent()
│   └── get_agent_roster()
├── Message Processing
│   ├── process_message()
│   ├── process()
│   ├── get_response()
│   └── multi_step_process() - DEPRECATED
├── Streaming
│   ├── _handle_stream_chunk()
│   ├── finalize_streaming_message()
│   └── emit_ui_event()
├── Message Routing (MessageBus)
│   ├── route_message()
│   ├── send_to_agent()
│   ├── send_to_human()
│   └── human_reply()
├── RunMode Integration
│   ├── start_run_mode()
│   └── _handle_run_mode_event()
├── Model Management
│   ├── load_model()
│   ├── list_available_models()
│   └── get_current_model()
└── State Management
    ├── reset_context()
    ├── reset_state()
    ├── create_checkpoint()
    └── rollback_to_checkpoint()
```

---

## Code Quality Issues

### Issue 1: Silent Exception Handling (30+ instances)

**Locations:** Lines 452, 578, 585, 598, 605, 727, 813, 826, 850, 861, 1037, 1056, 1069, 1228, 1273, 1281, 1322, 1451, 1473, 1482, 1488, 1561, 1593, 1685, 1742, 1753, 1765, 1778, 2340, and more

**Problem:** Bare `except Exception: pass` blocks mask bugs and make debugging extremely difficult.

```python
# Line 452 - Silent config failure
try:
    config_dict = config.to_dict() if hasattr(config, 'to_dict') else {}
except Exception:
    config_dict = {}

# Line 1228 - Silent metadata update failure
except Exception:
    pass

# Line 1281 - Silent APIClient system prompt failure
except Exception:
    pass
```

**Impact:** Failures in configuration, metadata, and API client setup are completely invisible. Issues only surface later as unexpected behavior.

**Recommendation:**
```python
except Exception as e:
    logger.debug(f"Config.to_dict() failed: {e}")
    config_dict = {}
```

---

### Issue 2: Print Statements in Production Code

**Location:** Lines 445-448, 2082

```python
# Lines 445-448 - DEBUG prints during initialization
print("DEBUG: Creating ToolManager in PenguinCore...")
print(f"DEBUG: Passing config of type {type(config)} to ToolManager.")
print(f"DEBUG: Passing log_error of type {type(log_error)} to ToolManager.")
print(f"DEBUG: Fast startup mode: {fast_startup}")

# Line 2082 - Test print in get_response
print(f"ACTION RESULT TEST: System outputs visible to LLM: ...")
```

**Problem:** Debug prints bypass the logging system, pollute CLI output, and cannot be disabled.

**Recommendation:** Replace with `logger.debug()` calls.

---

### Issue 3: Very Long Methods (12 exceed 100 lines)

| Method | Lines | Location |
|--------|-------|----------|
| `create()` (nested log_step_time) | 222 | 301-522 |
| `register_agent()` | 197 | 1128-1324 |
| `__init__()` | 174 | 523-696 |
| `get_response()` | 171 | 1930-2100 |
| `finalize_streaming_message()` | 149 | 3319-3467 |
| `_handle_stream_chunk()` | 119 | 3200-3318 |
| `bridged_callback()` (nested) | 105 | 2537-2641 |
| `load_model()` | 103 | 2919-3021 |
| `process()` | 95 | 2404-2498 |
| `start_run_mode()` | 95 | 2775-2869 |
| `_handle_run_mode_event()` | 93 | 3537-3629 |
| `_agent_inbox()` (nested) | 75 | 1325-1399 |

**Recommendation:** Extract into smaller methods:
```python
# register_agent() should become:
async def register_agent(self, agent_id: str, ...):
    persona_config = self._resolve_persona(persona, agent_id)
    model_config = self._resolve_agent_model_config(...)
    conv = self._provision_agent_conversation(agent_id, ...)
    executor = self._create_agent_executor(agent_id, conv)
    self._register_with_engine(agent_id, conv, executor, model_config)
    self._register_message_bus_handler(agent_id)
```

---

### Issue 4: Duplicate asyncio Import

**Location:** Lines 145, 168

```python
import asyncio  # Line 145
...
import asyncio  # Line 168 - DUPLICATE
```

**Recommendation:** Remove duplicate import.

---

### Issue 5: Missing Type Annotations

**Locations:** 13 methods lack return type annotations

```python
# Line 1421 - Missing return type
def list_all_conversations(self, *, limit_per_agent: int = 1000, offset: int = 0):
    ...  # Returns List[Dict[str, Any]]

# Line 1424 - Missing return type
def load_agent_conversation(self, agent_id: str, conversation_id: str, *, activate: bool = True):
    ...  # Returns bool

# Line 1427 - Missing return type
def delete_agent_conversation(self, agent_id: str, conversation_id: str):
    ...  # Returns bool
```

**Recommendation:** Add complete type annotations for IDE support and static analysis.

---

### Issue 6: Magic Numbers and Hardcoded Values

**Location 1:** Lines 3712-3723 (Model specifications)
```python
"anthropic/claude-4-opus": {"context_length": 200000, "max_output_tokens": 64000, ...}
"google/gemini-2.0-flash": {"context_length": 1048576, ...}
```

**Location 2:** Lines 3289-3293 (Streaming thresholds)
```python
min_interval = 0.04  # ~25 fps - MAGIC CONSTANT
min_chars = 12       # small bursts - MAGIC CONSTANT
```

**Location 3:** Line 1993 (Retry backoff)
```python
await asyncio.sleep(1 * retry_count)  # Magic multiplier
```

**Recommendation:** Move to constants module:
```python
# constants.py
MIN_STREAM_INTERVAL = 0.04  # ~25 fps
MIN_STREAM_CHARS = 12
RETRY_BACKOFF_BASE = 1.0
```

---

## Potential Bugs

### Bug 1: Race Condition in Streaming State

**Location:** Lines 618-636, 3200-3280

```python
self._streaming_state = {
    "active": False,
    "content": "",
    "emit_buffer": "",
    "last_emit_ts": 0.0,
    ...
}

# Line 3250 - Modified without lock
self._streaming_state["active"] = True

# Line 3289-3290 - Read without lock
buf = self._streaming_state["emit_buffer"]
last_ts = self._streaming_state["last_emit_ts"]
```

**Problem:** Multiple coroutines can access `_streaming_state` simultaneously without synchronization.

**Recommendation:**
```python
async with self.stream_lock:
    self._streaming_state["active"] = True
```

---

### Bug 2: Untracked asyncio.create_task() Calls (10 instances)

**Locations:** Lines 1794, 2143, 2542, 3135, 3384, 3404, 3415, 3425, 3436, 3526

```python
# Line 1794 - Fire-and-forget token update
asyncio.create_task(self.emit_ui_event("token_update", token_data))

# Line 2143 - CRITICAL: Resource cleanup not awaited
asyncio.create_task(browser_manager.close())

# Line 2542 - Callback execution untracked
asyncio.create_task(asyncio.to_thread(stream_callback, message))
```

**Problem:** Untracked tasks can lose exceptions silently. browser_manager.close() not being awaited is a resource leak.

**Recommendation:**
```python
# For cleanup operations - await directly
await browser_manager.close()

# For background tasks - track and handle errors
task = asyncio.create_task(self.emit_ui_event(...))
task.add_done_callback(self._handle_task_error)
```

---

### Bug 3: Callback Signature Reflection on Every Chunk

**Location:** Lines 2504-2521

```python
# Called for EVERY streaming chunk
params = list(inspect.signature(stream_callback).parameters.keys())
if asyncio.iscoroutinefunction(stream_callback):
    if len(params) >= 2:
        await stream_callback(chunk, message_type)
```

**Problem:** `inspect.signature()` is expensive (~200+ microseconds). Called on every token.

**Recommendation:** Cache at callback registration:
```python
def _normalize_callback(self, callback):
    sig = inspect.signature(callback)
    is_async = asyncio.iscoroutinefunction(callback)
    accepts_type = len(sig.parameters) >= 2
    return (callback, is_async, accepts_type)
```

---

### Bug 4: Incomplete Error Handling in get_response()

**Location:** Lines 1988-1998

```python
if not assistant_response or not assistant_response.strip():
    retry_count += 1
    if retry_count <= max_retries:
        await asyncio.sleep(1 * retry_count)
        continue
    else:
        assistant_response = "I apologize, but..."  # Synthetic response
        break
```

**Problem:** After retries fail, a synthetic placeholder is used with no clear indication to the caller that the response is not from the model.

**Recommendation:** Return error status or raise exception:
```python
return {
    "response": None,
    "error": "Empty response after retries",
    "synthetic": True
}
```

---

## Security Concerns

### Concern 1: Path Traversal Risk

**Location:** Lines 864-869

```python
def validate_path(self, path: Path):
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)  # No canonicalization
    if not os.access(path, os.W_OK):
        raise PermissionError(f"No write access to {path}")
```

**Problem:** No path canonicalization (symlink resolution), no parent directory escape checks.

**Recommendation:**
```python
def validate_path(self, path: Path):
    resolved = path.resolve()
    workspace = Path(WORKSPACE_PATH).resolve()
    if not str(resolved).startswith(str(workspace)):
        raise ValueError(f"Path escapes workspace: {path}")
    ...
```

---

### Concern 2: Missing Input Validation

**Location:** Lines 2445-2449

```python
message = input_data.get("text", "")
image_paths = input_data.get("image_paths")
if not message and not image_paths:
    return {"assistant_response": "No input provided", "action_results": []}
```

**Problems:**
- No validation of `image_paths` content (could be arbitrary paths)
- No message length validation (could be gigabytes)
- No sanitization of `context_files` (Line 2476-2477)

**Recommendation:**
```python
MAX_MESSAGE_LENGTH = 1_000_000  # 1MB
if len(message) > MAX_MESSAGE_LENGTH:
    raise ValueError(f"Message exceeds maximum length of {MAX_MESSAGE_LENGTH}")

if image_paths:
    for path in image_paths:
        self.validate_path(Path(path))
```

---

### Concern 3: File Operations Without Atomic Writes

**Location:** Lines 3642, 3671

```python
with open(config_path, 'r') as f:
    ...
with open(config_path, 'w') as f:
    ...
```

**Problem:** Non-atomic writes can corrupt config if interrupted.

**Recommendation:**
```python
import tempfile
with tempfile.NamedTemporaryFile(mode='w', dir=config_path.parent, delete=False) as f:
    f.write(content)
os.replace(f.name, config_path)  # Atomic rename
```

---

## Performance Issues

### Issue 1: O(n²) Complexity in get_agent_profile()

**Location:** Lines 1123-1126

```python
def get_agent_profile(self, agent_id: str) -> Optional[Dict[str, Any]]:
    for entry in self.get_agent_roster():  # Rebuilds entire roster
        if entry.get("id") == agent_id:
            return entry
```

**Problem:** `get_agent_roster()` (lines 1065-1118) rebuilds the entire roster with multiple nested loops. Called repeatedly.

**Recommendation:** Use dict-based lookup:
```python
def get_agent_profile(self, agent_id: str) -> Optional[Dict[str, Any]]:
    if not hasattr(self, '_roster_cache') or self._roster_dirty:
        self._roster_cache = {a['id']: a for a in self.get_agent_roster()}
        self._roster_dirty = False
    return self._roster_cache.get(agent_id)
```

---

### Issue 2: Expensive Debug Logging

**Location:** Line 1972

```python
logger.debug(json.dumps(self.conversation_manager.conversation.get_formatted_messages(), indent=2))
```

**Problem:** JSON serialization of potentially large message history on every API call, even in production (DEBUG still executes the args).

**Recommendation:**
```python
if logger.isEnabledFor(logging.DEBUG):
    logger.debug(json.dumps(...))
```

---

### Issue 3: Repeated Dictionary Operations in Loop

**Location:** Lines 1065-1116

```python
for agent_id in agent_ids:
    conv = cm.agent_sessions.get(agent_id)
    metadata = dict(raw_meta)  # Unnecessary copy
    persona_config = personas.get(persona_name)  # Repeated
    model_override = self._agent_model_overrides.get(agent_id)  # Repeated
```

**Problem:** Multiple redundant dict operations in loop. dict() copies are unnecessary.

---

## Dead Code

### Dead Code 1: Commented Debug Prints

**Location:** Lines 677-680

```python
# print("DEBUG: Initializing ActionExecutor...")
# print(f"DEBUG: ToolManager type: {type(self.tool_manager)}")
# print(f"DEBUG: ProjectManager type: {type(self.project_manager)}")
# print(f"DEBUG: ConversationManager type: {type(self.conversation_manager)}")
```

**Recommendation:** Remove. Version control has history.

---

### Dead Code 2: Commented Legacy Code

**Location:** Lines 895-898

```python
# if self.tool_manager: # ToolManager does not have a reset method currently
#     self.tool_manager.reset()
# if self.action_executor: # ActionExecutor does not have a reset method currently
#     self.action_executor.reset()
```

**Recommendation:** Remove or implement reset methods if needed.

---

### Dead Code 3: Deprecated Method with Implementation

**Location:** Lines 2642-2677 (`multi_step_process`)

```python
async def multi_step_process(self, ...):
    """DEPRECATED: Use process() with multi_step=True instead."""
    # Still has full implementation
```

**Recommendation:** Either remove entirely or delegate to new method without fallback code.

---

## Code Duplication

### Duplication 1: Callback Signature Introspection

**Location:** Lines 2504-2521, 3476-3506

Same pattern repeated:
```python
params = list(inspect.signature(stream_callback).parameters.keys())
if asyncio.iscoroutinefunction(stream_callback):
    if len(params) >= 2:
        await stream_callback(chunk, message_type)
    else:
        await stream_callback(chunk)
```

**Recommendation:** Extract to utility:
```python
async def _invoke_callback(self, callback, chunk, message_type=None):
    info = self._callback_info.get(id(callback))
    if info is None:
        info = self._analyze_callback(callback)
        self._callback_info[id(callback)] = info
    ...
```

---

### Duplication 2: Error Handling Pattern in Prompt/Style Methods

**Location:** Lines 800-862

```python
# set_prompt_mode, get_prompt_mode, set_output_style, get_output_style
# All follow identical try/nested-try/except/pass patterns
try:
    ...
    try:
        if hasattr(...):
            ...
    except Exception:
        pass
    return f"Mode set to '...'"
except Exception as e:
    msg = f"Failed to set ...: {e}"
    logger.warning(msg)
    return msg
```

**Recommendation:** Extract common pattern to helper.

---

## Maintainability Issues

### Issue 1: Complex Streaming State Dict

**Location:** Lines 618-636

```python
self._streaming_state = {
    "active": False,
    "content": "",
    "reasoning_content": "",
    "message_type": None,
    "role": None,
    "metadata": {},
    "started_at": None,
    "last_update": None,
    "empty_response_count": 0,
    "error": None,
    "emit_buffer": "",
    "last_emit_ts": 0.0,
}
```

**Problem:** 12+ fields in a mutable dict with multiple responsibilities.

**Recommendation:** Extract to dataclass:
```python
@dataclass
class StreamingState:
    active: bool = False
    content: str = ""
    reasoning_content: str = ""
    message_type: Optional[str] = None
    # ... with clear reset() method
```

---

### Issue 2: Inconsistent Error Return Formats

**Location:** Multiple methods

Some methods return:
- `{"assistant_response": "Error: ...", "action_results": []}`
- `{"success": False, "warning": "..."}`
- Plain string error messages
- Raise exceptions

**Recommendation:** Standardize on consistent error format:
```python
@dataclass
class CoreResult:
    success: bool
    data: Optional[Any]
    error: Optional[str]
    warning: Optional[str]
```

---

## Recommendations Summary

### High Priority

| Issue | Location | Fix |
|-------|----------|-----|
| Silent exception handlers | 30+ locations | Add logging, don't swallow silently |
| Race condition in streaming | 618-636, 3200-3280 | Use `stream_lock` for state access |
| Print statements | 445-448, 2082 | Replace with logger.debug() |
| Untracked async tasks | 2143, 1794, 2542 | Await or track with error handlers |
| browser_manager leak | 2143 | Await the close() call |

### Medium Priority

| Issue | Location | Fix |
|-------|----------|-----|
| Long methods | 12 methods >100 lines | Extract to smaller methods |
| Callback reflection per-chunk | 2504-2521 | Cache signature analysis |
| O(n²) agent lookup | 1123-1126 | Use dict-based cache |
| Missing type annotations | 13 methods | Add return types |
| Magic numbers | 3289, 3712, 1993 | Extract to constants |
| Path traversal | 864-869 | Add canonicalization |
| Input validation | 2445-2449 | Validate lengths and paths |

### Low Priority

| Issue | Location | Fix |
|-------|----------|-----|
| Duplicate import | 145, 168 | Remove duplicate asyncio |
| Dead code | 677-680, 895-898, 2642-2677 | Remove entirely |
| Callback duplication | 2504-2521, 3476-3506 | Extract to utility |
| Streaming state dict | 618-636 | Convert to dataclass |

---

## Metrics

| Metric | Value |
|--------|-------|
| Total Lines | 3,802 |
| Public Methods | 98 |
| Async Methods | ~35 |
| Sync Methods | ~63 |
| Silent Exception Handlers | 30+ |
| Methods >100 lines | 12 |
| Methods >50 lines | 20 |
| Untracked Async Tasks | 10 |
| Print Statements | 5 |
| Missing Type Annotations | 13 |
| Magic Numbers | 8+ |

---

## Next Steps

1. **Immediate:** Add `stream_lock` usage and await `browser_manager.close()`
2. **Sprint 1:** Replace all print statements with logging; add logging to silent handlers
3. **Sprint 2:** Extract `register_agent()` and other long methods into smaller units
4. **Sprint 3:** Add input validation and path canonicalization
5. **Sprint 4:** Convert `_streaming_state` dict to dataclass; standardize error returns
6. **Ongoing:** Add type annotations as methods are touched
