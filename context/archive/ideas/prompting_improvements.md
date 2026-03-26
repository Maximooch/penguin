# Penguin Prompting Improvements - Actionable Recommendations

Based on analysis of `cli-run-3.txt`, Codex comparison, and prompt architecture review.

## Critical Issues Found

### 1. Process Explanation in Main Messages (P0)

**Problem:** Agent outputs process explanation in main message content (not reasoning blocks):
> "I need to first understand the actual project structure. Let me start over with proper investigation:"

**Root Causes:**
1. **Unclear distinction** - Prompt doesn't clarify: planning (OK) vs process explanation (NOT OK)
2. **Contradictory guidance** - `system_prompt.py:77` encourages internal monologue (*italics*) which blurs boundaries
3. **Warning buried** - Meta-commentary warning appears after 700+ lines, focuses on reasoning blocks
4. **CLI renders faithfully** - CLI already handles reasoning collapse; problem is agent putting verbosity in main content

**Fixes:**

#### Fix 1.1: Clarify Planning vs Process Explanation
```python
# REMOVE from system_prompt.py line 77:
- "Internal Monologue: Use *italicized text* for brief, simulated internal thoughts or planning steps."

# REPLACE with explicit distinction:
+ """
+ **Internal Planning vs Process Explanation:**
+ - ✅ Planning thoughts are OK: Brief *italicized* thoughts about approach (hidden by default in CLI)
+ - ❌ Process explanation is NOT OK: Never say "Let me start by...", "I need to...", "Following my instructions..."
+ - ❌ Step-by-step explanations are NOT OK: Don't list what you're about to do
+ - ✅ Just execute tools → Acknowledge results → Provide answer
+ """
```

#### Fix 1.2: Add Output Verbosity Rule to Top
```python
# In prompt/builder.py, add to beginning of _build_direct():
def _build_direct(self) -> str:
    return (
        """**OUTPUT STYLE (Codex/Cursor/Claude Code Pattern):**

Show your work, not your process:
- ✅ Execute tools → Show results → Answer the question
- ❌ Never say: "Let me start by...", "I need to...", "I'll check...", "Following instructions..."
- ❌ Never list: "1. First I'll... 2. Then I'll... 3. Finally..."
- ✅ If uncertain: Ask clarifying question, don't explain your uncertainty
- ✅ Planning OK: Brief *italicized* thoughts (goes to reasoning block, hidden by default)

Match Codex/Cursor directness: Answer → Evidence → Done
"""
        +
        self.components.base_prompt +
        # ... rest
    )
```

#### Fix 1.3: Add Pattern Detection Guide
```python
# Add to prompt_workflow.py OUTPUT_STYLE_STEPS_FINAL:
"""
**FORBIDDEN PHRASES (Delete immediately if generated):**
- "Let me start by..."
- "I need to first..."
- "Following my instructions..."
- "I'll check..."
- "Let me investigate..."
- "Now I'll..."
- "Based on my analysis so far..." (before showing results)

**CORRECT PATTERN:**
❌ "Let me check the file structure first. I'll look for..."
✅ <list_files_filtered>.</>
   <enhanced_read>file.py</enhanced_read>
   The file structure shows...

❌ "Following the workflow, I should first verify then implement..."
✅ <enhanced_read>current.py</enhanced_read>
   Implementing the fix:
   <apply_diff>...
"""
```

### 2. Workspace vs Project Root Confusion (P0)

**Problem:** Agent looked in `/Users/maximusputnam/penguin_workspace/` instead of `/Users/maximusputnam/Code/Penguin/penguin/`

**Root Cause:** Prompt doesn't clarify path resolution strategy

**Fix:** Add explicit workspace guidance to `BASE_PROMPT`:

```python
# Add after "Operational Environment" section:
**--- Path Resolution (CRITICAL) ---**

When resolving file paths:
1. **Project Root**: Code repository root (where `.git`, `pyproject.toml`, etc. live)
   - Detected via: git root, `PENGUIN_PROJECT_ROOT` env var, or `project.root_strategy` config
   - Default location: Where you were invoked (usually cwd)

2. **Workspace Root**: Separate workspace directory (different from project!)
   - Location: `$PENGUIN_WORKSPACE` or `~/.penguin_workspace`
   - Used for: Session data, memory, temporary files
   - NOT for: Reading source code (that's project root)

3. **Path Resolution Rules:**
   - Relative paths resolve relative to PROJECT ROOT (not workspace)
   - Tools automatically resolve to correct root based on operation type
   - If confused, use absolute paths from tool output (they show resolved path)

**Common Mistake:** Looking in workspace when file is in project root.
**Solution:** Always check project root first for source code.
```

### 3. Prompt Verbosity Issues (P1)

