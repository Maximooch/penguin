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



---

## ADDITIONAL FIX: Empty Response Handling

### Problem Discovered (cli-run-2.txt)

Even after fixing max_iterations, the LLM sometimes:
1. Produces a complete, beautiful response
2. Doesn't call `finish_response`
3. Engine asks for more
4. LLM returns empty (17 times in the test case!)
5. User has to Ctrl+C

### Solution: System Message Injection

Instead of implicit completion (which could break during long reasoning), we now:

1. **Track consecutive empty responses**
2. **After 3 empty responses**, inject a system message:
   ```
   [System Notice] Multiple empty responses detected.
   If your task is complete, please call: <finish_response>brief summary</finish_response>
   If you need to continue working, please proceed with your next action.
   ```
3. **Reset counter** after injection to give LLM another chance
4. **Safety break** after 10+ iterations with continued empty responses

### Why System Message Instead of Implicit Break?

- Implicit break could interrupt during long reasoning phases
- System message prompts LLM to make explicit decision
- LLM can either finish properly or continue with actions
- More robust than guessing when to stop

### Code Location

`penguin/engine.py` in `run_response()` method, after the `finish_response_called` check.

### Expected Behavior

1. LLM completes response without calling finish_response
2. Engine asks for more → empty response #1
3. Engine asks for more → empty response #2
4. Engine asks for more → empty response #3
5. System injects reminder message
6. LLM sees reminder and calls finish_response (or continues with action)
7. Loop ends cleanly


---

## COMPLETE FIX: Safety Break Logic (December 2024)

### The Bug in the Previous Fix

The system message injection (added earlier) had a **fatal flaw in the safety break logic**:

```python
# Reset counter after injection
self._empty_response_count = 0

# Break after too many attempts (safety limit)
if self.current_iteration > 10 and not iteration_results:  # UNREACHABLE!
    break
```

**Why it was broken:**
1. Counter resets to 0 after every reminder injection
2. Safety break only triggers when BOTH `current_iteration > 10` AND `_empty_response_count >= 3`
3. But counter is always 0-2 when we check iteration number (just got reset!)
4. **The break NEVER triggered** - loop ran until max_iterations (5000)

**Evidence:** cli-run-2.txt showed 17 consecutive empty response warnings with no break.

### The Fix

Added a **total empty response counter** that never resets:

```python
# Initialize at start of run_response/run_task
self._empty_response_count = 0
self._total_empty_responses = 0

# On each empty response
self._empty_response_count += 1
self._total_empty_responses += 1  # Never reset

# Hard break after 10 total (prevents runaway loops)
if self._total_empty_responses >= 10:
    logger.warning(f"Breaking due to {self._total_empty_responses} total empty responses")
    break

# Reminder injection after 3 consecutive
if self._empty_response_count >= 3:
    # ... inject reminder ...
    self._empty_response_count = 0  # Only reset consecutive counter
```

### Files Updated

1. **penguin/engine.py**
   - `run_response()`: Added `_total_empty_responses` counter, hard break at 10
   - `run_task()`: Added `_total_empty_responses_task` counter, hard break at 10

2. **agent/__init__.py**
   - Lines 111, 243: Changed `max_iterations: int = 5` → `MAX_TASK_ITERATIONS`

3. **penguin/local_task/manager.py**
   - Line 453: Changed `data.get("max_iterations", 5)` → `MAX_TASK_ITERATIONS`

### Expected Behavior After Fix

1. LLM completes response without calling finish_response
2. Empty responses accumulate (total counter tracks all of them)
3. After 3 consecutive → reminder injected, consecutive counter resets
4. If LLM still doesn't respond, more empties accumulate
5. After 10 TOTAL empties → hard break (loop exits)
6. User no longer needs to Ctrl+C or type "continue"


---

## SIMPLIFIED FIX: Remove Injection, Break After 3 (December 2024)

### Why the Previous Fix Was Over-Engineered

The system message injection approach had issues:
1. Spammed the console with warning messages
2. Added complexity without benefit
3. The LLM often ignored the injected reminder anyway

