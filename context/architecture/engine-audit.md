# Engine.py Code Audit

*Audit Date: 2025-12-16*
*File: `penguin/engine.py`*
*Lines: 1,263*

---

## Executive Summary

The Engine is the high-level coordination layer for Penguin's reasoning loops. It manages multi-step conversations, tool execution, and multi-agent orchestration. Recent refactoring (LoopState, consolidated helpers) improved the codebase, but several issues remain.

**Overall Assessment:** Functional but has technical debt. Priority areas: error handling, async safety, and method extraction.

---

## Architecture Overview

```
Engine
├── Settings & Configuration
│   ├── EngineSettings (dataclass)
│   ├── LoopConfig (dataclass) - NEW
│   └── LoopState (dataclass) - NEW
├── Stop Conditions
│   ├── StopCondition (base)
│   ├── TokenBudgetStop
│   ├── WallClockStop
│   └── ExternalCallbackStop
├── Agent Management
│   ├── register_agent()
│   ├── get_agent() / list_agents()
│   └── _resolve_components()
├── Public API
│   ├── run_single_turn()
│   ├── run_response() - conversational loop
│   ├── run_task() - task execution loop
│   └── stream()
└── Internal Helpers
    ├── _llm_step() - single LLM call + action execution
    ├── _llm_stream()
    ├── _check_stop()
    ├── _check_wallet_guard_termination() - NEW
    └── _save_conversation() - NEW
```

---

## Code Quality Issues

### Issue 1: `_llm_step()` is Too Long (265 lines)

**Location:** Lines 934-1198

**Problem:** This method handles too many responsibilities:
1. Message formatting
2. Responses API tool preparation
3. LLM API calls (with retry logic)
4. Empty response handling
5. Streaming finalization
6. Action parsing
7. Action execution
8. UI event emission
9. Conversation persistence
10. Tool choice mapping

**Recommendation:** Extract into smaller methods:
```python
async def _llm_step(...):
    messages = self._prepare_messages(cm)
    extra_kwargs = self._prepare_tool_kwargs()

    response = await self._call_llm_with_retry(api_client, messages, streaming, stream_callback, extra_kwargs)
    response = await self._handle_responses_tool_call(cm, _tm, response)
    response = await self._finalize_streaming(cm, response, streaming)

    action_results = await self._execute_parsed_actions(cm, action_executor, response, tools_enabled)

    cm.save()
    return {"assistant_response": response, "action_results": action_results}
```

---

### Issue 2: Hardcoded Magic Strings

**Locations:**
- Line 362: `r'<\w+>.*?</\w+>'` (action tag pattern)
- Line 368: `"[Tool Result]"`
- Line 773: `r'\[FINISH_STATUS:(\w+)\]'`
- Line 1113: `"[Tool Result]"`

**Problem:** Same patterns duplicated, hard to maintain.

**Recommendation:** Move to constants module:
```python
# constants.py
ACTION_TAG_PATTERN = r'<\w+>.*?</\w+>'
TOOL_RESULT_MARKER = "[Tool Result]"
FINISH_STATUS_PATTERN = r'\[FINISH_STATUS:(\w+)\]'
```

---

### Issue 3: Exception Handling Anti-Patterns

**Problem 1: Bare `except Exception` blocks**

```python
# Line 314, 327, 412, 959, 966, 981, 991, 1028, 1073, 1106, 1167, 1193
except Exception:
    pass  # Silent failure
```

**Problem 2: Overly broad exception catching**

```python
# Line 589-597 (run_response)
except Exception as e:
    logger.error(f"Error in run_response: {str(e)}")
    return {
        "assistant_response": f"Error occurred: {str(e)}",
        ...
    }
```

This catches everything including `KeyboardInterrupt`, `SystemExit`, etc.

**Recommendation:**
```python
except (ValueError, RuntimeError, LLMError) as e:
    # Handle specific errors
except Exception as e:
    logger.exception("Unexpected error")  # Logs full traceback
    raise
```

---

### Issue 4: Inconsistent Logging Levels

**Problem:** Mixed use of `logger.debug`, `logger.warning`, `logger.error`, and `print()` statements.

```python
# Line 848 - print statement in production code
print("(Engine) EventBus not available yet, continue with normal operation")
```

**Recommendation:** Remove all print statements, use consistent logging:
- `DEBUG`: Internal state changes
- `INFO`: Significant events (task start/complete)
- `WARNING`: Recoverable issues (empty response retry)
- `ERROR`: Failures that affect user experience

---

### Issue 5: Type Annotation Gaps

**Problem:** Several methods lack complete type annotations:

```python
# Line 302 - missing return type
def _resolve_components(self, agent_id: Optional[str] = None):
    ...  # Returns tuple but not annotated

# Line 934 - missing return type
async def _llm_step(self, *, tools_enabled: bool = True, ...):
    ...  # Returns Dict[str, Any] but not annotated
```

