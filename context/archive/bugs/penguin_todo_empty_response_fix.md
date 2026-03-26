# Empty Response Loop Bug - Investigation & Fix Plan

*Created: 2025-12-13*
*Status: Investigation Complete, Fix Required*

---

## Executive Summary

**Problem:** The auto-continuation loop is not breaking after 3 empty responses as designed, causing hundreds of wasted API calls that return only 3 tokens each.

**Cost Impact (from CSV analysis):**
- 166 requests with exactly 3 output tokens
- Example: 25 consecutive calls at $0.28 each = **$7.00 wasted in ~75 seconds**
- Some sequences show 20+ consecutive 3-token calls

**Root Cause:** Multiple issues working together to defeat the empty response safeguards.

---

## Evidence from CSV Analysis

### Pattern 1: Dec 13, 06:12-06:14 (56,065 input tokens)
```
22+ consecutive requests, 3 tokens each
$0.28 × 22 = $6.16 wasted
Time span: ~72 seconds
Requests every ~3.3 seconds
```

### Pattern 2: Dec 13, 06:17 (74,748 input tokens)
```
11 consecutive requests, 3 tokens each
$0.37 × 11 = $4.07 wasted
```

### Key Observation
**Input tokens stay CONSTANT** within each sequence. This means:
- Assistant messages are NOT being added to conversation
- Same context is being sent repeatedly
- LLM keeps returning the same 3-token response

---

## Root Cause Analysis

### Issue 1: Messages Not Being Added to Conversation

In `core.py:3301`:
```python
if content_to_add.strip():
    # Add to conversation manager
    ...
```

When the 3-token response is whitespace-only (e.g., `"\n\n\n"`), `strip()` returns empty string, so the message is **NOT added**. The conversation stays the same, and the next iteration sends the exact same context.

### Issue 2: Break-After-3 Logic Not Triggering

The engine has this logic (engine.py:402-417):
```python
stripped_response = (last_response or "").strip()
is_empty_or_trivial = not stripped_response or len(stripped_response) < 10

if is_empty_or_trivial:
    self._empty_response_count += 1
    if self._empty_response_count >= 3:
        break
else:
    self._empty_response_count = 0
```

**But 22+ consecutive calls means this isn't working.** Possible reasons:

1. **Response is NOT trivial after processing**
   - The finalized content might be different from what the LLM actually returned
   - Some processing might add content that makes it >= 10 chars

2. **Counter reset between iterations**
   - If something throws and catches an exception, the counter might not increment
   - If a different code path is taken, the counter might be reset

3. **Different entry point**
   - The request might go through a path that doesn't have the counter logic

### Issue 3: 3 Tokens Could Be Anything

The LLM returning exactly 3 tokens could be:
- Whitespace: `"\n"` + `"\n"` + `"\n"`
- Partial text: `"I"` + `"'"` + `"ll"`
- Start of a sentence that gets cut off

If it's partial text like "I'll", that's 4 chars which would be < 10 and trigger the trivial check. But if it's "I'll look", that's 10 chars and would NOT be trivial.

---

## Confirmed Findings (from conversation JSON analysis)

**Conversation JSON files confirm the theory:**
- Normal conversations have only 1-2 very short assistant messages (finish_response acks)
- The looping 3-token messages are NOT being saved to conversation files
- This proves: 3-token responses are whitespace → not saved → same context sent repeatedly

**Entry point confirmed:** User is using `run_response` mode (CLI).

**The fix needs to:**
1. Detect when context hasn't changed (stale context = loop)
2. Ensure the break-after-3 logic actually works
3. Add logging to capture what the 3-tokens actually contain

---

## Proposed Fixes

### Fix 1: Add Token Count Check (Highest Priority)

The CSV shows these responses have exactly 3 **tokens** (not characters). Add a token-based check:

```python
# In engine.py run_response/run_task:

# Get actual token count from the response metadata or estimate
response_tokens = response_data.get("completion_tokens", 0)
if response_tokens == 0:
    # Estimate: average 4 chars per token
    response_tokens = len(last_response) // 4 if last_response else 0

# Consider responses with <= 5 tokens as trivial
is_token_trivial = response_tokens <= 5
is_empty_or_trivial = not stripped_response or len(stripped_response) < 10 or is_token_trivial
```

### Fix 2: Detect Repeated Identical Context

