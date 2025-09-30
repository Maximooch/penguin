# Penguin CLI Enhancement To-Do List

**Created:** 2025-09-29  
**Goal:** Fix UX issues in `old_cli.py` and improve prompting for CLI environments

---

## High Priority Tasks

### 0. Add ASCII Art at Startup 🎨 ✅
- **File:** `penguin/cli/old_cli.py`
- **Status:** ✅ COMPLETED
- **Issue:** CLI lacks visual polish at startup
- **Fix:** Display ASCII art from README.md at welcome (line 2049-2082)
- **Actual Time:** 3 minutes
- **Lines modified:** 2049-2061 (added ASCII banner)
- **Art source:** Lines 1-11 from README.md

### 1. Remove Duplicate User Messages ✅
- **File:** `penguin/cli/old_cli.py`
- **Status:** ✅ COMPLETED
- **Issue:** User messages appear twice - once at input, once via event system
- **Fix:** Commented out direct display at line 2125, rely on event system only
- **Actual Time:** 1 minute
- **Lines modified:** 2125 (commented out display_message call)

### 2. Implement Reasoning Token Separate Panel Rendering ✅
- **File:** `penguin/cli/old_cli.py`
- **Status:** ✅ COMPLETED
- **Issue:** Reasoning tokens exist but aren't displayed differently from regular content
- **Fix:** Check `is_reasoning` flag and create SEPARATE panel with 🧠 icon in gray
- **Actual Time:** 15 minutes
- **Lines modified:** 
  - 1504: Added reasoning_buffer attribute
  - 2509: Reset reasoning buffer on new stream
  - 2530-2538: Route chunks to correct buffer based on is_reasoning flag
  - 2574-2584: Display reasoning panel with gray dim styling
  - 2604, 2122, 2640: Reset reasoning buffer at stream boundaries
- **Result:** Two separate panels - reasoning in gray, content in regular styling

### 3. Strengthen Tool Acknowledgment Rules in Prompts ✅
- **File:** `penguin/prompt_workflow.py`
- **Status:** ✅ COMPLETED
- **Issue:** AI executes code twice without acknowledging first result (827561 → 670326)
- **Fix:** Added explicit warnings with user's exact duplicate execution example
- **Actual Time:** 8 minutes
- **Lines modified:** 452-504, 581-618 (both OUTPUT_STYLE sections)
- **Key addition:** "CRITICAL - PREVENTS DUPLICATE EXECUTION" with real case study

### 4. Fix Code Block Formatting in Prompts ✅
- **File:** `penguin/prompt_workflow.py`
- **Status:** ✅ COMPLETED
- **Issue:** Generated code has `import randomdef` instead of proper newlines
- **Fix:** Added 5 critical rules with BAD/GOOD examples showing exact user issue
- **Actual Time:** 7 minutes
- **Lines modified:** 401-450, 502-538 (enhanced formatting guidance)
- **Key addition:** "MANDATORY blank line after imports" rule with examples

---

## Medium Priority Tasks

### 5. Add `--no-tui` Flag Support ✅
- **File:** `penguin/cli/old_cli.py`
- **Status:** ✅ COMPLETED
- **Issue:** `--no-tui` flag exists in cli_new.py but not in old_cli.py (active CLI)
- **Fix:** Added flag to main_entry() and headless detection logic
- **Actual Time:** 5 minutes
- **Lines modified:** 491-494 (parameter), 561-593 (headless detection)
- **Result:** `uv run penguin --no-tui` now works without error

### 6. Add CLI-Specific Reasoning Format to Prompts ✅
- **File:** `penguin/prompt_workflow.py`
- **Status:** ✅ COMPLETED
- **Issue:** HTML `<details><summary>` tags don't render in terminal
- **Fix:** Split reasoning guidance into CLI (gray text) vs TUI (HTML) modes
- **Actual Time:** 10 minutes
- **Lines modified:** 506-539, 641-669 (both output style sections)
- **Result:** AI will use `[dim]` gray text in CLI, `<details>` in TUI/Web

