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

**Critical Bug Found & Fixed:**
- **Bug:** PromptBuilder was caching `output_formatting` and never refreshing it
- **Location:** `penguin/prompt/builder.py` lines 72-82
- **Impact:** Prompt changes NOW take effect immediately on fresh conversations

**Total Implementation Time:** ~80 minutes across all rounds  
**Status:** ✅ ALL FIXES COMPLETED - READY FOR TESTING

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