**Recommendation:** Add complete type annotations for better IDE support and static analysis.

---

## Potential Bugs

### Bug 1: Race Condition in UI Event Emission

**Location:** Lines 1010-1020, 1156-1166

```python
await cm.core.emit_ui_event("tool", {...})
await asyncio.sleep(0.01)  # "Yield control to allow UI to render"
```

**Problem:** This 10ms sleep is a hack that may not be sufficient under load, and adds unnecessary latency in fast operations.

**Recommendation:** Use proper async synchronization or event queuing.

---

### Bug 2: Unguarded `hasattr` Checks

**Location:** Lines 545, 1008, 1085, 1143

```python
if hasattr(cm, 'core') and cm.core:
    cm.core.finalize_streaming_message()
```

**Problem:** If `cm.core` exists but the method doesn't exist, this will crash.

**Recommendation:**
```python
if hasattr(cm, 'core') and cm.core and hasattr(cm.core, 'finalize_streaming_message'):
    cm.core.finalize_streaming_message()
```

Or use `getattr` with default:
```python
finalize = getattr(getattr(cm, 'core', None), 'finalize_streaming_message', None)
if finalize:
    finalize()
```

---

### Bug 3: Potential None Dereference

**Location:** Line 1066

```python
session_messages = cm.conversation.session.messages if hasattr(cm.conversation, 'session') else []
last_msg = session_messages[-1] if session_messages else None
```

**Problem:** If `session_messages` is truthy but empty-ish (like a custom list type), `[-1]` could fail.

**Recommendation:**
```python
last_msg = session_messages[-1] if session_messages and len(session_messages) > 0 else None
```

---

### Bug 4: Import Inside Function (Performance)

**Location:** Lines 685, 744, 787, 835, 988, 1053, 1146

```python
# Inside the loop body
from penguin.utils.events import EventBus, TaskEvent
```

**Problem:** Python caches imports, but the lookup still has overhead. More importantly, if the import fails, it fails at runtime rather than startup.

**Recommendation:** Move imports to top of file or use lazy loading pattern properly.

---

## Security Concerns

### Concern 1: No Input Validation on Agent ID

**Location:** Lines 257-275

```python
def register_agent(self, *, agent_id: str, ...):
    self.agents[agent_id] = EngineAgent(...)
```

**Problem:** No validation of `agent_id` string. Could potentially allow injection if used in file paths or shell commands downstream.

**Recommendation:**
```python
import re
if not re.match(r'^[a-zA-Z0-9_-]+$', agent_id):
    raise ValueError(f"Invalid agent_id: {agent_id}")
```

---

### Concern 2: Tool Result Displayed Without Sanitization

**Location:** Line 1162

```python
"result": str(action_result['output'])[:200]  # Truncate for display
```

**Problem:** Tool output is passed directly to UI without sanitization. If tool output contains terminal escape sequences or other control characters, could affect terminal display.

**Recommendation:** Sanitize before display:
```python
from penguin.utils.sanitize import strip_ansi_and_control_chars
"result": strip_ansi_and_control_chars(str(action_result['output']))[:200]
```

---

## Performance Issues

### Issue 1: Redundant Component Resolution

**Location:** Lines 506, 654, 759, 942, 1207

```python
cm, _api, _tm, _ae = self._resolve_components(self.current_agent_id)
```

**Problem:** `_resolve_components()` is called multiple times per iteration, but the result doesn't change within an iteration.

**Recommendation:** Cache the result at the start of each iteration:
```python
# At iteration start
self._current_components = self._resolve_components(self.current_agent_id)
# Then use self._current_components throughout
```

---

### Issue 2: Regex Compilation in Hot Path

**Location:** Line 362

```python
has_action_tags = bool(re.search(r'<\w+>.*?</\w+>', last_response, re.DOTALL))
```

**Problem:** Regex is compiled on every check. In a loop with many iterations, this adds up.

**Recommendation:**
```python
# At module level
_ACTION_TAG_RE = re.compile(r'<\w+>.*?</\w+>', re.DOTALL)

# In method
has_action_tags = bool(_ACTION_TAG_RE.search(last_response))
```

---

### Issue 3: Multiple Conversation Saves

**Location:** Lines 553, 760, 1197

```python
await self._save_conversation(cm, async_save=True)  # In loop
cm.save()  # In _llm_step
```

**Problem:** Conversation is saved multiple times per iteration (once in `_llm_step`, once after).

**Recommendation:** Remove save from `_llm_step`, let caller handle persistence:
```python
# In _llm_step, remove:
# cm.save()

# Caller decides when to persist
await self._save_conversation(cm, async_save=True)
```

---

## Dead Code

### Dead Code 1: Unused Import

**Location:** Line 18