### 7. Reduce Reasoning Verbosity ✅
- **File:** `penguin/prompt_workflow.py`
- **Status:** ✅ COMPLETED
- **Issue:** Reasoning sections too long (451 words in test case)
- **Fix:** Added explicit 60-word maximum for CLI reasoning
- **Actual Time:** 3 minutes (combined with Task 6)
- **Lines modified:** 520-521, 656 (word limits added)
- **Result:** AI will keep reasoning to 1-2 sentences in CLI mode

---

## Lower Priority Tasks

### 8. Buffer Tool Results for Proper Ordering
- **File:** `penguin/cli/old_cli.py`
- **Status:** Pending (OPTIONAL)
- **Issue:** Tool results display before assistant message that triggered them
- **Fix:** Buffer SYSTEM_OUTPUT messages until streaming completes
- **Estimated Time:** 1 hour
- **Lines to modify:** 2578-2582, 2450-2463, add pending_tool_results buffer
- **Complexity:** Medium - requires careful async handling

---

## Implementation Checklist

**Before Starting:**
- [x] Analyze current code and identify root causes
- [x] Document all issues in CLI_ISSUES_ANALYSIS.md
- [ ] Confirm implementation priorities with user
- [ ] Ask clarifying questions (see below)

**During Implementation:**
- [ ] Create feature branch for CLI improvements
- [ ] Implement fixes in order of priority
- [ ] Test each fix individually
- [ ] Update this todo as tasks complete

**After Implementation:**
- [ ] Run manual test: `uv run penguin --old-cli`
- [ ] Verify no duplicate messages
- [ ] Verify reasoning appears in gray
- [ ] Verify code blocks format correctly
- [ ] Verify tools execute only once
- [ ] Test `--no-tui` flag works
- [ ] Clean up any debug logging added
- [ ] Update documentation if needed

---

## Questions Before Implementation

### Q1: Reasoning Token Display Style
Your config uses `client_preference: native` with `openai/gpt-5`. 

**Question:** Do you want reasoning tokens for ALL interactions, or only when using specific models?

**Options:**
- **A)** Always render reasoning-like content (from prompts) in gray
- **B)** Only render actual reasoning tokens (from API) in gray
- **C)** Make it configurable with a flag like `--show-reasoning`

**Current state:** 
- TUI shows reasoning in collapsible blocks
- CLI currently shows no distinction

**Recommendation:** Start with Option B (only real reasoning tokens), add Option C (flag) later if needed.

---

### Q2: Reasoning Display Format

For gray-text reasoning in CLI, which format do you prefer?

**Option A - Inline Gray Block (Recommended for CLI):**
```
╭─ 🐧 Penguin (Streaming) ─────────────────────────────────
│ 🧠 I'll search the codebase for auth logic, then check 
│    if caching exists.
│ 
│ Now implementing the authentication flow...
│ [rest of response]
╰──────────────────────────────────────────────────────────
```

**Option B - Separate Reasoning Section:**
```
╭─ 🐧 Reasoning ───────────────────────────────────────────
│ I'll search the codebase for auth logic, then check if
│ caching exists.
╰──────────────────────────────────────────────────────────
╭─ 🐧 Penguin ─────────────────────────────────────────────
│ Now implementing the authentication flow...
│ [rest of response]
╰──────────────────────────────────────────────────────────
```

**Recommendation:** Option A - keeps conversation flow cleaner, matches how humans think (reasoning → action).

---

### Q3: Tool Result Buffering Priority

Issue #3 (tool results appearing before assistant message) is lower priority but noticeable.

**Question:** Should I implement this now, or defer it?

**Trade-off:**
- **Implement now:** Better UX, proper conversation flow, 1 hour investment
- **Defer:** Focus on quick wins first, add later if users complain

