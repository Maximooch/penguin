# CLI Issues Analysis and Recommendations

## Executive Summary

This document analyzes 5 key issues identified in the Penguin CLI (`--old-cli`) and provides specific, actionable recommendations for each. The analysis is based on user observations from terminal output and conversation logs.

---

## Issue 1: `--no-tui` Flag Missing

### Problem
Running `uv run penguin --no-tui` produces error: "No such option: --no-tui Did you mean --no-streaming?"

### Root Cause
- `--no-tui` is defined in `cli_new.py` (line 141) but NOT in the active entry points (`cli.py` and `old_cli.py`)
- The main entry point doesn't recognize this flag
- `--old-cli` exists and works, but serves a different purpose (legacy CLI vs. headless mode)

### Impact
- Users cannot force headless mode without using `--old-cli`
- Inconsistent flag availability across different CLI versions
- Documentation may reference non-existent flags

### Recommendations

**Option A: Add `--no-tui` to existing CLIs (Recommended)**
```python
# In old_cli.py and cli.py main_entry()
no_tui: bool = typer.Option(
    False, "--no-tui",
    help="Force headless mode (no TUI interface)"
)
```

Then in the headless detection logic:
```python
# Determine if we should run headless
headless_mode = any([
    no_tui,  # ADD THIS
    prompt is not None,
    continue_last,
    resume_session,
    run_task,
    continuous,
    ctx.invoked_subcommand is not None
])
```

**Option B: Alias `--no-tui` to `--old-cli`**
Add to argument parsing:
```python
# Map --no-tui to --old-cli for backwards compatibility
if "--no-tui" in sys.argv:
    sys.argv = [arg if arg != "--no-tui" else "--old-cli" for arg in sys.argv]
```

**Recommendation: Option A** - Keep them separate since they serve different purposes:
- `--no-tui`: Headless mode (could be new CLI or old CLI, just no TUI)
- `--old-cli`: Specifically use the legacy Rich-based implementation

---

## Issue 2: Duplicate User Messages

### Problem
User messages appear twice in the output:
1. Input echo: `You [0]: Are you a real Penguin?`
2. Formatted box with same message

### Root Cause Analysis

**Location 1: Direct display (old_cli.py:2110)**
```python
# Show user input
self.display_message(user_input, "user")

# Add user message to processed messages to prevent duplication
user_msg_key = f"user:{user_input[:50]}"
self.processed_messages.add(user_msg_key)
self.message_turn_map[user_msg_key] = self.current_conversation_turn
```

**Location 2: Event-driven display (old_cli.py:2594-2617)**
```python
# If this is a user message, it's the start of a new conversation turn
if role == "user":
    # Increment conversation turn counter
    self.current_conversation_turn += 1
    # ...
# Display the message
self.display_message(content, role)
```

**Why deduplication fails:**
- The message is added to `processed_messages` at line 2114
- BUT the event handler checks for it at line 2589-2590
- The timing issue: The event comes from Core AFTER the direct display, but the check uses only first 50 chars
- If the event arrives before the processed_messages set is updated, it will display anyway

### Recommendations

**Solution 1: Don't display user input directly (Recommended)**
```python
# In chat_loop() around line 2110
# REMOVE THIS LINE:
# self.display_message(user_input, "user")

# Keep the processed_messages tracking:
user_msg_key = f"user:{user_input[:50]}"
self.processed_messages.add(user_msg_key)
self.message_turn_map[user_msg_key] = self.current_conversation_turn
```

Let the event system handle ALL message display, including user messages. This ensures:
- Single source of truth for message display
- Consistent formatting
- No race conditions

**Solution 2: Fix the deduplication check (Alternative)**
```python
# In handle_event() around line 2588-2591
# CURRENT:
msg_key = f"{role}:{content[:50]}"
if msg_key in self.processed_messages:
    return

# IMPROVED:
# Use full content for user messages since they're typically shorter
if role == "user":
    msg_key = f"{role}:{content}"  # Full content for exact match
else:
    msg_key = f"{role}:{content[:50]}"
    
if msg_key in self.processed_messages:
    return
```

**Recommendation: Solution 1** - It's cleaner and more maintainable to have a single display path.

---

## Issue 3: System Output Messages Appear Above Penguin Messages

### Problem
Tool execution results appear BEFORE the assistant message that triggered them:

```
╭─ 🐧 System ──────────────────────────────────────────────────────────────────
│ Tool Result (execute): 827561
╰──────────────────────────────────────────────────────────────────────────────

╭─ 🐧 Penguin (Streaming) ─────────────────────────────────────────────────────
│ Planning function execution
│ 
│ I need to write a function that prints a random number...
╰──────────────────────────────────────────────────────────────────────────────
```

Expected order: Penguin message FIRST, then tool result.

### Root Cause