If input tokens haven't changed for 2+ iterations, we're in a loop:

```python
# Track input token count
current_input_tokens = len(cm.conversation.get_formatted_messages())  # or actual token count

if not hasattr(self, '_last_input_tokens'):
    self._last_input_tokens = 0
    self._stale_context_count = 0

if current_input_tokens == self._last_input_tokens:
    self._stale_context_count += 1
    if self._stale_context_count >= 2:
        logger.warning(f"Breaking due to stale context (no new messages added)")
        break
else:
    self._stale_context_count = 0
    self._last_input_tokens = current_input_tokens
```

### Fix 3: Force-Add Empty Messages to Conversation

Instead of silently skipping empty messages, add a placeholder:

```python
# In core.py finalize_streaming_message:
if content_to_add.strip():
    # Add normally...
else:
    # Add a marker for empty response
    self.conversation_manager.conversation.add_message(
        role="assistant",
        content="[No response from model]",
        category=MessageCategory.SYSTEM,
        metadata={"was_empty": True, **final_metadata}
    )
```

This ensures context grows and the same request isn't sent repeatedly.

### Fix 4: Lower the Break Threshold

Change from 3 consecutive to 2 consecutive:

```python
if self._empty_response_count >= 2:  # Was 3
    logger.info("Breaking: 2 consecutive empty/trivial responses")
    break
```

### Fix 5: Add Hard Cost Limit

```python
# Track cumulative cost for session
if not hasattr(self, '_session_cost'):
    self._session_cost = 0.0

response_cost = response_data.get("cost", 0.0)
self._session_cost += response_cost

MAX_SESSION_COST = 5.0  # $5 limit
if self._session_cost > MAX_SESSION_COST:
    logger.error(f"Session cost limit exceeded: ${self._session_cost:.2f}")
    raise RuntimeError("Session cost limit exceeded")
```

---

## Implementation Priority

1. **Fix 2: Stale Context Detection** - Catches the exact pattern seen in CSV
2. **Fix 1: Token Count Check** - More precise than character count
3. **Fix 4: Lower Threshold** - Quick and safe change
4. **Fix 3: Force-Add Messages** - Prevents context stagnation
5. **Fix 5: Cost Limit** - Last-resort safety net

---

## Debugging Suggestions

Add these debug points to understand current behavior:

```python
# In engine.py run_response, after getting response:
logger.info(f"[WALLET_DEBUG] Iter {self.current_iteration}: "
            f"resp_len={len(last_response or '')}, "
            f"stripped_len={len((last_response or '').strip())}, "
            f"empty_count={self._empty_response_count}, "
            f"input_tokens_approx={len(str(messages))}")
```

Run with `LOG_LEVEL=INFO` to see these messages during the loop.

---

## Related Files

- `penguin/engine.py` - run_response (line 280), run_task (line 441), _llm_step (line 793)
- `penguin/core.py` - finalize_streaming_message (line 3269)
- `penguin/llm/openrouter_gateway.py` - streaming handling (line 850)
- `context/investigate_continuation_bug.md` - Previous investigation

---

## Testing Plan

1. Create a test case that simulates 3-token responses
2. Verify counter increments correctly
3. Verify break triggers after threshold
4. Verify context grows (or breaks) appropriately
5. Monitor OpenRouter activity CSV for similar patterns after fix

---

## Implemented Fixes (2025-12-14)

### 1. Force Context Advance (core.py:3301-3309)
```python
# WALLET_GUARD: Context MUST advance or we're guaranteed to loop
if not content_to_add.strip():
    logger.warning(f"[WALLET_GUARD] Empty response from LLM, forcing context advance...")
    content_to_add = "[Empty response from model]"
    final_metadata["was_empty"] = True
```
**This is the root fix.** Now context always grows, preventing the same request from being sent repeatedly.

### 2. Diagnostic Logging (engine.py:407-417, 675-684)
```python
# DIAGNOSTIC: Log trivial responses to understand what Claude is actually returning
if is_empty_or_trivial or len(last_response or "") < 20:
    logger.warning(
        f"[WALLET_GUARD] Trivial response detected: "
        f"raw={repr(last_response)}, "
        f"last_action={last_action}, ..."
    )
```
**Added to both run_response and run_task.** Now you'll see exactly what those 3 tokens contain.