**Recommendation:** Defer for now. The other fixes are more impactful and faster.

---

### Q4: Prompt Style Auto-Detection

Should the system automatically detect CLI vs TUI mode for reasoning formatting?

**Options:**
- **A)** Auto-detect based on which interface is running (CLI = gray text, TUI = collapsible)
- **B)** Use config setting: `output.reasoning_format: "cli" | "tui" | "web"`
- **C)** Always use the format specified in `output.prompt_style`

**Current behavior:** Same prompt for both CLI and TUI (uses HTML tags everywhere)

**Recommendation:** Option A with fallback to config - detect interface type and apply appropriate formatting.

---

### Q5: Code Block Formatting Strictness

The AI sometimes generates malformed code blocks. How strict should enforcement be?

**Options:**
- **A)** Add strong warnings and examples in prompts (what I suggested)
- **B)** Add post-processing to fix common errors (auto-add newlines after imports)
- **C)** Both A and B

**Recommendation:** Start with A (prompt fixes), add B only if issues persist. Post-processing adds complexity.

---

### Q6: Implementation Order

**Suggested order (fastest to slowest):**

1. ✅ Remove duplicate user messages (2 min)
2. ✅ Add `--no-tui` flag (10 min)
3. ✅ Fix code formatting in prompts (10 min)
4. ✅ Strengthen tool acknowledgment rules (15 min)
5. ✅ Add CLI reasoning format to prompts (15 min)
6. ✅ Implement reasoning gray text in old_cli.py (20 min)
7. ⏸️ Buffer tool results (1 hour) - DEFER

**Total time for items 1-6:** ~1.5 hours

---

## Notes & Discoveries

### Reasoning Token Flow (Confirmed)

**YES, reasoning tokens ARE being fetched from the API!**

1. **OpenRouterGateway** extracts them: `reasoning_delta = delta_obj.get("reasoning")` (line 380)
2. Calls callback with: `await stream_callback(new_reasoning_segment, "reasoning")` (line 406)
3. **Core** tracks separately: `self._streaming_state["reasoning_content"] += chunk` (line 3040)
4. **TUI** renders differently: Uses collapsible `<details>` blocks with gray styling
5. **old_cli.py** IGNORES the flag: Doesn't check `is_reasoning`, mixes all content together

**Models with real reasoning tokens:**
- `openai/o1`, `openai/o3`, `openai/gpt-5`
- `deepseek/deepseek-r1`
- `google/gemini-2.5-pro:thinking`
- `anthropic/claude-4-*` (some variants)

**Your current model (`openai/gpt-5` with `native` client):**
- Should support reasoning IF the native OpenAI adapter extracts it
- OpenAI SDK v1.12.0+ exposes reasoning tokens in streaming delta
- Need to verify native adapter implementation supports this

---

## Testing Plan

### Manual Test Script

```bash
# 1. Test basic interaction (no duplicates)
uv run penguin --old-cli
> Are you a real penguin?
# Expected: User message appears only once

# 2. Test code execution (no duplicate execution)
> Write a function that prints a random number, execute it, tell me the result
# Expected: Code executes ONCE, AI acknowledges: "The result is X"

# 3. Test reasoning tokens (if using reasoning-enabled model)
> Solve this complex problem: [some problem]
# Expected: Reasoning appears in gray text above main response

# 4. Test --no-tui flag
uv run penguin --no-tui -p "Hello"
# Expected: Runs in headless mode, no error

# 5. Test code formatting
> Write a Python function to add two numbers
# Expected: Proper newlines, spacing, indentation
```

### Automated Tests (Future)

- [ ] Unit test for duplicate message detection
- [ ] Integration test for reasoning token rendering
- [ ] Snapshot test for panel formatting
- [ ] Test --no-tui flag with various combinations

---

## Open Questions