**Current State:**
- `BASE_PROMPT`: ~200 lines
- `ACTION_SYNTAX`: ~700 lines  
- `OUTPUT_STYLE_STEPS_FINAL`: ~230 lines
- **Total: ~1100+ lines**

**Issues:**
- Redundant guidance (same rule mentioned 3-4 times)
- Excessive examples (BAD/GOOD patterns repeated)
- Not prioritized (critical rules buried)

**Recommended Streamlining:**

#### 3.1: Consolidate Safety Rules
```python
# Current: Mentioned in SAFETY_RULES, CORE_PRINCIPLES, MULTI_STEP_SECTION, ACTION_SYNTAX
# Fix: Single canonical source, referenced everywhere

SAFETY_CANON = """
**Non-Negotiable Safety Rules:**
1. Pre-write check: `Path(file).exists()` before write
2. Use `apply_diff`/`multiedit` (auto-backups)
3. Respect permission engine (allow/ask/deny)
4. Verify touched files only (not global scans)
"""
```

#### 3.2: Reduce Example Verbosity
```python
# Current: 10+ BAD/GOOD examples in OUTPUT_STYLE
# Fix: Keep 2-3 most critical, move rest to reference doc

OUTPUT_STYLE_COMPACT = """
**Critical Formatting Rules:**
- Fenced blocks: ```language\n then NEWLINE (not ```languagecode)
- Blank line after Python imports (PEP 8)
- Tool results: Acknowledge BEFORE next action

[Keep 2 key examples max, reference detailed guide for edge cases]
"""
```

#### 3.3: Prioritize Critical Sections
```python
# Reorder prompt assembly to put critical rules first:
1. Meta-commentary prohibition (FIRST)
2. Path resolution (immediately after)
3. Safety rules (consolidated)
4. Tool syntax (reference style, not tutorial)
5. Output formatting (minimal)
6. Advanced guides (last)
```

### 4. Workflow Clarity (P1)

**Issue:** Multiple overlapping workflow descriptions

**Current:**
- `MULTI_STEP_SECTION` - Multi-step process
- `PENGUIN_WORKFLOW` - Development workflow  
- `MULTI_TURN_INVESTIGATION` - Investigation process
- Task type strategies in `BASE_PROMPT`

**Fix:** Single canonical workflow, referenced by mode:

```python
# Core workflow (universal):
CORE_WORKFLOW = """
1. **Understand** (if unclear): Read relevant files first
2. **Plan** (if multi-step): Brief internal plan, optional scratchpad
3. **Execute**: Tools → Wait for results → Acknowledge → Proceed
4. **Verify**: Check only what changed (not global scans)
5. **Iterate**: Continue until complete or blocked
"""

# Mode-specific variations reference this core
```

### 5. Codex Comparison Findings

**Codex Strengths Penguin Should Adopt:**

1. **Terse, Direct Statements**
   - Codex: "Execute code to accomplish the user's goal"
   - Penguin: [3 paragraphs explaining execution strategy]
   - **Fix:** Lead with direct statement, expand only if needed

2. **Single Source of Truth**
   - Codex: Tool docs in one place, referenced
   - Penguin: Tool docs duplicated across files
   - **Fix:** `ACTION_SYNTAX` as canonical source, modes reference it

3. **Mode-Specific Prompts**
   - Codex: Different prompts for review vs implementation
   - Penguin: Has modes but deltas are small
   - **Fix:** Make mode deltas more substantial (see profiles.py)

### 6. Output Verbosity Control (Primary Focus)

#### 6.1: Match Codex/Cursor/Claude Code Output Style

**Current Problem:** Agent outputs like a verbose assistant explaining its process.

**Target Style (Codex/Cursor/Claude Code):**
- Direct answers
- Tool results shown inline
- No process explanation
- Minimal preamble

**Implementation:**
```python
# Add to BASE_PROMPT after "Response Strategy":
**--- Output Style (Codex Pattern) ---**

Your responses should match Codex/Cursor/Claude Code directness:

**CORRECT (Direct):**
```python
<read_file>path/to/file.py</read_file>
[Tool result shows the bug at line 42]

Fixed by correcting the validation logic:
<apply_diff>path/to/file.py
  @@ -40,5 +40,6 @@
   def validate(data):
-     if not data:
+     if not data or len(data) == 0:
        raise ValueError("Empty data")
```

**WRONG (Verbose Process Explanation):**
```
Let me first check the file to understand the issue. I'll read the code and then analyze what's wrong.

Following my workflow, I should:
1. Read the file
2. Identify the bug
3. Fix it

[Tool call]

Based on my analysis, I found the issue. Now I'll implement the fix...
```

**Rules:**
- Never explain what you're about to do
- Never list your steps
- Just: Execute → Show → Answer
- If planning, use *brief italics* (goes to reasoning block, hidden)
```

#### 6.2: Clarify Tool Result Handling (Most Common Error)

**Current:** Buried in `TOOL_RESULT_HANDLING`, mixed with exploration vs implementation rules

**Fix:** Elevate to prominent position with clear pattern:

```python
TOOL_RESULT_HANDLING_ELEVATED = """
**⚠️ Tool Results (READ THIS FIRST):**

Tool results appear in NEXT system message. Your workflow:

1. **You call tool:** `<enhanced_read>file.py</enhanced_read>`
2. **System responds:** [Tool result with file contents]
3. **You acknowledge:** "Got it: file.py shows X function..."
4. **Then proceed:** Based on what you learned

**CRITICAL ERROR TO AVOID:**
❌ Calling tool → Not waiting → Calling again → Confusion

✅ Calling tool → Waiting → Acknowledging → Acting
```

#### 6.2: Simplify Exploration vs Implementation Distinction

**Current:** Complex rules about when to acknowledge vs stay silent

**Fix:** Simpler rule:

```python
EXPLORATION_RULE = """
**For exploration tasks (analyze, understand, research):**
- Execute tools silently (no "now checking..." messages)
- Gather all information first
- Respond ONCE with complete findings

**For implementation tasks (fix, create, implement):**
- Acknowledge tool results for critical changes
- Provide brief status for long operations
- Focus on verification of changes
```

#### 6.3: Path Resolution Examples

**Add concrete examples to prompt:**

```python
PATH_EXAMPLES = """
**Examples:**

✅ CORRECT:
User: "Check penguin/cli.py"
You: <enhanced_read>penguin/cli.py</enhanced_read>
      [If file exists in project root, tool finds it]

❌ WRONG:
User: "Check penguin/cli.py"  
You: <enhanced_read>/Users/.../penguin_workspace/penguin/cli.py</enhanced_read>
      [Looking in workspace instead of project root]

**Rule:** Always use relative paths. Tools resolve to correct root automatically.
```

## Implementation Priority

### Phase 1 (Immediate - 2-3 hours)
1. ✅ Remove contradictory internal monologue line
2. ✅ Elevate meta-commentary warning to top
3. ✅ Add path resolution guidance to BASE_PROMPT
4. ✅ Consolidate safety rules (remove duplication)

### Phase 2 (This Week - 5-6 hours)
1. ✅ Streamline OUTPUT_STYLE (226 → ~80 lines)
2. ✅ Add tool result handling elevation
3. ✅ Reorder prompt sections (critical first)
4. ✅ Add path resolution examples

### Phase 3 (Next Week - 8-10 hours)
1. ✅ Substantial mode deltas (review mode P0-P3 rubric)
2. ✅ Single canonical workflow
3. ✅ Reference docs for verbose examples
4. ✅ Test prompt changes with real sessions

## Testing Strategy

After each change:
1. Run `cli-run-3.txt` scenario again
2. Check for meta-commentary leakage
3. Verify path resolution clarity
4. Measure prompt token count (target: <15k tokens)
5. Test all modes still work correctly

## Success Metrics

- **Meta-commentary incidents:** 0 (currently ~20% of sessions)
- **Path confusion:** <5% (currently ~30% in complex scenarios)
- **Prompt length:** <15k tokens (currently ~20k+)
- **Agent comprehension:** Task success rate maintained or improved

## Implementation Priority (Updated Based on User Feedback)

### Phase 1 (Immediate - 1-2 hours)
1. ✅ Add output verbosity rule to top of prompt (match Codex/Cursor style)
2. ✅ Clarify planning (OK) vs process explanation (NOT OK)
3. ✅ Add forbidden phrases detection
4. ✅ Remove contradictory internal monologue line (or clarify boundaries)

### Phase 2 (This Week - 3-4 hours)
1. ✅ Streamline OUTPUT_STYLE (remove redundant examples)
2. ✅ Add path resolution guidance
3. ✅ Consolidate safety rules
4. ✅ Test with real sessions

### Phase 3 (Future)
1. ⏸ Mode system improvements (not priority now)
2. ⏸ Further prompt reduction (target ~10k tokens if possible, but quality > quantity)

## Key Insights from User Feedback

1. **Planning OK, Process Explanation NOT OK** - Clear distinction needed
2. **Output verbosity is main issue** - Not prompt length itself, but what agent outputs
3. **CLI already handles reasoning collapse** - Problem is agent putting verbosity in main messages
4. **Match Codex/Cursor/Claude Code style** - Direct answers, no process explanation
5. **Mode system not urgent** - Focus on core output verbosity first

