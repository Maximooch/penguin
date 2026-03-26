# LLM Module Code Audit

*Audit Date: 2025-12-19*
*Files Audited:*
- `penguin/llm/openrouter_gateway.py` (1,185 lines)
- `penguin/llm/stream_handler.py` (471 lines)
- `penguin/llm/api_client.py` (502 lines)
- `penguin/llm/model_config.py` (683 lines)
- `penguin/llm/client.py` (397 lines)

---

## Executive Summary

The LLM module provides a well-layered abstraction over multiple LLM providers (OpenRouter, LiteLLM, native adapters). The OpenRouterGateway correctly implements SSE streaming with keep-alive handling and error detection per OpenRouter documentation. **OpenRouter API compliance is excellent.**

**Key Concerns:** Duplicate code patterns between SDK and direct API paths, incomplete error propagation, missing imports in fallback code, and a potential race condition in header updates.

**Overall Assessment:** Solid implementation with proper OpenRouter API compliance. Priority areas: consolidate streaming logic, fix broken token counter fallback, and add path validation for image handling.

---

## Architecture Overview

```
LLMClient (client.py)
├── Configuration Management
│   ├── LLMClientConfig - base URL, timeouts
│   └── LinkConfig - billing/attribution headers
├── Gateway Selection
│   ├── OpenRouterGateway (openrouter_gateway.py)
│   ├── LiteLLMGateway (litellm_gateway.py)
│   └── Native Adapters (adapters.py)
└── APIClient (api_client.py)
    ├── System prompt injection
    ├── Message preparation
    └── Token counting delegation

OpenRouterGateway
├── Vision handling (_encode_image, _process_messages_for_vision)
├── Conversation format cleaning (_clean_conversation_format)
├── SDK path (OpenAI client)
├── Direct API path (httpx for reasoning support)
└── Streaming handlers

StreamingStateManager (stream_handler.py)
├── State machine (INACTIVE → ACTIVE → FINALIZING)
├── Coalescing logic (~25 fps throttling)
├── WALLET_GUARD empty response handling
└── Event generation for UI
```

---

## OpenRouter API Compliance

### Verified Against Official Documentation

| Feature | Status | Implementation Location |
|---------|--------|------------------------|
| SSE Streaming | ✅ COMPLIANT | openrouter_gateway.py:469-658, 826-1008 |
| Keep-alive comments | ✅ COMPLIANT | openrouter_gateway.py:860-862 |
| finish_reason handling | ✅ COMPLIANT | openrouter_gateway.py:486-501, 886-903 |
| Mid-stream errors | ✅ COMPLIANT | openrouter_gateway.py:893-903 |
| Unified reasoning param | ✅ COMPLIANT | model_config.py:175-197 |
| Debug mode | ✅ COMPLIANT | openrouter_gateway.py:838-840, 876-880 |
| Error response parsing | ✅ COMPLIANT | openrouter_gateway.py:137-196 |

### Compliance Details

**1. Keep-Alive Comment Handling (CORRECT)**