1. Should reasoning always be visible, or add a `--hide-reasoning` flag?
2. Do you want different reasoning styles for different task types (quick answers vs deep analysis)?
3. Should the CLI support toggling reasoning display like the TUI does (keybind)?

---

## Related Files

- `/Users/maximusputnam/Code/Penguin/penguin/CLI_ISSUES_ANALYSIS.md` - Detailed analysis
- `/Users/maximusputnam/Code/Penguin/penguin/penguin/cli/old_cli.py` - Main CLI implementation
- `/Users/maximusputnam/Code/Penguin/penguin/penguin/prompt_workflow.py` - System prompts
- `/Users/maximusputnam/Code/Penguin/penguin/penguin/llm/openrouter_gateway.py` - Reasoning token extraction
- `/Users/maximusputnam/Code/Penguin/penguin/penguin/core.py` - Reasoning token handling
- `/Users/maximusputnam/Code/Penguin/penguin/penguin/cli/tui.py` - TUI reasoning reference implementation

---

## Progress Tracker

**Round 1 Tasks:** 7 completed ✅  
**Round 2 Tasks:** 6 completed ✅  
**Round 3 Tasks:**
- ✅ Created /info command with docs link and explanation
- ✅ Added markdown preference over YAML to prompts  
- ✅ Created /reload-prompt command
- ✅ FIXED: Core not using latest prompt formatting

**Round 4 Tasks (Polish):**
- ✅ Fixed Internal Reasoning panel formatting (dim italic Text instead of Markdown)
- ✅ Fixed /help indentation (direct Panel instead of display_message)
- ✅ Fixed chronological ordering (buffer system outputs until streaming completes)
- ✅ Changed "Penguin (Streaming)" to just "Penguin"

**Round 5 Tasks (Duplication Fixes):**
- ✅ Removed duplicate action result display (commented out lines 2344-2360)
- ✅ Improved markdown stripping in reasoning (handles all bold/italic patterns)
- ✅ Added user's exact duplicate execution pattern (Example 2) to prompts

**Critical Bugs Found & Fixed:**
1. **PromptBuilder caching:** Now refreshes output_formatting on every build()
2. **Duplicate action results:** Event system displays them, removed redundant code
3. **Markdown in reasoning:** Now strips **, ***, __, ___, _, and collapses whitespace

**Remaining Issue:**
- ⚠️ AI still executing twice (down from 3x, but not ideal)
- Prompt rules are VERY explicit now
- May need to test with different model or add post-processing guard

**Total Implementation Time:** ~90 minutes across all rounds  
**Status:** ✅ MAJOR IMPROVEMENTS DONE, one remaining issue to monitor

**Verification (just ran):**
```bash
✅ Prompt length: 40,416 characters
✅ Contains "MANDATORY blank line after imports": YES
✅ Contains "yamldata:" bad example: YES
```

**The prompt NOW includes all our formatting rules!**

---

## 🧪 Testing Results & Next Steps

**Latest Test (Fresh Conversation):**
- ✅ Executes ONCE (not 3x) - Fixed!
- ✅ Acknowledges result: "Got it: 179885" - Fixed!
- ⚠️ Code still had `import randomdef` - But AI was aware and corrected it

**All Polish Fixes Applied:**
1. ✅ Reasoning panels use dim italic gray text
2. ✅ /help displays without indentation
3. ✅ Tool results appear AFTER assistant messages (buffered during streaming)
4. ✅ Panel titles say "Penguin" not "Penguin (Streaming)"

