# Codex vs Penguin: Prompting Comparison & Action Items

## Executive Summary

After analyzing OpenAI Codex's prompts (`gpt_5_codex_prompt.md`, `prompt.md`, `review_prompt.md`), here are the key insights for Penguin:

**What to steal from Codex:**
1. Default conciseness ("be very concise; friendly coding teammate")
2. Clear safety model (explicit sandbox modes + approval policies)
3. Simple file references (`file.py:42` prominence)
4. Code review rubric (P0-P3 priority system)
5. `update_plan` tool pattern (cleaner than CHARTER+TRACK+SCRATCHPAD split)

**What Penguin does better:**
1. ITUV workflow (Implement-Test-**Use**-Validate) - "Use" step is unique
2. Enhanced file operations with automatic backups
3. Memory/search integration
4. PyDoll browser tools (anti-bot capabilities)
5. Multi-agent coordination infrastructure

**The core issue:** Personality vs behavior conflict
- Prompt says "be concise" AND "you have IQ 180, think like Elon/Linus"
- Creates verbose strategic tangents when users want quick fixes
- Codex picks ONE role: "Precise, safe, and helpful coding agent"

**The solution:** Mode system (already started in Phase 4)
- `direct` mode (default): Codex-style concise
- `mentor` mode (opt-in): Strategic advisor with IQ 180 framing
- `review` mode: Code review with P0-P3 rubric

---

## Key Metrics: Prompt Length Comparison

| Component | Codex | Penguin Current | Target |
|-----------|-------|-----------------|--------|
| Base prompt | ~40 lines | ~170 lines | ~60 lines |
| Action syntax | ~50 lines | 693 lines | ~300 lines |
| Output formatting | ~20 lines | 226 lines | ~60 lines |
| **Total** | **~110 lines** | **~1089 lines** | **~420 lines** |

**Penguin is ~10x longer than Codex.** Target: Reduce to ~4x (still richer, but not wasteful).

---

## User Feedback Integration

1. **Target user:** "Both" (aspiring founders + experienced devs)
   - **Action:** Mode system addresses this perfectly

2. **Context files:** "Could be simplified to 2-3 files or sections"
   - **Action:** Phase 2 consolidation (PLAN.md + PROGRESS.md + DOMAIN.md)
   - **Question:** Preference for 1-file vs 2-file vs 3-file approach?

3. **Permission engine:** Not yet implemented
   - **Action:** New Phase 0 added (implement before prompt streamlining)

4. **Prompt file structure:** "Codex also has 3 files"
   - **Clarification:** Keep 3-file split, focus on content reduction not structure

---

## Implementation Timeline

**Total time:** ~12-18 hours of focused work

- **Phase 0:** Permission Engine (4-6 hours)
- **Phase 1:** Prompt Streamlining (3-5 hours)
- **Phase 2:** Context & Planning (2-3 hours)
- **Phase 3:** Mode System (3-4 hours)

## Top 5 Immediate Changes (High ROI)

### 1. Implement Permission Engine (NEW Phase 0 - 4-6 hours)
**Why:** Currently referenced but doesn't exist - creates confusion

**Implementation:**
```python
# penguin/security/permission_engine.py
class PermissionMode(Enum):
    READ_ONLY = "read_only"
    WORKSPACE = "workspace"
    FULL = "full"

class PermissionEngine:
    def check_operation(self, op: Operation, path: str) -> PermissionResult:
        """Returns: ALLOW, ASK, DENY"""
```

**Prompt update:**
```markdown
## Permission Model (Active)
Current mode: workspace
You can: Read/write files in workspace/, run safe commands
You cannot: Modify files outside workspace/, git push
Requires approval: File deletion, process spawning
```

**Impact:** Codex-style safety clarity, removes vague references

---

### 2. Reorganize ACTION_SYNTAX (Keep all 693 lines of tool info - 1-2 hours)
**Current problem:** Tool documentation lacks clear organization

**Solution:** Add category headers, keep ALL tool descriptions
```python
ACTION_SYNTAX = """
## Core Actions (Organized by Category)

### File Operations
<enhanced_read>, <enhanced_write>, <apply_diff>, <multiedit>

### Code Execution
<execute>

### Search & Memory
<search>, <memory_search>, <perplexity_search>

### Project Management
<update_plan>  # NEW - Codex pattern
<task_create>, <project_create>

### Browser Automation
<pydoll_browser_*> tools

[Keep ALL 693 lines of tool capability documentation]
[Only remove redundant examples, NOT tool descriptions]
"""
```

**Impact:** Better organization, all tools remain discoverable

---

### 3. Streamline OUTPUT_STYLE from 226 → ~80 lines (2 hours)
**Current problem:** 80 lines of BAD/GOOD examples, 70 lines explaining duplicate execution bug