Per [OpenRouter Streaming Docs](https://openrouter.ai/docs/api/reference/streaming): SSE comments like `: OPENROUTER PROCESSING` should be ignored.

```python
# Line 860-862 - Correct implementation
if line.startswith(":"):
    self.logger.debug(f"OpenRouter keep-alive: {line}")
    continue
```

**2. finish_reason Values (CORRECT)**

Per OpenRouter docs, normalized values are: `tool_calls`, `stop`, `length`, `content_filter`, `error`

```python
# Lines 486-501 - Proper handling
if chunk_finish_reason == "error":
    # ... handle mid-stream error
if sdk_last_finish_reason == "length":
    # ... handle truncation with helpful message
```

**3. Mid-Stream Error Structure (CORRECT)**

Per [OpenRouter Error Docs](https://openrouter.ai/docs/api/reference/errors-and-debugging):
```typescript
type MidStreamError = {
  error: { code: string | number; message: string };
  choices: [{ finish_reason: 'error'; delta: { content: '' } }];
};
```

Implementation correctly extracts error info:
```python
# Lines 893-903
if finish_reason == "error":
    error_info = data.get("error", {})
    error_message = error_info.get("message", "Unknown streaming error")
    provider_name = error_info.get("metadata", {}).get("provider_name", "unknown provider")
```

**4. Unified Reasoning Parameter (CORRECT)**

Per [OpenRouter Reasoning Tokens](https://openrouter.ai/announcements/reasoning-tokens-for-thinking-models), the unified format supports `effort` and `max_tokens`.

```python
# model_config.py Lines 175-197
def get_reasoning_config(self) -> Optional[Dict[str, Any]]:
    config = {}
    if self._uses_effort_style():
        config["effort"] = self.reasoning_effort or "high"
    elif self._uses_max_tokens_style():
        config["max_tokens"] = self.reasoning_max_tokens or 16000
    if self.reasoning_exclude:
        config["exclude"] = True
    return config
```

**5. Debug Mode (CORRECT)**

Per OpenRouter docs, `debug.echo_upstream_body: true` returns debug chunk first with empty choices.

```python
# Lines 838-840, 876-880
if getattr(self.model_config, "debug_upstream", False):
    params["debug"] = {"echo_upstream_body": True}
# ...
if not choices and getattr(self.model_config, "debug_upstream", False):
    debug_body = data.get("debug", {}).get("upstream_body")
```

---

## Code Quality Issues

### Issue 1: Duplicate Streaming Logic

**Locations:** Lines 469-658 (SDK path) and 826-1008 (Direct API path)

**Problem:** Near-identical streaming logic duplicated between SDK path and direct httpx path.

```python
# SDK path (Lines 524-590)
if reasoning_delta and not reasoning_phase_complete:
    new_reasoning_segment = ""
    if reasoning_delta.startswith(_gateway_accumulated_reasoning):
        new_reasoning_segment = reasoning_delta[len(_gateway_accumulated_reasoning):]
    # ... ~60 more lines

# Direct API path (Lines 905-944)
if reasoning_delta and not reasoning_phase_complete:
    full_reasoning += reasoning_delta
    # ... similar but different pattern
```

**Recommendation:** Extract to shared method:
```python
async def _process_stream_chunk(
    self, content_delta, reasoning_delta, tool_calls_delta,
    accumulated_content, accumulated_reasoning, stream_callback
) -> Tuple[str, str, bool]:
    """Unified chunk processing for both SDK and direct API paths."""
    ...
```

---

### Issue 2: Inconsistent Error String Prefixes

**Locations:** Throughout openrouter_gateway.py

**Problem:** Multiple error return formats make parsing difficult:
- `"[Error: ...]"` - Lines 157-196, 407, 760, 769
- `"[Note: ...]"` - Lines 650, 656, 730, 999, 1006
- Plain error strings

**Recommendation:** Standardize on typed error responses:
```python
@dataclass
class GatewayResponse:
    content: str
    success: bool
    error_type: Optional[str] = None  # "api_error", "timeout", "truncated"
    truncated: bool = False
```

---

### Issue 3: Silent Exception Swallowing

**Locations:**
- openrouter_gateway.py: Lines 562-564, 584-586, 607-608, 622-624, 925-926, 937-940, 962-963, 972-975
- model_config.py: Lines 593-600

```python
# Line 562-564 - Silent telemetry failure
try:
    self._telemetry["streamed_bytes"] += len(new_content_segment.encode("utf-8"))
except Exception:
    pass
```

**Recommendation:** At minimum, log debug messages for all caught exceptions.

---

### Issue 4: Missing Type Annotations

**Locations:**
- openrouter_gateway.py: `_parse_api_model` return type implicit
- api_client.py: 5+ methods missing return type annotations
- model_config.py: Internal methods like `_detect_reasoning_support`

---

## Potential Bugs

### Bug 1: api_client.py Token Counter Import Missing (CRITICAL)

**Location:** Lines 401-429

**Problem:** The code references `token_counter` from litellm but it's never imported:

```python
return token_counter(model=model_for_counting, text=content)  # NameError!
```

The import at top of file is commented out:
```python
# from litellm import acompletion, completion, token_counter, cost_per_token, completion_cost
```

**Impact:** Any call to the token counting fallback path will raise `NameError`.

**Recommendation:** Either uncomment the import or remove the fallback code that references it.

---

### Bug 2: SDK Path Missing finish_reason 'content_filter' Handling

**Location:** Lines 634-658

**Problem:** The SDK streaming path checks for `error` and `length` finish_reason but doesn't handle `content_filter`.

**Per OpenRouter Docs:** `content_filter` indicates moderation flagged the content.

**Recommendation:**
```python
if sdk_last_finish_reason == "content_filter":
    return f"{full_response_content}\n\n[Warning: Response was filtered by content moderation.]"
```

---

### Bug 3: Race Condition in client.py Gateway Header Updates

**Location:** Lines 266-311

**Problem:** `_get_gateway()` uses a lock but `chat_completion()` re-fetches headers outside the lock and modifies `gateway.extra_headers` without proper synchronization.

```python
# Lines 347-352 - Modifying gateway outside lock
if hasattr(gateway, 'extra_headers') and link_headers:
    if isinstance(gateway.extra_headers, dict):
        gateway.extra_headers.update(link_headers)  # Not thread-safe
```

**Recommendation:** Either:
1. Hold the gateway lock during header updates
2. Create a new gateway when headers change
3. Make headers immutable at creation time

---

### Bug 4: StreamingStateManager Not Used Consistently

**Location:** stream_handler.py defines `StreamingStateManager` but openrouter_gateway.py implements its own streaming state.

**Problem:** The `StreamingStateManager` with proper state machine (INACTIVE → ACTIVE → FINALIZING) and WALLET_GUARD logic exists but isn't used in the gateway. The gateway duplicates this logic inline.

**Recommendation:** Integrate `StreamingStateManager` into `OpenRouterGateway` to consolidate streaming logic and reduce code duplication.

---

## Performance Issues

### Issue 1: Regex Compilation on Every Streaming Chunk

**Location:** openrouter_gateway.py Lines 264-282

```python
def _contains_penguin_action_tags(self, content: str) -> bool:
    from penguin.utils.parser import ActionType
    import re
    action_tag_pattern = "|".join([action_type.value for action_type in ActionType])
    action_tag_regex = f"<({action_tag_pattern})>.*?</\\1>"
    return bool(re.search(action_tag_regex, content, re.DOTALL | re.IGNORECASE))
```

**Problem:** Compiles regex and imports module on every call. Called on every streaming chunk when `interrupt_on_action` is enabled.

**Recommendation:** Compile regex once at module level:
```python
from penguin.utils.parser import ActionType
_ACTION_TAG_PATTERN = re.compile(
    f"<({'|'.join(a.value for a in ActionType)})>.*?</\\1>",
    re.DOTALL | re.IGNORECASE
)
```

---

### Issue 2: ModelSpecsService Disk I/O on Every Cache Update

**Location:** model_config.py Lines 647-664

**Problem:** `_save_disk_cache()` is called on every cache update, writing the entire cache synchronously.

**Recommendation:** Debounce disk writes or use async I/O:
```python
def _save_disk_cache_debounced(self) -> None:
    if self._save_pending:
        return
    self._save_pending = True
    asyncio.get_event_loop().call_later(5.0, self._do_save_disk_cache)
```

---

## Security Concerns

### Concern 1: Image Path Validation Missing

**Location:** openrouter_gateway.py Lines 198-226

```python
async def _encode_image(self, image_path: str) -> Optional[str]:
    if not os.path.exists(image_path):
        # ...
    with PILImage.open(image_path) as img:
```

**Problem:** No path traversal validation. Arbitrary file paths can be read if passed through the vision API.

**Recommendation:**
```python
def _validate_image_path(self, image_path: str) -> Path:
    resolved = Path(image_path).resolve()
    workspace = Path(os.environ.get("PENGUIN_WORKSPACE", ".")).resolve()
    if not str(resolved).startswith(str(workspace)):
        raise ValueError(f"Image path escapes workspace: {image_path}")
    return resolved
```

---

### Concern 2: API Key Exposure in Debug Logs

**Location:** openrouter_gateway.py Line 793

```python
headers = {
    "Authorization": f"Bearer {self.client.api_key}",
```

**Problem:** If debug logging is enabled and headers are logged elsewhere, API key would be exposed.

**Recommendation:** Mask sensitive headers in any logging:
```python
safe_headers = {k: "***" if "auth" in k.lower() else v for k, v in headers.items()}
self.logger.debug(f"Request headers: {safe_headers}")
```

---

## Dead Code

### Dead Code 1: Commented Debug Functions

**Location:** openrouter_gateway.py Lines 20-32

```python
# from .debug_utils import get_debugger, debug_request, debug_stream_start, ...
# def get_debugger(): return None
# def debug_request(*args, **kwargs): return f"debug_{id(args)}"
```

**Recommendation:** Remove commented code. Version control has history.

---

### Dead Code 2: Commented litellm Import

**Location:** api_client.py Lines 12-17

```python
# Lazy import litellm to avoid 1+ second import time overhead
# from litellm import acompletion, completion, token_counter, cost_per_token, completion_cost
```

But `token_counter` is referenced in fallback code that will fail.

**Recommendation:** Either uncomment and use lazy import, or remove all references.

---

## Code Duplication

### Duplication 1: Error Parsing Logic

**Locations:**
- openrouter_gateway.py Lines 137-196 (`_parse_openrouter_error`)
- openrouter_gateway.py Lines 893-903 (inline error extraction)

**Recommendation:** Use `_parse_openrouter_error` consistently for all error handling.

---

### Duplication 2: Token Counter Fallback Pattern

**Location:** api_client.py Lines 376-429

Same fallback pattern repeated 3 times:
```python
try:
    return self.client_handler.count_tokens(content)
except Exception as e:
    # Fallback 1
    try:
        return token_counter(...)  # Broken!
    except Exception as litellm_e:
        # Fallback 2
        return len(str(content)) // 4
```

**Recommendation:** Extract to single fallback chain method.

---

## Recommendations Summary

### High Priority

| Issue | Location | Fix |
|-------|----------|-----|
| Missing litellm import | api_client.py:401-429 | Add import or remove dead code |
| Image path traversal | openrouter_gateway.py:198-226 | Add path validation |
| Thread-safety in client.py | client.py:347-352 | Fix header update synchronization |
| Duplicate streaming logic | openrouter_gateway.py | Extract shared methods |

### Medium Priority

| Issue | Location | Fix |
|-------|----------|-----|
| Regex compilation per-call | openrouter_gateway.py:264-282 | Compile at module level |
| Silent exception handling | 15+ locations | Add debug logging |
| Missing content_filter handling | openrouter_gateway.py:634-658 | Add finish_reason case |
| Inconsistent error formats | Throughout | Standardize on typed response |
| StreamingStateManager unused | stream_handler.py | Integrate into gateway |

### Low Priority

| Issue | Location | Fix |
|-------|----------|-----|
| Dead commented code | openrouter_gateway.py:20-32 | Remove |
| Missing type annotations | Multiple files | Add annotations |
| Disk I/O on every cache update | model_config.py:647-664 | Debounce writes |

---

## Metrics

| File | Lines | Issues Found |
|------|-------|--------------|
| openrouter_gateway.py | 1,185 | 12 |
| stream_handler.py | 471 | 1 (unused by gateway) |
| api_client.py | 502 | 4 |
| model_config.py | 683 | 2 |
| client.py | 397 | 2 |
| **Total** | **3,238** | **21** |

| Metric | Value |
|--------|-------|
| Total Lines | 3,238 |
| Silent Exception Handlers | 15+ |
| Dead/Commented Code Blocks | 3 |
| Missing Type Annotations | 10+ |
| Duplicated Logic Patterns | 3 |

---

## Next Steps

1. **Immediate:** Fix broken token_counter import in api_client.py
2. **Sprint 1:** Add image path validation; extract shared streaming logic
3. **Sprint 2:** Integrate StreamingStateManager into OpenRouterGateway
4. **Sprint 3:** Standardize error response format across gateways
5. **Ongoing:** Add type annotations as methods are touched

---

## Sources

- [OpenRouter API Streaming](https://openrouter.ai/docs/api/reference/streaming)
- [OpenRouter Error Handling](https://openrouter.ai/docs/api/reference/errors-and-debugging)
- [OpenRouter API Parameters](https://openrouter.ai/docs/api/reference/parameters)
- [OpenRouter Reasoning Tokens](https://openrouter.ai/announcements/reasoning-tokens-for-thinking-models)
