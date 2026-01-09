# finish_response and finish_task - Complete Execution Flow Analysis

## Overview

The termination signal system in Penguin provides explicit control for the LLM to stop reasoning loops. This analysis traces the complete execution flow from LLM output to loop termination.

---

## Complete Call Stack

```
LLM Output
  ↓
Parser (parse_action)
  ↓
ActionExecutor.execute_action()
  ↓
ToolManager (registry lookup)
  ↓
TaskTools.finish_response() / finish_task()
  ↓
Engine._check_termination_signal()
  ↓
Iteration Loop Break
  ↓
Return Results
```

---

## Step-by-Step Execution

### Step 1: LLM Generates Termination Signal

**Conversational Mode (run_response):**
```
finish_response
Brief summary of what was explained
```

**Task Mode (run_task):**
```
finish_task
{"summary": "Implemented the login feature", "status": "done"}
```

Or with plain string:
```
finish_task
Task completed successfully
```

---

### Step 2: Parser Extracts Action

**File:** `penguin/utils/parser.py`

The `parse_action()` function extracts:
- Action name: `"finish_response"` or `"finish_task"`
- Parameters: The content between tags (summary or JSON)

---

### Step 3: ActionExecutor Routes to Tool

**File:** `penguin/utils/parser.py` (ActionExecutor class)

1. Looks up action name in ToolManager's registry
2. Executes the tool with parsed parameters
3. Returns result dict with structure:
   ```python
   {
       "action": "finish_response",
       "result": "Response complete. Summary: ...",
       "status": "completed"
   }
   ```

---

### Step 4: ToolManager Registry Lookup

**File:** `penguin/tools/tool_manager.py` (Lines 252-253)

```python
self._tool_registry = {
    'finish_response': 'self.task_tools.finish_response',
    'finish_task': 'self.task_tools.finish_task',
    'task_completed': 'self.task_tools.task_completed',  # Deprecated alias
}
```

The registry maps tool names to execution paths.

---

### Step 5: TaskTools Implementation

**File:** `penguin/tools/core/task_tools.py`

#### finish_response Method (Lines 5-20)

```python
def finish_response(self, summary: Optional[str] = None) -> str:
    """
    Signal that the conversational response is complete.
    
    Called by the LLM when it has finished responding to the user
    and has no more actions to take. This stops the run_response loop.
    
    Args:
        summary: Optional brief summary of the response.
        
    Returns:
        A confirmation message.
    """
    # This tool is a signal for Engine.run_response to stop.
    if summary:
        return f"Response complete. Summary: {summary}"
    return "Response complete."
```