```python
import multiprocessing as mp
```

**Usage:** Not used anywhere in the file.

---

### Dead Code 2: Commented Code Block

**Location:** Lines 804-809

```python
# NOTE: Phrase-based completion detection is deprecated.
# Keeping commented out for reference. Use finish_task tool instead.
# if any(phrase in last_response for phrase in all_completion_phrases):
#     completion_status = "completed"
#     logger.debug(f"Task completion detected. Found completion phrase: {all_completion_phrases}")
#     break
```

**Recommendation:** Remove entirely. Version control has the history.

---

### Dead Code 3: Unused Parameter

**Location:** Line 1257 (run_agent_turn)

```python
image_path: Optional[str] = None,
```

But `run_single_turn` takes `image_paths: Optional[List[str]]`, so this parameter mapping is broken.

---

## Code Duplication

### Duplication 1: Event Publishing Pattern

**Location:** Lines 683-697, 742-756, 785-801, 833-849

Same pattern repeated 4 times:
```python
if enable_events:
    try:
        from penguin.utils.events import EventBus, TaskEvent
        event_bus = EventBus.get_instance()
        await event_bus.publish(TaskEvent.XXX.value, {...})
    except (ImportError, AttributeError):
        pass
```

**Recommendation:** Extract to helper:
```python
async def _publish_event(self, event_type: str, data: Dict, enable_events: bool = True):
    if not enable_events:
        return
    try:
        from penguin.utils.events import EventBus, TaskEvent
        event_bus = EventBus.get_instance()
        await event_bus.publish(event_type, data)
    except (ImportError, AttributeError):
        logger.debug("EventBus not available")
```

---

### Duplication 2: Tool Event Emission

**Location:** Lines 1009-1020, 1156-1166

Same UI event emission logic duplicated:
```python
await cm.core.emit_ui_event("tool", {
    "id": f"{action_result['action_name']}-{int(time.time() * 1000)}",
    "phase": "end",
    ...
})
```

**Recommendation:** Extract to helper method.

---

## Maintainability Issues

### Issue 1: LoopConfig Not Used

**Location:** Lines 47-79

`LoopConfig` dataclass was created as part of refactoring plan but is not actually used in the code. `run_response` and `run_task` still have their own inline logic.

**Recommendation:** Either use `LoopConfig` to drive a unified `_iteration_loop()` or remove it.

---

### Issue 2: Inconsistent Error Return Formats

**Location:** Lines 581-586 vs 591-597

```python
# Success case
return {
    "assistant_response": last_response,
    "iterations": self.current_iteration,
    "action_results": all_action_results,
    "status": final_status,
    "execution_time": (datetime.utcnow() - self.start_time).total_seconds()
}

# Error case
return {
    "assistant_response": f"Error occurred: {str(e)}",
    "iterations": self.current_iteration,
    "action_results": all_action_results,
    "status": "error",
    "execution_time": (datetime.utcnow() - self.start_time).total_seconds()
}
```

**Problem:** Error message is embedded in `assistant_response` instead of a separate `error` field.

**Recommendation:** Standardize return format:
```python
return {
    "assistant_response": last_response,  # Keep last valid response
    "error": str(e),  # Add error field
    "status": "error",
    ...
}
```

---

## Recommendations Summary

### High Priority

| Issue | Location | Fix |
|-------|----------|-----|
| `_llm_step` too long | 934-1198 | Extract 5-7 helper methods |
| Silent exception swallowing | Multiple | Log or re-raise, don't `pass` |
| Remove print statements | 848 | Use logger.warning |
| Multiple saves per iteration | 553, 760, 1197 | Single save point |

### Medium Priority

| Issue | Location | Fix |
|-------|----------|-----|
| Hardcoded strings | 362, 368, 773, 1113 | Move to constants |
| Missing type annotations | 302, 934 | Add return types |
| Event publish duplication | 683-849 | Extract helper |
| LoopConfig unused | 47-79 | Use or remove |

### Low Priority

| Issue | Location | Fix |
|-------|----------|-----|
| Unused import (mp) | 18 | Remove |
| Commented code | 804-809 | Remove |
| Broken parameter | 1257 | Fix or remove |
| Regex compilation | 362 | Pre-compile at module level |

---

## Metrics After Refactoring (Previous Session)

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Lines in run_response | ~120 | ~85 | -35 |
| Lines in run_task | ~170 | ~135 | -35 |
| Duplicate WALLET_GUARD code | ~80 | 0 | -80 |
| Dynamic attribute patterns | 4 | 0 | -4 |

**Net reduction:** ~150 lines from consolidation

---

## Next Steps

1. Extract `_llm_step` into smaller methods
2. Implement unified `_iteration_loop()` using `LoopConfig`
3. Move magic strings to constants
4. Add comprehensive type annotations
5. Remove dead code and unused imports