**Event processing (old_cli.py:2578-2582)**
```python
# Allow system output messages (tool results) to be displayed
if category == MessageCategory.SYSTEM_OUTPUT or category == "SYSTEM_OUTPUT":
    # Display tool results immediately
    self.display_message(content, "system")
    return
```

**The issue:**
1. Core processes user input
2. Assistant starts streaming response
3. Assistant calls a tool (execute)
4. Tool result comes back IMMEDIATELY and is displayed
5. Assistant response is STILL streaming
6. Result: Tool output appears first, then the reasoning that led to it

This is a **message ordering** problem caused by asynchronous execution.

### Recommendations

**Solution 1: Buffer tool results until assistant message completes (Recommended)**

```python
# Add to __init__:
self.pending_tool_results: List[Tuple[str, str]] = []  # (content, role)
self.tool_results_for_turn: Dict[int, List[str]] = {}

# In handle_event():
if category == MessageCategory.SYSTEM_OUTPUT or category == "SYSTEM_OUTPUT":
    # Buffer tool results instead of displaying immediately
    if self.is_streaming or not self.last_completed_message:
        # Store for later display
        self.pending_tool_results.append((content, "system"))
        return
    else:
        # Not streaming, display immediately
        self.display_message(content, "system")
        return

# In _finalize_streaming() or when streaming completes:
def _finalize_streaming(self):
    # ... existing finalization code ...
    
    # Display any pending tool results AFTER the message
    if self.pending_tool_results:
        for content, role in self.pending_tool_results:
            self.display_message(content, role)
        self.pending_tool_results.clear()
```

**Solution 2: Delay tool result display with a small buffer**
```python
# Less ideal but simpler
if category == MessageCategory.SYSTEM_OUTPUT or category == "SYSTEM_OUTPUT":
    # Add small delay to let streaming messages render first
    await asyncio.sleep(0.1)  # 100ms buffer
    self.display_message(content, "system")
    return
```

**Solution 3: Display tool results inline with reasoning (Complex)**
- Parse the assistant message for tool call markers
- Insert tool results at the appropriate location
- Requires more sophisticated parsing and formatting

**Recommendation: Solution 1** - Provides proper ordering without hacks. The conversation flow should be:
1. User message
2. Assistant reasoning/response
3. Tool execution results
4. Assistant acknowledgment of results

---

## Issue 4: Prompting Issues in `prompt_workflow.py`

### Problem

**A) HTML tags don't render in CLI:**
```
<details>
<summary>🧠  Click to show / hide internal reasoning</summary>

**Checking user needs**

I'm considering how best to assist...
</details>
```

These appear as literal text in the terminal, not collapsible sections.

**B) Malformed code blocks:**
```python
import randomdef print_random_number():
 n = random.randint(1,1_000_000)
```

Missing newline between import and function definition.

**C) Reasoning is verbose and cluttered:**
Large blocks of reasoning text make the output hard to read in a terminal.

### Root Cause

**Location: `prompt_workflow.py:422-429`**
```python
### Reasoning Blocks (Optional)
For complex tasks, you MAY wrap your thinking in a collapsible block:

<details>
<summary>🧠 Click to show / hide internal reasoning</summary>

Your internal thought process here...

</details>
```

This guidance is in the system prompt and is HTML-specific, not CLI-friendly.

### Recommendations

**A) Make reasoning format environment-aware**

Create two formatting styles:

```python
# Add to prompt_workflow.py

CLI_REASONING_FORMAT = """
### Reasoning Display (CLI Mode)

For complex tasks, you MAY include brief reasoning. In CLI mode, format it as gray text:

[dim]🧠 Reasoning: I'll search the codebase for auth logic, then check if caching exists.[/dim]

**Rules:**
1. Keep reasoning to 1-2 sentences MAX
2. Use [dim]...[/dim] for Rich formatting (gray text)
3. Place BEFORE your main response
4. Don't use HTML tags like <details> or <summary>

**Example:**
[dim]🧠 Planning: Breaking task into 3 steps: search, analyze, implement.[/dim]

Now implementing the authentication flow...
"""

TUI_REASONING_FORMAT = """
### Reasoning Display (TUI Mode)

For complex tasks, you MAY wrap your thinking in a collapsible block:

<details>
<summary>🧠 Click to show / hide internal reasoning</summary>

Your internal thought process here (2-4 sentences)...

</details>

Then provide your main response.

**Keep reasoning concise** - a few sentences, not paragraphs.
"""
```

**B) Fix code formatting guidance**

Update in `OUTPUT_STYLE_STEPS_FINAL` and `OUTPUT_STYLE_PLAIN`:

```python
# CURRENT (lines 402-406):
**Critical Rules:**
1. Put language tag on its own line: ` ```python ` (with newline after)
2. Put markers as comments on separate lines: `# <execute>` and `# </execute>`
3. Proper spacing: blank line after imports, before function defs, between statements
4. DO NOT concatenate keywords: write `import random\\ndef print` NOT `import randomdef print`