**Key Points:**
- Simple signal tool with optional summary parameter
- Returns human-readable confirmation
- Used in `run_response` mode (conversational)
- No status marker needed (conversational mode doesn't track task status)

#### finish_task Method (Lines 22-60)

```python
def finish_task(self, params: Optional[str] = None) -> str:
    """
    Signal that the LLM believes the task objective is achieved.
    
    This transitions the task to PENDING_REVIEW status for human approval.
    The task is NOT marked COMPLETED - a human must approve it.
    
    Args:
        params: Either a plain summary string, or JSON with:
            - summary: What was accomplished (optional)
            - status: "done" | "partial" | "blocked" (default: "done")
            
    Returns:
        A confirmation message indicating task is pending review.
    """
    # Parse params - could be plain string or JSON
    summary = None
    status = "done"
    
    if params:
        params = params.strip()
        if params.startswith("{"):
            try:
                data = json.loads(params)
                summary = data.get("summary")
                status = data.get("status", "done")
            except json.JSONDecodeError:
                summary = params
        else:
            summary = params
    
    # This tool is a signal for Engine.run_task to stop.
    # The actual state transition to PENDING_REVIEW is handled by RunMode/Engine.
    status_msg = {
        "done": "Task objective achieved",
        "partial": "Partial progress made", 
        "blocked": "Task blocked - cannot proceed"
    }.get(status, "Task objective achieved")
    
    # Include machine-readable status marker for Engine to parse reliably
    # This avoids false positives from substring matching in user summaries
    status_marker = f"[FINISH_STATUS:{status}]"
    
    if summary:
        return f"{status_msg}. Marked for human review. Summary: {summary} {status_marker}"
    return f"{status_msg}. Marked for human review. {status_marker}"
```

**Key Points:**
- Accepts plain string or JSON parameters
- Extracts `status` field: "done" | "partial" | "blocked"
- **Critical**: Embeds `[FINISH_STATUS:xxx]` marker in return value
- This marker is parsed by Engine to determine completion status
- Used in `run_task` mode (autonomous)

#### task_completed Method (Lines 62-65)

```python
# Deprecated: kept for backward compatibility
def task_completed(self, summary: str) -> str:
    """Deprecated: Use finish_task instead."""
    return self.finish_task(summary)
```

Legacy alias for backward compatibility.

---

### Step 6: Engine Detects Termination Signal

**File:** `penguin/engine.py`

#### _check_termination_signal Method (Lines 846-865)

```python
def _check_termination_signal(
        self,
        iteration_results: List[Dict[str, Any]],
        termination_action: str,
    ) -> Tuple[bool, str]:
        """Check if termination signal was received in iteration results.

        Args:
            iteration_results: Action results from current iteration
            termination_action: Action name that signals termination

        Returns:
            Tuple of (signal_detected, finish_status)
        """
        for result in iteration_results:
            if isinstance(result, dict):
                action_name = result.get("action", "")
                # Also check for legacy "task_completed" action
                if action_name == termination_action or (termination_action == "finish_task" and action_name == "task_completed"):
                    # Extract status from machine-readable marker [FINISH_STATUS:xxx]
                    result_output = result.get("result", "")
                    status_match = re.search(r'\[FINISH_STATUS:(\w+)\]', result_output)
                    finish_status = status_match.group(1) if status_match else "done"
                    return True, finish_status
        return False, ""
```

**Key Points:**
- Iterates through action results from current iteration
- Checks if action name matches expected termination action
- For `finish_task`, also accepts legacy `task_completed`
- **Critical**: Extracts status from `[FINISH_STATUS:xxx]` regex pattern
- Returns tuple: (signal_detected, finish_status)

---

### Step 7: Iteration Loop Processes Termination

**File:** `penguin/engine.py` (_iteration_loop method, Lines 714-740)

```python
# Check for explicit termination signal
termination_detected, finish_status = self._check_termination_signal(
    iteration_results, config.termination_action
)
if termination_detected:
    if config.mode == "task":
        completion_status = "pending_review"
        logger.info(f"Task completion signal detected via '{config.termination_action}' (status: {finish_status})")

        if config.enable_events and config.task_metadata:
            await self._publish_task_event("COMPLETED", config.task_metadata, {
                "response": last_response,
                "iteration": self.current_iteration,
                "max_iterations": max_iterations,
                "finish_status": finish_status,
                "requires_review": True,
            })
    else:
        logger.debug(f"Response completion: {config.termination_action} tool called")
    break
```

**Key Points:**
- Calls `_check_termination_signal` with iteration results
- If signal detected:
  - For task mode: Sets `completion_status = "pending_review"`
  - For response mode: Just logs and breaks
  - Publishes COMPLETED event if events enabled
- **Critical**: Breaks the while loop to stop iterations

---

### Step 8: Loop Returns Final Results

**File:** `penguin/engine.py` (_iteration_loop method, Lines 789-796)

```python
return {
    "assistant_response": last_response,
    "iterations": self.current_iteration,
    "action_results": all_action_results,
    "status": completion_status,
    "execution_time": (datetime.utcnow() - self.start_time).total_seconds()
}
```

**Return Values:**
- `assistant_response`: Final LLM response
- `iterations`: Number of iterations performed
- `action_results`: All action results collected
- `status`: Completion status ("completed", "pending_review", "max_iterations", etc.)
- `execution_time`: Total execution time in seconds

---

## Mode Differences

### Conversational Mode (run_response)

**Configuration:**
```python
config = LoopConfig(
    mode="response",
    termination_action="finish_response",
    # ...
)
```

**Termination Behavior:**
- Only checks for `finish_response` action
- Does NOT check for `finish_task`
- Sets status to "completed" or "max_iterations"
- No event publishing
- Simple break from loop

**Example Call Stack:**
```
run_response()
  → _iteration_loop(config.mode="response", termination_action="finish_response")
    → _llm_step() returns action_results
    → _check_termination_signal(iteration_results, "finish_response")
      → Returns (True, "") if finish_response found
    → break (loop terminates)
    → return {"status": "completed", ...}
```

---

### Task Mode (run_task)

**Configuration:**
```python
config = LoopConfig(
    mode="task",
    termination_action="finish_task",
    enable_events=True,
    task_metadata={...},
    # ...
)
```

**Termination Behavior:**
- Checks for `finish_task` action (also accepts legacy `task_completed`)
- Extracts status from `[FINISH_STATUS:xxx]` marker
- Sets `completion_status = "pending_review"`
- Publishes COMPLETED event with finish_status
- Marks task for human review (not auto-completed)

**Example Call Stack:**
```
run_task()
  → _iteration_loop(config.mode="task", termination_action="finish_task")
    → _llm_step() returns action_results
    → _check_termination_signal(iteration_results, "finish_task")
      → Returns (True, "done") if finish_task with status found
    → completion_status = "pending_review"
    → _publish_task_event("COMPLETED", ..., finish_status="done")
    → break (loop terminates)
    → return {"status": "pending_review", ...}
```

---

## Summary Parameter Handling

### finish_response

**Input:**
```xml
finish_response
Brief summary of what was explained
```

**Tool Output:**
```
Response complete. Summary: Brief summary of what was explained
```

**Engine Processing:**
- No status extraction needed
- Summary is just informational
- Loop terminates immediately

---

### finish_task

**Input (JSON):**
```json
finish_task
{"summary": "Implemented the login feature", "status": "done"}
```

**Tool Output:**
```
Task objective achieved. Marked for human review. Summary: Implemented the login feature [FINISH_STATUS:done]
```

**Input (Plain String):**
```xml
finish_task
Task completed successfully
```

**Tool Output:**
```
Task objective achieved. Marked for human review. Summary: Task completed successfully [FINISH_STATUS:done]
```

**Engine Processing:**
1. Extracts status from `[FINISH_STATUS:xxx]` via regex
2. Stores finish_status for event publishing
3. Sets completion_status = "pending_review"
4. Publishes COMPLETED event with finish_status

---

## Status Values

### finish_task Status Options

| Status | Meaning | Use Case |
|--------|---------|----------|
| `done` | Task objective fully achieved | Normal completion |
| `partial` | Partial progress made | Task incomplete but useful work done |
| `blocked` | Cannot proceed | Task stopped by external factor |

### Engine Completion Status Values

| Status | Mode | Meaning |
|--------|------|---------|
| `completed` | response | Normal completion via finish_response |
| `pending_review` | task | Normal completion via finish_task |
| `max_iterations` | response | Hit max iterations limit |
| `iterations_exceeded` | task | Hit max iterations limit |
| `stopped` | both | External stop condition triggered |
| `error` | both | Exception occurred |
| `llm_empty_response_error` | both | LLM returned empty response |
| `implicit_completion` | task | WALLET_GUARD detected completion |

---

## WALLET_GUARD Fallback Termination

**File:** `penguin/engine.py` (_check_wallet_guard_termination method, Lines 683-726)

If explicit termination signal not received, Engine checks for these conditions:

1. **No-action completion**: Model doesn't use CodeAct format
2. **Echoing tool results**: Model confused and echoing results as text
3. **Repeated responses**: Same response seen 2+ times consecutively
4. **Empty/trivial responses**: 3+ consecutive empty or trivial responses

**Behavior:**
- For task mode: Returns `("implicit_completion", "implicit_completion")`
- For response mode: Returns `("implicit_completion", None)`

---

## Key Design Decisions

### 1. Machine-Readable Status Marker

**Problem:** How to distinguish status from user summary?

**Solution:** `[FINISH_STATUS:xxx]` marker in tool output

**Benefits:**
- Avoids false positives from substring matching
- Allows user summaries to contain any text
- Reliable regex-based extraction

### 2. Dual Termination Tools

**Problem:** Different modes need different termination semantics

**Solution:** Separate `finish_response` and `finish_task` tools

**Benefits:**
- Clear separation of concerns
- Mode-specific behavior (event publishing, status tracking)
- Prevents accidental cross-mode termination

### 3. Explicit vs Implicit Termination

**Problem:** Models might not call termination tools

**Solution:** WALLET_GUARD fallback checks

**Benefits:**
- Prevents infinite loops
- Handles models that don't use CodeAct format
- Provides safety net for edge cases

---

## Common Issues and Debugging

### Issue 1: Loop Not Terminating

**Symptoms:** Engine continues iterating after finish_response/finish_task called

**Debugging:**
1. Check logs for: `Response contains 'finish_response' text but wasn't parsed as action`
2. Verify tool is registered in `_tool_registry`
3. Check action name matches exactly (case-sensitive)
4. Verify parser is extracting action correctly

### Issue 2: Status Not Extracted

**Symptoms:** finish_status is "done" even when different status specified

**Debugging:**
1. Check tool output contains `[FINISH_STATUS:xxx]` marker
2. Verify regex pattern in `_check_termination_signal`
3. Check JSON parsing in `finish_task` method

### Issue 3: Wrong Mode Terminating

**Symptoms:** finish_response called in task mode (or vice versa)

**Debugging:**
1. Check LoopConfig.termination_action matches mode
2. Verify tool name matches expected termination action
3. Check mode-specific logic in _iteration_loop

---

## File References

| Component | File | Lines |
|-----------|------|-------|
| Tool Registry | `penguin/tools/tool_manager.py` | 252-253 |
| finish_response | `penguin/tools/core/task_tools.py` | 5-20 |
| finish_task | `penguin/tools/core/task_tools.py` | 22-60 |
| task_completed | `penguin/tools/core/task_tools.py` | 62-65 |
| _check_termination_signal | `penguin/engine.py` | 846-865 |
| _iteration_loop (termination check) | `penguin/engine.py` | 714-740 |
| run_response | `penguin/engine.py` | 857-950 |
| run_task | `penguin/engine.py` | 1002-1200 |
| _check_wallet_guard_termination | `penguin/engine.py` | 683-726 |

---

## Conclusion

The termination signal system is a well-designed mechanism that gives explicit control to the LLM while providing robust fallbacks. The key innovations are:

1. **Machine-readable status markers** for reliable parsing
2. **Mode-specific tools** for clear separation of concerns
3. **WALLET_GUARD fallbacks** for safety and reliability
4. **Event publishing** for task mode integration

The system ensures that:
- Conversational loops terminate cleanly with `finish_response`
- Task loops transition to human review with `finish_task`
- Edge cases are handled gracefully with WALLET_GUARD
- Status information is reliably extracted and propagated