### Key Finding from CSV Analysis
All 3-token responses have `finish_reason=stop` - Claude is *intentionally* outputting 3 tokens and stopping, not being truncated. This points to the model being confused by something in the conversation structure (likely after tool results).

---

## Next Steps

1. **Run with logging enabled** - `LOG_LEVEL=WARNING` to see `[WALLET_GUARD]` messages
2. **Check the raw output** - The `repr(last_response)` will show exactly what Claude returns
3. **Investigate upstream** - Why is Claude returning 3 whitespace tokens after tool results?

---

## Notes

The commit history shows multiple attempts to fix this:
- `9f3bdf4`: Added < 10 char detection
- `ea3be51`: Simplified to break after 3
- `266516a`: Placeholder fixes

**Root cause was never addressed until now:** messages not being added to conversation when response is whitespace-only. The force-add fix ensures context always advances.

---

## Fix #3: Early Return Bypass (2025-12-15)

### The Bug
The WALLET_GUARD fix was being bypassed by an early return in `handle_streaming_chunk`:

```python
# core.py:3192 (BEFORE)
if not chunk.strip() and not self._streaming_state["active"]:
    # Only skip whitespace chunks if we haven't started streaming yet
    return  # <-- BUG: Streaming never activates for whitespace-only responses!
```

**Flow when LLM returns whitespace:**
1. LLM returns 3 tokens of whitespace (e.g., `"\n\n"`)
2. First chunk arrives, is whitespace
3. `not chunk.strip()` = True, `not streaming_active` = True
4. **Early return** → Streaming never activates
5. `finalize_streaming_message()` sees `active=False`, returns `None`
6. **WALLET_GUARD never runs** → Message never added
7. Context doesn't advance → Loop

### The Fix
```python
# core.py:3190-3196 (AFTER)
# WALLET_GUARD FIX: Even whitespace-only first chunks must activate streaming
if not chunk.strip() and not self._streaming_state["active"]:
    logger.debug(f"[WALLET_GUARD] First chunk is whitespace-only, activating streaming anyway")
    # Fall through to activate streaming - WALLET_GUARD in finalize will handle it
```

Now whitespace-only responses still activate streaming, allowing `finalize_streaming_message()` to run and add the `[Empty response from model]` placeholder.

---

## Fix #4: Empty String Bypass (2025-12-15)

### The Bug (ANOTHER early return!)
Even after Fix #3, there was ANOTHER early return at line 3179:

```python
if not chunk:  # True for "" or None (BEFORE the whitespace check!)
    if self._streaming_state["active"]:
        # only tracks if ALREADY active
        ...
    return  # <-- Returns before whitespace check if chunk is ""
```

