# Auto-Continuation Bug Investigation

*Created to track down why Penguin sometimes continues when it shouldn't*

---

## Symptoms

1. **"Direct streaming response completed with no content"** warning appears
   - Often appears 3 times in a row
   - Model: anthropic/claude-opus-4.5
   - Happens after Penguin seems to have finished

2. **Unnecessary continuation attempts**
   - System tries to continue when response is complete
   - May require user to say "continue" to keep track of conversation

3. **Location of warning:**
   - `penguin/llm/openrouter_gateway.py`

---

## Questions to Answer

1. Where is the continuation logic?
2. What triggers a continuation attempt?
3. Why would streaming return empty content?
4. Why does it happen exactly 3 times?
5. What signal should stop continuation?

---

## Investigation Log

### Step 1: Find the warning source

Search for "Direct streaming response completed with no content" in openrouter_gateway.py

### Step 2: Trace the call stack

Who calls this? What triggers multiple attempts?

### Step 3: Find continuation logic

Look for:
- `continue` related code
- Loop that calls LLM multiple times
- `finish_response` / `finish_task` handling

### Step 4: Identify the fix

---

## Findings

(To be filled in during investigation)

---

## Related Files

- `penguin/llm/openrouter_gateway.py` - Warning source
- `penguin/engine.py` - Main execution loop
- `penguin/core.py` - Core orchestration
- `penguin/cli/cli.py` - CLI continuation handling


---

## Findings

### 1. Warning Source (openrouter_gateway.py:852)

```python
if not full_content:
    self.logger.warning(f"Direct streaming response completed with no content. Model: {self.model_config.model}")
```

This warning fires when the LLM returns an empty response during streaming.

### 2. Why Empty Responses Happen

The engine loop (`run_response`) continues until:
1. `finish_response` tool is called → `break`
2. Max iterations reached (5000 default)
3. Lite agent returns output → `break`

**There is NO break for empty responses!**

When the LLM has nothing more to say but doesn't call `finish_response`:
- Engine requests another response
- LLM returns empty
- Warning fires
- Loop continues
- Repeat 3 times (maybe some retry logic?)

### 3. Implicit Completion is DISABLED

Lines 390-396 in engine.py:
```python
# NOTE: Implicit completion detection is DISABLED.
# The LLM must explicitly call finish_response to end the conversation.
# This prevents premature termination when processing tool results.
#
# if not iteration_results:
#     logger.debug("Conversation completion: No actions in response (implicit)")
#     break
```

This was intentionally disabled to prevent premature termination, but it causes the opposite problem - the loop never stops when LLM returns empty.

### 4. The 3x Pattern

The warning appears 3 times because:
- Likely retry logic somewhere
- Or the LLM is being called multiple times in quick succession
- Need to trace where the 3 comes from

---

## Root Cause

**The LLM sometimes doesn't call `finish_response` when it should.** When this happens:
1. Engine asks for another response
2. LLM returns empty (nothing more to say)
3. Warning fires
4. Loop continues because no `break` condition met
5. Eventually something stops it (unclear what)

---

## Potential Fixes

### Option A: Re-enable implicit completion for empty responses

```python
# If LLM returns empty AND no actions, consider it done
if not assistant_response and not iteration_results:
    logger.debug("Implicit completion: Empty response with no actions")
    break
```

**Risk:** May terminate prematurely if LLM is "thinking"

### Option B: Add empty response counter

```python
empty_response_count = 0
MAX_EMPTY_RESPONSES = 2

# In loop:
if not assistant_response:
    empty_response_count += 1
    if empty_response_count >= MAX_EMPTY_RESPONSES:
        logger.debug("Completion: Multiple empty responses")
        break
else:
    empty_response_count = 0
```

**Safer:** Allows one retry but stops after repeated empties

### Option C: Better prompt engineering

Ensure the system prompt strongly emphasizes calling `finish_response`:
- "You MUST call finish_response when done"
- "Never end without finish_response"

**Risk:** LLMs don't always follow instructions perfectly

---

## Recommended Fix

**Option B** - Add empty response counter with limit of 2.

This:
1. Allows one retry (in case of transient issue)
2. Stops infinite loops
3. Doesn't require LLM behavior change
4. Is conservative and safe



---

## Additional Findings (Deeper Investigation)

### Call Stack

1. `CLI.run()` → main loop waiting for user input
2. `interface.process_input()` → calls core.process
3. `core.process()` → calls engine.run_response (multi_step=True, max_iterations=5)
4. `engine.run_response()` → while loop up to max_iterations (5 by default)
5. `engine._llm_step()` → calls api_client.get_response
6. `api_client.get_response()` → calls gateway.get_response
7. `gateway.get_response()` → streaming call to OpenRouter

### Key Finding: max_iterations=5 in core.process