**Expected Behavior (Fresh Conversation):**
```bash
# Exit and restart for fully updated prompts
exit
uv run penguin --old-cli

# Test:
You [0]: Write a function that prints a random number, execute it, tell me the result

# Should see:
╭─ 👤 You ───────────────────────────
│ [your message]
╰─────────────────────────────────────
╭─ Internal Reasoning ────────────────  [gray dim text]
│ 🧠 [brief reasoning]
╰─────────────────────────────────────
╭─ 🐧 Penguin ───────────────────────  [NOT "Penguin (Streaming)"]
│ Running a function...
│ [properly formatted code with newlines]
╰─────────────────────────────────────
╭─ 🐧 System ─────────────────────────  [AFTER Penguin message]
│ Tool Result (execute): 179885
╰─────────────────────────────────────
╭─ 🐧 Penguin ────────────────────────
│ The result is 179885.  [acknowledges, STOPS]
╰─────────────────────────────────────
```

---

## Implementation Notes

### For Task #2 (Reasoning Gray Text):

Key data available in `stream_chunk` events:
- `is_reasoning: bool` - Whether this chunk is reasoning vs regular content
- `message_type: str` - "reasoning" or "assistant"
- `reasoning_so_far: str` - Accumulated reasoning content
- `content_so_far: str` - Accumulated regular content

**Implementation strategy:**
1. Add `streaming_reasoning_buffer` attribute to PenguinCLI class
2. In `handle_event()`, check `is_reasoning` flag
3. If reasoning: accumulate in reasoning buffer, display with `[dim]🧠` prefix
4. If regular: accumulate in regular buffer
5. Panel shows: `[gray reasoning]\n\n[regular content]`

### For Task #3 (Tool Acknowledgment):

Add explicit "NEVER DO THIS" examples showing duplicate execution:
- Show the exact pattern from the user's test case (827561 → 670326)
- Emphasize: "If you see Tool Result: X, your NEXT message MUST start with acknowledging X"
- Add detection pattern: "Check previous message for tool results before executing"

---

## Success Criteria

- [ ] `uv run penguin --no-tui` works without error
- [ ] User messages appear exactly once
- [ ] Reasoning tokens display in gray text (when available)
- [ ] Code blocks have proper formatting (newlines after imports)
- [ ] Tools execute exactly once per request
- [ ] AI acknowledges tool results before continuing
- [ ] No system messages appear above assistant messages (if buffering implemented)

---

## Future Enhancements (Post-MVP)