OpenRouter data showed:
- `tokens_completion: 0` (OpenRouter's count)
- `native_tokens_completion: 3` (Amazon Bedrock's native count)

The 3 native tokens were being stripped to `""` somewhere in the pipeline.

### The Fix
Now empty chunks also activate streaming:

```python
if not chunk:
    # WALLET_GUARD: Even truly empty chunks must activate streaming
    if not self._streaming_state["active"]:
        logger.debug(f"[WALLET_GUARD] First chunk is empty, activating streaming anyway")
        self._streaming_state["active"] = True
        self._streaming_state["content"] = ""
        # ... initialize other state ...
    # Track empty chunks, but streaming is now active
    return
```

Now ALL response types (empty, whitespace, content) activate streaming, ensuring `finalize_streaming_message()` runs and WALLET_GUARD can add the placeholder.

---

## Potential Bug #5: SDK Path `.strip()` Check (2025-12-15)

### The Issue
During code audit, found a potential bypass in the SDK streaming path:

**Location:** `openrouter_gateway.py:534`
```python
if new_content_segment.strip():  # PROBLEM: Skips whitespace!
    await stream_callback(new_content_segment, "assistant")
```

The SDK path has a `.strip()` check that **never calls `stream_callback`** when content is whitespace-only. This bypasses all WALLET_GUARD fixes because:

1. Model returns whitespace tokens via SDK path
2. `new_content_segment = "\n\n"`
3. `.strip()` returns "" → callback NOT called
4. `handle_streaming_chunk` never runs
5. `_streaming_state["active"]` stays False
6. `finalize_streaming_message()` returns None
7. No message added to conversation
8. Context doesn't advance → Loop!

### Compare to Direct API Path
The direct API path (line 891-893) has **NO** `.strip()` check:
```python
if stream_callback:
    await stream_callback(content_delta, "assistant")  # Always called!
```

### Affected Code Paths
- **SDK path:** Non-reasoning models → **VULNERABLE**
- **Direct API path:** Reasoning models (Claude Opus 4.5) → **NOT affected** (no .strip() check)

### Proposed Fix
Remove the `.strip()` check at line 534 to match the direct API path:
```python
# BEFORE:
if new_content_segment.strip():
    await stream_callback(new_content_segment, "assistant")

# AFTER:
if stream_callback:
    await stream_callback(new_content_segment, "assistant")
```

Let the callback (`handle_streaming_chunk`) handle whitespace content - it now has WALLET_GUARD logic to deal with it.

### The Fix (2025-12-15)
Removed the `.strip()` check at `openrouter_gateway.py:534`:
```python
# WALLET_GUARD FIX: Always call stream_callback, even for whitespace
# The downstream handle_streaming_chunk has WALLET_GUARD logic to handle it
# Previously: `if new_content_segment.strip():` skipped whitespace, bypassing fixes
if stream_callback:
    await stream_callback(new_content_segment, "assistant")
```

Now both SDK and direct API paths call the callback for all content, including whitespace.

### Status
**FIXED** - SDK path now matches direct API path behavior.

---

## Fix #6: No-Action Completion for Non-CodeAct Models (2025-12-15)

### The Bug
Free/simple models (like `mistralai/devstral-2512:free`) don't know about CodeAct action format. They respond with plain text like "Hello! How can I assist you today?" without `<finish_response>` tags.

**Result:** Engine kept iterating because:
1. No `finish_response` action parsed
2. Response was 34+ chars (not "trivial")
3. No termination condition met
4. Model outputs same response again → infinite loop

### The Fix
Added no-action completion check in both `run_response` and `run_task`:

**Location:** `engine.py:402-410` (run_response), `engine.py:680-688` (run_task)
```python
# WALLET_GUARD: No-action completion for models that don't use CodeAct format
# If the model responded without any action tags, treat as conversation complete
if not iteration_results and last_response:
    has_action_tags = bool(re.search(r'<\w+>.*?</\w+>', last_response, re.DOTALL))
    if not has_action_tags:
        logger.debug(f"[WALLET_GUARD] No actions in response, treating as conversation complete")
        break
```

### Logic
- If model returns text WITHOUT any `<tag>...</tag>` patterns → it's just conversing
- Models that use CodeAct will have action tags → continue iterating
- Models that don't → complete after first response

### Status
**FIXED** - Free models now complete after responding instead of looping.

---

## Fix #7: Pre-Execution Tool Result Detection (2025-12-15)

### The Bug
Fix #6's `[Tool Result]` check in the main loop happened AFTER `_llm_step()` returned with actions already executed. When a confused model output both action tags AND echoed results:

```
<execute_command>python script.py</execute_command> [Tool Result] Random number: 180076...
```

The flow was:
1. `_llm_step()` called
2. `parse_action()` extracts `<execute_command>`
3. Action executes (random number generated)
4. `_llm_step()` returns
5. **NOW** `[Tool Result]` check runs → breaks
6. But action already executed!

This caused an extra iteration before the break caught it.

### The Fix
Moved `[Tool Result]` detection BEFORE action parsing in `_llm_step`:

**Location:** `engine.py:1058-1067`
```python
# WALLET_GUARD: Skip action parsing if model is echoing tool results
# Confused models may output action tags AND echoed results - don't execute
if assistant_response and "[Tool Result]" in assistant_response:
    logger.warning(
        f"[WALLET_GUARD] Skipping action parsing: response contains echoed '[Tool Result]' "
        f"(model confused about format, len={len(assistant_response)})"
    )
    actions = []
else:
    actions: List[CodeActAction] = parse_action(assistant_response)
```

### Result
Now when a model outputs action + echoed result:
1. `_llm_step()` sees `[Tool Result]` in response
2. Skips action parsing entirely → `actions = []`
3. No action executed
4. Main loop's `[Tool Result]` check also triggers → break
5. No wasted execution!

### Status
**FIXED** - Actions no longer execute when model is confused about format.