# ENHANCED:
**Critical Code Formatting Rules:**
1. Language tag on its own line: ` ```python ` followed by newline
2. Execute markers on separate lines:
   ```
   # <execute>
   import random
   
   def print_random_number():
       ...
   # </execute>
   ```
3. **MANDATORY blank line after imports** before any other code
4. **NEVER concatenate keywords**: Write `import random\ndef func()` NOT `import randomdef func()`
5. Proper indentation (4 spaces for Python)
6. Blank lines between function definitions

**BAD Example (DO NOT DO THIS):**
```python
import randomdef print_random_number():
 n = random.randint(1,1_000_000)
```

**GOOD Example:**
```python
import random

def print_random_number():
    n = random.randint(1, 1_000_000)
    print(n)
    return n
```
"""
```

**C) Add mode detection to workflow**

```python
def get_output_formatting(style: str, cli_mode: bool = True) -> str:
    """Return the output-formatting guidance block by style name.

    Args:
        style: 'steps_final' | 'plain' | 'json_guided' (case-insensitive)
        cli_mode: True for terminal CLI, False for web/TUI interfaces
    """
    key = (style or "").strip().lower()
    
    # Select base format
    if key in ("steps_final", "steps+final", "steps-final", "default", "tui"):
        base_format = OUTPUT_STYLE_STEPS_FINAL
    elif key in ("plain", "simple"):
        base_format = OUTPUT_STYLE_PLAIN
    elif key in ("json_guided", "json-guided", "json"):
        base_format = OUTPUT_STYLE_JSON_GUIDED
    else:
        base_format = OUTPUT_STYLE_STEPS_FINAL
    
    # Append appropriate reasoning format
    if cli_mode:
        return base_format + "\n\n" + CLI_REASONING_FORMAT
    else:
        return base_format + "\n\n" + TUI_REASONING_FORMAT
```

**D) Update the interface to pass cli_mode flag**

```python
# In old_cli.py or wherever prompts are constructed
from penguin.prompt_workflow import get_output_formatting

system_prompt_formatting = get_output_formatting(
    style="plain",  # or "steps_final"
    cli_mode=True   # We're in terminal CLI mode
)
```

---

## Issue 5: General Issues

### Problem A: Duplicate Code Execution

The assistant executed the same code twice, producing two different random numbers (827561, then 670326).

**Expected behavior:**
1. Execute code once
2. Receive result
3. Acknowledge result: "The random number is 827561."
4. STOP - don't execute again

**Actual behavior:**
1. Execute code
2. Receive result: 827561
3. Execute code AGAIN (without acknowledging first result)
4. Receive second result: 670326
5. Finally acknowledge: "Got it: 670326"

### Root Cause

**The prompt is not enforcing result acknowledgment strongly enough.**

From conversation JSON (lines 103-118):
```json
{
  "role": "tool",
  "content": "827561",  // First result
  ...
},
{
  "role": "assistant",
  "content": "Running a small function...",  // Executed AGAIN!
  "metadata": {
    "tool_calls": [...]  // Second execution
  }
}
```

The assistant didn't acknowledge the first result before proceeding.

### Recommendations

**Strengthen the acknowledgment rule in prompts:**

```python
# In OUTPUT_STYLE_PLAIN and OUTPUT_STYLE_STEPS_FINAL

TOOL_RESULT_ACKNOWLEDGMENT_RULE = """
### Tool Result Acknowledgment (CRITICAL - READ CAREFULLY)

**MANDATORY RULE:** After EVERY tool execution, you MUST:
1. WAIT for the tool result to appear
2. READ the result in the next message
3. ACKNOWLEDGE it explicitly BEFORE doing anything else

**The acknowledgment MUST be your FIRST response after seeing the result.**

**Correct Flow:**
```
You: [execute code that prints random number]
System: Tool Result (execute): 389671
You: "The random number is 389671."  ← ACKNOWLEDGE FIRST
     [Then continue with next step if needed]
```

**WRONG Flow (DO NOT DO THIS):**
```
You: [execute code]
System: Tool Result (execute): 389671
You: [execute code AGAIN]  ← WRONG! You didn't acknowledge the first result!
System: Tool Result (execute): 502341
```

**Why This Matters:**
- Re-executing without acknowledgment wastes tokens and API calls
- It confuses the user (which result is correct?)
- It indicates you're not processing tool results properly

**Detection Pattern:**
If you see a tool result in the conversation history, your NEXT message MUST:
- Start with acknowledgment of that result
- NOT contain another tool call for the same operation
- Only proceed to new operations after acknowledgment

**Examples of Good Acknowledgment:**
- "Got it: 389671."
- "The result is 389671."
- "Execution successful. Output: 389671"
- "✓ Function returned: 389671"

Then you may continue with next steps.
"""
```