### Root Cause Analysis: Why LLM Doesn't Call finish_response

Looking at real usage logs, the LLM often ends with questions like:
- "Which direction appeals to you?"
- "Any preferences on style and behavior?"

This is **valid conversational behavior**. The LLM is waiting for user input, so it correctly doesn't call `finish_response`. The engine then:
1. Asks for more (because no finish_response)
2. LLM returns empty (nothing more to say)
3. Repeat...

**Conclusion:** Empty responses after a question-ending response are **expected**, not an error.

### The Simplified Fix

**engine.py changes:**
```python
# Track consecutive empty responses - break after 3 (simple approach)
if not last_response or not last_response.strip():
    self._empty_response_count += 1
    logger.debug(f"Empty response #{self._empty_response_count}")

    # Break after 3 consecutive empty responses
    if self._empty_response_count >= 3:
        logger.debug("Implicit completion: 3 consecutive empty responses")
        break
else:
    # Reset counter on non-empty response
    self._empty_response_count = 0
```

**openrouter_gateway.py change:**
```python
# Changed from warning to debug level
self.logger.debug(f"Direct streaming response completed with no content...")
```

### Files Updated

1. **penguin/engine.py**
   - `run_response()`: Simplified to break after 3 empties, no injection
   - `run_task()`: Same simplification

2. **penguin/llm/openrouter_gateway.py**
   - Line 852: Changed `warning` → `debug` level

### Expected Behavior After Simplified Fix

1. LLM gives complete response (possibly ending with a question)
2. Engine asks for more → empty response #1 (debug log only)
3. Engine asks for more → empty response #2 (debug log only)
4. Engine asks for more → empty response #3 (debug log only)
5. Engine breaks with "Implicit completion" (debug log)
6. User gets control back - no warnings, no spam


---

## ROOT CAUSE: Prompt Framing Issue (December 2024)

### Investigation: Why Doesn't LLM Call finish_response?

User observation: Line 148-149 in `system_prompt.py` framed `finish_response` as something to call only after tool results, not after general conversational responses.

**Original (problematic):**
```
-   Action results appear in the **next** message as "[Tool Execution Result]". Acknowledge the result, then proceed or call `<finish_response>` if complete.
```

This only mentioned `finish_response` in the context of action results, leading the LLM to think it shouldn't call `finish_response` after regular conversational turns.

### Analysis of Prompt Structure

1. **prompt_actions.py** (lines 45-82): Has excellent finish_response guidance
   - "You MUST explicitly signal when you're done"
   - "Call when you've answered the user and have no more actions to take"
   - "NEVER rely on implicit completion"

2. **prompt_workflow.py** (COMPLETION_PHRASES_GUIDE, lines 571-618): Also has good guidance
   - "You MUST explicitly signal when you're done using completion tools"
   - "The system continues until you call one of these"

3. **system_prompt.py** (line 148-149): Had conflicting/confusing guidance
   - Only mentioned finish_response after "[Tool Execution Result]"
   - Created confusion about when to call it

### The Fix

Updated `system_prompt.py` lines 148-149:

**Before:**
```
-   Use `<finish_response>` (or <finish_task>) to end your turn when the task is fully complete.
-   Action results appear in the **next** message as "[Tool Execution Result]". Acknowledge the result, then proceed or call `<finish_response>` if complete.
```

**After:**
```
-   **ALWAYS call `<finish_response>` when you're done** - whether after answering a question, completing a task, or providing information. Never just stop without calling it.
-   Action results appear in the **next** message as "[Tool Execution Result]". Acknowledge the result, then either continue working or call `<finish_response>` if done.
```

### Summary of All Fixes Applied

1. **max_iterations defaults**: Changed from 5 to MAX_TASK_ITERATIONS (5000) across all files
2. **Empty response handling**: Simplified to break after 3 consecutive empties (no injection)
3. **Warning level**: Changed openrouter_gateway empty response from `warning` to `debug`
4. **System prompt clarity**: Emphasized that `finish_response` must be called after ANY completed response

