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
