# Penguin Prompting Improvements - Actionable Recommendations

Based on analysis of `cli-run-3.txt`, Codex comparison, and prompt architecture review.

## Critical Issues Found

### 1. Meta-Commentary Still Occurring (P0)

**Problem:** Despite `META_COMMENTARY_WARNING`, agent in `cli-run-3.txt` said:
> "I need to first understand the actual project structure. Let me start over with proper investigation:"

**Root Causes:**
1. **Contradictory guidance** - `system_prompt.py:77` encourages internal monologue (*italics*)
2. **Warning buried** - Appears after 700+ lines in prompt
3. **Not reinforced** - Only mentioned once in output formatting section

**Fixes:**

#### Fix 1.1: Remove Contradictory Line
```python
# REMOVE from system_prompt.py line 77:
- "Internal Monologue: Use *italicized text* for brief, simulated internal thoughts or planning steps."

# REPLACE with:
+ "Internal thoughts stay internal. Never externalize planning steps or reasoning process."
```

#### Fix 1.2: Elevate Warning to Top
```python
# In prompt/builder.py, add to beginning of _build_direct():
def _build_direct(self) -> str:
    return (
        "🚫 CRITICAL RULE: Never externalize internal reasoning. Just execute tools, then respond with findings.\n\n" +
        self.components.base_prompt +
        # ... rest
    )
```

#### Fix 1.3: Add Immediate Enforcement Pattern
```python
# Add to prompt_workflow.py OUTPUT_STYLE_STEPS_FINAL (near beginning):
"""
**BEFORE EVERY RESPONSE:**
1. Did I explain what I'm about to do? → DELETE IT
2. Did I list my internal steps? → DELETE IT  
3. Did I acknowledge tool results? → YES, then proceed

Only output: Tool calls → Results → Final answer
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

### 6. Specific Prompt Improvements

#### 6.1: Clarify Tool Result Handling (Most Common Error)

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

## Questions for User

1. **Internal monologue**: Do you want to keep the *italicized thoughts* feature? If yes, we need clearer boundaries (planning OK, process explanation NOT OK).

2. **Prompt length**: Is <15k tokens acceptable, or should we target <10k?

3. **Mode priority**: Which modes need the most work? (Review mode mentioned as P0)

4. **Codex parity**: How important is matching Codex's terseness vs keeping Penguin's thoroughness?