In `core.process()` line 2354:
```python
max_iterations: int = 5,
```

And this is passed to `engine.run_response()` at line 2504:
```python
response = await self.engine.run_response(
    prompt=message,
    ...
    max_iterations=max_iterations,  # 5 by default
    ...
)
```

### The run_response Loop

In `engine.run_response()` (line 280-410):
- Loop: `while self.current_iteration < max_iters`
- Only breaks on:
  1. `finish_response` tool called
  2. Lite agent output
- Does NOT break on empty response

### Why 3 Warnings?

The `max_iterations=5` in core.process, but we see 3 warnings. Possible explanations:

1. **First 2 iterations work** (tool execution, response generation)
2. **Last 3 iterations are empty** (LLM has nothing more to say but didn't call finish_response)
3. Loop stops at iteration 5, but only 3 of those were empty

### The Real Issue

When the LLM completes its work but doesn't call `finish_response`:
1. Engine asks for another response
2. LLM returns empty (nothing more to say)
3. Warning fires: "Direct streaming response completed with no content"
4. Loop continues because no break condition met
5. Repeat until max_iterations

### Empty Response Retry in core.process

Lines 2535-2549 show a single retry when response is empty:
```python
if isinstance(response, dict) and not response.get("assistant_response", "").strip():
    logger.warning("Assistant response was empty – retrying once without streaming…")
    retry_data, _ = await self.get_response(streaming=False)
```

But this is AFTER run_response returns, so it doesn't explain the 3 warnings during the loop.

---

## Hypothesis

The 3 warnings happen because:
1. run_response runs with max_iterations=5
2. LLM produces content in iterations 1-2
3. Iterations 3-5 produce empty responses (no finish_response called)
4. Each empty iteration triggers the warning
5. Loop exits at iteration 5

The warning is a **symptom**, not the **cause**. The cause is the LLM not calling `finish_response`.

---

## Questions Still Open

1. Why doesn't the LLM call `finish_response`?
2. Is the system prompt clear enough about when to call it?
3. Should we add implicit completion detection for consecutive empty responses?



---

## ROOT CAUSE FOUND ✅

### The Problem

In `core.process()` (line 2354):
```python
max_iterations: int = 5,  # THIS WAS THE BUG
```

The CLI calls `core.process()` without overriding `max_iterations`, so it defaults to 5.

After 5 iterations (tool calls), the engine stops and returns. The user then has to say "continue" to start another batch of 5.

### The Fix

Changed the default from 5 to 100:
```python
max_iterations: int = 100,  # Increased from 5 to allow longer autonomous runs
```

### Why 100 instead of 5000?

- 5000 is the engine's internal max (safety limit)
- 100 is reasonable for most tasks
- Prevents truly runaway loops while allowing autonomous work
- Can be overridden by caller if needed

### The 3x Empty Response Warning

This was a **symptom**, not the cause:
1. After 5 iterations, engine stops
2. But sometimes LLM hasn't called `finish_response` yet
3. The last few iterations might be empty (LLM has nothing to say)
4. Warning fires for each empty iteration

With `max_iterations=100`, the LLM has more room to work and should naturally call `finish_response` when done, rather than being cut off at 5.



---

## COMPLETE FIX APPLIED ✅

### Files Updated

1. **penguin/core.py**
   - Added `MAX_TASK_ITERATIONS` to imports
   - Changed `max_iterations: int = 5` → `max_iterations: int = MAX_TASK_ITERATIONS`

2. **penguin/web/routes.py**
   - Changed `max_iterations: Optional[int] = 5` → `max_iterations: Optional[int] = None`

3. **penguin/agent/__init__.py**
   - Changed `max_iterations: int = 5` → `max_iterations: int = 5000`

4. **penguin/project/models.py**
   - Changed `max_iterations: int = 5` → `max_iterations: int = 5000`

5. **penguin/api/routes.py**
   - Changed `max_iterations: Optional[int] = 5` → `max_iterations: Optional[int] = None`

6. **penguin/api_client.py**
   - Changed `max_iterations: int = 5` → `max_iterations: int = 5000`

### Not Changed (Intentionally Low)

- `penguin/web/integrations/github_webhook.py` - max_iterations=3 for PR reviews (appropriate)
- `penguin/project/spec_parser.py` - max_iterations=3 for spec parsing (appropriate)
- `penguin/utils/parser.py` - delegate_explore_task capped at 100 (appropriate for sub-agent)

### Config Value

All these now align with `penguin/config.py`:
```python
MAX_TASK_ITERATIONS = 5000  # High default for agentic workflows; API callers can override
```

### Expected Result

Users should no longer need to say "continue" every 5 iterations. The agent will run autonomously until:
1. It calls `finish_response` or `finish_task`
2. Max iterations (5000) is reached
3. User interrupts