- [ ] Add `--reasoning-style` flag to control reasoning display
- [ ] Implement reasoning toggle keybind in CLI (like TUI's 'r' key)
- [ ] Add reasoning token cost tracking in output
- [ ] Support reasoning-only mode (show reasoning, hide answer)
- [ ] Add reasoning summary at end of response ("Thought for X tokens")

---

## Round 6 Tasks (2025-09-30): Critical Hybrid State Issues

### Issue Analysis from User's Penguin Run
**Source:** Session log showing visual contamination and tool failures

### 9. Fix Display Contamination in Tool Results 🔥 ✅
- **File:** `penguin/utils/notebook.py`, `penguin/tools/tool_manager.py`
- **Status:** ✅ COMPLETED
- **Issue:** Rich-formatted output (panels, borders, ANSI codes) bleeding into subprocess stdout
- **Evidence:** Lines 90-103 in user's log show:
  ```
  \u001b[34m\u256d\u2500\u001b[0m\u001b[34m 🐧 Penguin \u001b[0m...
  ```
- **Root Cause:** Code being executed triggers Rich display that gets captured by subprocess
- **Fix:** Suppress Rich ANSI codes during tool execution
  ```python
  env = os.environ.copy()
  env['TERM'] = 'dumb'  # Disables Rich formatting
  env['NO_COLOR'] = '1'
  env['RICH_NO_MARKUP'] = '1'
  ```
- **Estimated Time:** 15 minutes
- **Priority:** HIGH - Breaks tool output readability

### 10. Fix Console State Confusion in cli.py ✅
- **File:** `penguin/cli/cli.py`
- **Status:** ✅ COMPLETED
- **Issue:** `self.console = None` (line 2065) but methods still call `self.console.print()`
- **Evidence:** 
  - Line 2065: `self.console = None`
  - Line 2367, 2393: Code tries to use `self.console.print()`
- **Root Cause:** Incomplete conversion from Rich CLI to headless CLI
- **Fix Options:**
  - **Option A (Recommended):** Remove all `self.console` references, use plain print
  - **Option B:** Initialize simple console: `self.console = Console(no_color=True, legacy_windows=False)`
- **Lines to modify:** 2065, 2367, 2393, and audit entire `PenguinCLI` class
- **Estimated Time:** 30 minutes
- **Priority:** HIGH - Prevents crashes in headless mode

### 11. Fix Regex Escaping in edit_with_pattern Tool ✅
- **File:** `penguin/tools/core/support.py`, `penguin/utils/parser.py`, `penguin/tools/plugins/core_tools/main.py`
- **Status:** ✅ COMPLETED  
- **Issue:** Tool failed on patterns AND truncated replacement text containing colons
- **Evidence from user's log:**
  - Line 687: `"missing ), unterminated subpattern at position 62"`
  - Line 750: `"No matches found"` after trying `\\\\\\(note::`
  - Line 896: Replacement "note: it's ~90%" got truncated to just "(note"
- **Root Causes:**
  1. No regex validation before execution
  2. **CRITICAL BUG:** Parser used `split(":", 3)` but replacement text contains colons!
  3. Plugin handler passed dict instead of individual args
- **Fixes Applied:**
  1. Added regex validation + helpful error messages (`support.py`)
  2. **Changed parser to `rsplit` + `split(":", 2)`** to preserve colons in replacement (`parser.py`)
  3. Fixed plugin handler signature mismatch (`core_tools/main.py`)
- **Actual Time:** 35 minutes
- **Priority:** 🔥 CRITICAL - Was silently corrupting data!

### 12. Fix Duplicate Reasoning Display ✅
- **File:** `penguin/cli/old_cli.py`
- **Status:** ✅ COMPLETED
- **Issue:** Assistant message appears twice - raw and formatted versions
- **Evidence:** Lines 63-87 show duplicate content with/without `<details>` blocks
- **Root Cause:** `_extract_and_display_reasoning()` (lines 1590-1636) not checking if already displayed
- **Fix:** Add guard to prevent re-displaying already-formatted reasoning
  ```python
  def _extract_and_display_reasoning(self, message: str) -> str:
      # Check if message already has reasoning extracted
      if hasattr(self, '_last_reasoning_extracted') and \
         message == self._last_reasoning_extracted:
          return message
      # ... rest of method
      self._last_reasoning_extracted = message
  ```
- **Estimated Time:** 10 minutes
- **Priority:** LOW - Cosmetic issue

### 13. Fix "Only one live display may be active at once" Error ✅
- **File:** `penguin/cli/old_cli.py`
- **Status:** ✅ COMPLETED
- **Issue:** Rich throws error when Progress and Live streaming contexts overlap
- **Evidence:** User's screenshot shows "Error processing event: Only one live display may be active at once"
- **Root Cause:** `self.progress` (Progress context) and `self.streaming_live` (Live context) both active simultaneously
- **Fix:** Stop progress before starting streaming display (line 2573)
  ```python
  # CRITICAL: Stop any active progress display FIRST
  self._safely_stop_progress()
  ```
- **Actual Time:** 5 minutes
- **Priority:** 🔥 CRITICAL - Breaks streaming display

---

## Round 6 Implementation Plan

**Order (by severity):**
1. 🔥 Task #9: Fix display contamination (blocks clean output)
2. 🔥 Task #10: Fix console state (prevents crashes)
3. 🔥 Task #11: Fix edit_with_pattern parser (was corrupting data!)
4. 🔥 Task #13: Fix "Only one live display" error (breaks streaming)
5. ⚪ Task #12: Fix duplicate reasoning (polish)

**Total Estimated Time:** 1.5 hours  
**Actual Time:** ~45 minutes

**Testing Plan:**
```bash
# Test 1: Tool execution should be clean
uv run penguin --old-cli -p "run: print('hello world')"
# Expected: No ANSI codes in output

# Test 2: Headless mode should work
uv run penguin -p "hello"
# Expected: No AttributeError crashes

# Test 3: Edit patterns with parentheses
# (Test via actual tool usage in conversation)
# Expected: Proper escaping guidance or auto-handling

# Test 4: No duplicate reasoning
uv run penguin --old-cli
> "complex task"
# Expected: Reasoning appears once, in correct format
```

---

## Round 6 Implementation Summary ✅

**Completed:** 2025-09-30  
**Total Time:** ~45 minutes (discovered 2 additional critical bugs!)

### Changes Made:

#### 1. ✅ Task #9: Display Contamination Fixed
**Files Modified:**
- `penguin/utils/notebook.py` (lines 31-66, 121-125)
- `penguin/tools/tool_manager.py` (lines 1636-1640)

**Changes:**
- Added environment variable suppression before code/command execution
- Set `TERM=dumb`, `NO_COLOR=1`, `RICH_NO_MARKUP=1`
- Properly restore original environment after execution
- Applied to both `execute_code()` and `execute_shell()` methods

**Impact:** Tool outputs will now be clean, no ANSI escape codes

#### 2. ✅ Task #10: Console State Fixed
**Files Modified:**
- `penguin/cli/cli.py` (lines 2065-2067)

**Changes:**
- Changed `self.console = None` to `Console(no_color=True, legacy_windows=False, force_terminal=False)`
- Prevents AttributeErrors while maintaining headless behavior

**Impact:** No more crashes when methods call `self.console.print()`

#### 3. ✅ Task #11: Regex Escaping Fixed
**Files Modified:**
- `penguin/tools/core/support.py` (lines 1420-1434)

**Changes:**
- Added regex validation with `re.compile()` before `re.sub()`
- Added helpful error message explaining common escaping issues
- Provides specific guidance on escaping parentheses, dots, etc.

**Impact:** Better UX when regex patterns fail, clear guidance for fixes

#### 4. ✅ Task #11 CRITICAL ADDITION: Parser Split Bug Fixed
**Files Modified:**
- `penguin/utils/parser.py` (lines 1497-1530)
- `penguin/tools/plugins/core_tools/main.py` (lines 375-381)

**Critical Bug Found:**
- Parser used `params.split(":", 3)` which BREAKS on replacement text containing colons!
- Example: `file.md:pattern:text (note: details):true`
  - Got split into: `["file.md", "pattern", "text (note", " details):true"]`
  - Replacement was TRUNCATED to "text (note"!

**Changes:**
- Use `rsplit(":", 1)` to extract backup flag from end first
- Then `split(":", 2)` to preserve all colons in replacement text
- Fixed plugin handler to pass individual args, not dict

**Impact:** Tool now handles colons, punctuation, URLs in replacement text correctly!

#### 5. ✅ Task #13: "Only one live display" Error Fixed
**Files Modified:**
- `penguin/cli/old_cli.py` (line 2573)

**Changes:**
- Call `self._safely_stop_progress()` BEFORE starting `streaming_live`
- Prevents Rich Live() context manager conflicts

**Impact:** No more "Only one live display may be active at once" errors during streaming

#### 6. ✅ Task #12: Duplicate Reasoning Fixed
**Files Modified:**
- `penguin/cli/old_cli.py` (lines 1598-1599, 1639-1640)

**Changes:**
- Added guard `_last_reasoning_extracted` to prevent re-processing
- Marks processed messages to avoid duplicate display

**Impact:** Reasoning blocks appear exactly once

### Verification:
- ✅ All files lint clean (no Ruff errors)
- ✅ Changes follow existing code patterns
- ✅ Proper error handling and cleanup
- ✅ Backward compatible (no breaking changes)
- ✅ Tested: clean subprocess output confirmed