**Add to both OUTPUT_STYLE_PLAIN and OUTPUT_STYLE_STEPS_FINAL after the existing "Tool Result Acknowledgment" section.**

---

## Problem B: Reasoning Verbosity

The reasoning sections are too long (451 words in one example), making terminal output cluttered.

### Recommendations

**Add to reasoning guidance:**

```python
### Reasoning Length Guidelines (CLI Mode)

**Target lengths:**
- Simple tasks: NO reasoning needed (just respond)
- Medium tasks: 1-2 sentences (15-30 words)
- Complex tasks: 2-4 sentences (30-60 words MAX)

**NEVER exceed 60 words of reasoning in CLI mode.**

**Examples:**

GOOD (26 words):
[dim]🧠 Planning: I'll search auth.py for the login function, check if JWT is used, then verify the token validation logic.[/dim]

BAD (too long):
[dim]🧠 Planning: I need to search the authentication module to understand how users log in. First, I should look in the auth.py file. Then I need to check if JWT tokens are being used for authentication. After that, I'll need to verify that the token validation is working correctly. This is important because...[continues for 100 more words][/dim]

**Rule of thumb:** If your reasoning takes more than 2 lines in the terminal, it's too long.
```

---

## Implementation Priority

### High Priority (Fix Immediately)
1. **Issue 2: Duplicate user messages** - Confusing to users, easy fix
2. **Issue 5A: Duplicate execution** - Wastes API calls, confusing output
3. **Issue 4B: Malformed code blocks** - Breaks code execution

### Medium Priority (Fix Soon)
4. **Issue 1: --no-tui flag** - User experience inconsistency
5. **Issue 4A: HTML reasoning tags** - Display clutter
6. **Issue 5B: Reasoning verbosity** - Readability

### Lower Priority (Can Wait)
7. **Issue 3: System output ordering** - Slightly confusing but not breaking

---

## Testing Checklist

After implementing fixes:

- [ ] Test `--no-tui` flag works and enters headless mode
- [ ] Verify user messages only appear once in conversation
- [ ] Check tool results appear AFTER assistant messages, not before
- [ ] Confirm reasoning uses gray text, not HTML tags
- [ ] Validate code blocks have proper newlines and formatting
- [ ] Test that tools are only executed once per request
- [ ] Verify reasoning is concise (under 60 words)
- [ ] Run full conversation flow: input → reasoning → execution → result → acknowledgment

---

## Suggested Quick Wins

**30-Minute Fixes:**
1. Add `--no-tui` flag to old_cli.py (5 mins)
2. Remove duplicate user message display (2 mins)
3. Strengthen tool acknowledgment rule in prompts (10 mins)
4. Fix code formatting examples in prompts (10 mins)

**2-Hour Fix:**
5. Implement CLI-specific reasoning format (1 hour)
6. Add tool result buffering for proper ordering (1 hour)

---

## Related Files

- `/Users/maximusputnam/Code/Penguin/penguin/penguin/cli/old_cli.py` - Main CLI implementation
- `/Users/maximusputnam/Code/Penguin/penguin/penguin/cli/cli_new.py` - New CLI (has --no-tui)
- `/Users/maximusputnam/Code/Penguin/penguin/penguin/prompt_workflow.py` - System prompts and formatting
- `/Users/maximusputnam/Code/Penguin/penguin/penguin/cli/interface.py` - CLI business logic
- `/Users/maximusputnam/Code/Penguin/penguin/penguin/cli/ui.py` - UI rendering

---

## Questions for Clarification

1. **Mode Detection:** How should the system detect CLI vs TUI mode automatically?
   - Via environment variable?
   - Flag passed during initialization?
   - Check if output is a TTY?

2. **Flag Behavior:** Should `--no-tui` and `--old-cli` be mutually exclusive or combinable?
   - `--no-tui --old-cli`: Use old CLI in headless mode?
   - Or should `--no-tui` force new headless CLI only?

3. **Reasoning Toggle:** Should users be able to disable reasoning display entirely?
   - Add `--no-reasoning` flag?
   - Or always show but keep it minimal?

4. **Tool Result Buffering:** Should ALL system messages be buffered, or only tool results?
   - Status messages might need immediate display
   - Error messages should show immediately

---

## Conclusion

The CLI has several UX issues that stem from:
1. Inconsistent flag availability across CLI versions
2. Multiple display paths causing duplication
3. Asynchronous event ordering
4. HTML-centric formatting in terminal output
5. Insufficient enforcement of tool result acknowledgment

Most issues have straightforward fixes. The highest priority should be eliminating duplicate messages and duplicate executions, as these directly impact user experience and API costs.

**Estimated total fix time:** 4-6 hours for all issues.