**Solution:** Condense to essential rules
```markdown
## Output Format (Essential Only)
1. Code blocks: Fenced with language tags (```python\n)
2. Tool results: ALWAYS acknowledge before proceeding
3. File references: Use file.py:42 format
4. Markdown preference: Lists over YAML (terminal readability)
```

**Impact:** ~150 line reduction (65%), keep essential formatting rules

---

### 4. Extract Strategic Advisor Persona to Mentor Mode (1 hour)
**Current problem:** Base prompt has 24 lines of "IQ 180, Elon/Linus" framing

**Solution:**
```python
# system_prompt.py - new minimal base
PERSONA_MINIMAL = """
You are Penguin, a software engineering agent.
Fact-based, helpful, clear. Use brief italicized thoughts for planning.
"""

# prompt/profiles.py - strategic advisor as opt-in
MENTOR_MODE_DELTA = """
Act as strategic advisor: Think like top engineers (Carmack, Torvalds).
Brutally honest, systems thinking, push beyond comfort zones.
"""
```

**Impact:** Default is Codex-style concise, strategic mode via `--mode mentor`

---

### 5. Add `update_plan` Tool + Review Mode (Codex Patterns - 3-4 hours)
**Current problem:** Agent manually edits 3 separate files (CHARTER, SCRATCHPAD, TRACK)

**Solution:** Single atomic tool
```python
@tool
def update_plan(current_step: str, completed: List[str],
                next_steps: List[str], blockers: List[str] = None):
    """Update context/PLAN.md atomically"""
```

**Review Mode (PRIORITY 1):**
```python
# Add P0-P3 code review rubric (Codex pattern)
REVIEW_MODE_DELTA = """
## Code Review Mode
### Priority Levels
- [P0] Critical: Blocks release (security, data loss)
- [P1] Urgent: Fix next cycle (correctness, bugs)
- [P2] Normal: Fix eventually (maintainability)
- [P3] Nice-to-have: Style improvements
"""
```

**Impact:**
- Cleaner planning workflow
- Structured code review capability
- Less manual context file editing

---

## Decisions Finalized ✅

### 1. Context File Structure:
✅ **Selected: 3 files** (PLAN.md + PROGRESS.md + DOMAIN.md)

### 2. Permission Engine Modes:
✅ **Workspace mode:** Full permissions (especially in containers)
✅ **Project mode:** Only what User grants in project root

### 3. Mode System Rollout:
✅ **Priority 1:** Review mode (P0-P3 rubric)
✅ **Priority 2:** Mentor mode (strategic advisor)

### 4. Tool Documentation:
✅ **Keep ALL capability descriptions** (all 693 lines)
✅ **Only reduce:** Styling examples, redundant explanations

### 5. Time Estimates:
✅ **Use hours/minutes, not weeks** (12-18 hours total)

---

## The Irony You Noted

> "Penguin's prompt tells itself to be concise while being verbose in its instructions. Codex's prompt is concise while instructing conciseness. Meta-alignment matters."

**This is the core insight.** The prompt itself should embody the behavior it's asking for.

**Actionable principle:** Every line in the prompt should justify its token cost. If we're telling the agent to be concise, the instruction itself must be concise.

---

## Next Steps (12-18 hours total)

### Phase 0: Permission Engine (4-6 hours)
- [ ] Implement `PermissionEngine` with mode enum
- [ ] Add config schema for `security.mode`
- [ ] Update prompts to reference actual engine
- [ ] Add Codex-style safety sections

### Phase 1: Prompt Streamlining (3-5 hours)
- [ ] Reorganize ACTION_SYNTAX with category headers (keep all 693 lines)
- [ ] Streamline OUTPUT_STYLE: 226 → 80 lines
- [ ] Extract persona to mentor mode
- [ ] Elevate file reference format

### Phase 2: Context & Planning (2-3 hours)
- [ ] Consolidate to 3 files: PLAN.md + PROGRESS.md + DOMAIN.md
- [ ] Implement `update_plan` tool
- [ ] Wire `load_project_instructions()` into pipeline

### Phase 3: Mode System (3-4 hours)
- [ ] Add `--mode` CLI flag
- [ ] Add `/mode` TUI command
- [ ] Implement `review` mode with P0-P3 (PRIORITY 1)
- [ ] Implement `mentor` mode (Priority 2)

**Target outcome:**
- OUTPUT_STYLE streamlined (65% reduction)
- ACTION_SYNTAX better organized (all tools kept)
- Codex-style directness by default
- Review mode for code quality
- Strategic advisor mode available
- Clear permission model with workspace/project distinction
