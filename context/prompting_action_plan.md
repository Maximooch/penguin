# Penguin Prompting: Immediate Action Plan

Based on Codex analysis and user feedback, here's the prioritized action plan for transforming Penguin's prompting system.

## Critical User Feedback

1. ✅ **Target user:** Both aspiring founders AND experienced devs → Mode system solves this
2. ✅ **Context files:** 3 files preferred (PLAN.md + PROGRESS.md + DOMAIN.md)
3. ❌ **Permission engine:** Not implemented yet → Critical blocker
4. ✅ **Prompt structure:** Codex also has 3 files → Keep structure, reduce content
5. ✅ **Tool documentation:** Keep ALL tool info in prompt - can reduce styling/examples, but NOT capability descriptions
6. ✅ **Mode priority:** Implement `review` mode first (P0-P3 rubric), then `mentor`
7. ✅ **Permission defaults:**
   - Workspace mode: Full permissions (especially in containers)
   - Project root: Only what User grants explicitly

---

## Phase 0: Permission Engine (CRITICAL - 4-6 hours)

**Status:** Referenced in prompts but doesn't exist

### Why This Is Blocking
- Prompts mention "permission engine" 12+ times
- No actual implementation exists
- Creates confusion about what's allowed/denied
- Can't test safety model without it

### Implementation Plan

#### Step 1: Core Permission Engine
```python
# penguin/security/permission_engine.py
from enum import Enum
from pathlib import Path
from typing import List, Tuple

class PermissionMode(Enum):
    READ_ONLY = "read_only"      # Search, analyze only
    WORKSPACE = "workspace"       # Full perms in workspace (especially containers)
    PROJECT = "project"           # Only what User grants in project root

class PermissionResult(Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"

class PermissionEngine:
    def __init__(self, mode: PermissionMode, config: dict):
        self.mode = mode
        self.allowed_paths = [Path(p) for p in config.get("allowed_paths", [])]
        self.denied_paths = [Path(p) for p in config.get("denied_paths", [])]
        self.require_approval = config.get("require_approval", [])

    def check_file_operation(self, operation: str, path: Path) -> PermissionResult:
        """Check if file operation is allowed"""
        # Deny system paths
        if self._is_system_path(path):
            return PermissionResult.DENY

        # Check explicit denylists
        if self._matches_denied_path(path):
            return PermissionResult.DENY

        # Mode-specific logic
        if self.mode == PermissionMode.READ_ONLY:
            return PermissionResult.ALLOW if operation == "read" else PermissionResult.DENY

        if self.mode == PermissionMode.WORKSPACE:
            if self._is_workspace_path(path):
                return self._check_operation_approval(operation)
            return PermissionResult.DENY

        # FULL mode
        return self._check_operation_approval(operation)

    def _check_operation_approval(self, operation: str) -> PermissionResult:
        """Check if operation requires approval"""
        if operation in self.require_approval:
            return PermissionResult.ASK
        return PermissionResult.ALLOW

    def get_capabilities_summary(self) -> dict:
        """Get what agent can/cannot do"""
        if self.mode == PermissionMode.READ_ONLY:
            return {
                "can": ["Read files", "Search", "Analyze"],
                "cannot": ["Write files", "Delete", "Run commands"],
                "requires_approval": []
            }
        # ... etc for other modes
```

#### Step 2: Config Schema
```yaml
# penguin.yaml (add to schema)
security:
  mode: workspace  # read_only | workspace | full
  allowed_paths:
    - "workspace/**"
    - "src/**"
  denied_paths:
    - ".env"
    - "**/*secret*"
    - "**/*credential*"
  require_approval:
    - "file_delete"
    - "git_push"
    - "process_spawn"
```

#### Step 3: Prompt Integration
```python
# In system_prompt.py
def get_permission_section(engine: PermissionEngine) -> str:
    caps = engine.get_capabilities_summary()
    return f"""
## Permission Model (Active)
Current mode: {engine.mode.value}

**You can:**
{chr(10).join(f"- {item}" for item in caps["can"])}

**You cannot:**
{chr(10).join(f"- {item}" for item in caps["cannot"])}

**Requires approval:**
{chr(10).join(f"- {item}" for item in caps["requires_approval"])}
"""
```

#### Step 4: Tool Integration
```python
# Wrap file operations
@tool
def enhanced_write(path: str, content: str, backup: bool = True):
    permission_result = permission_engine.check_file_operation("write", Path(path))

    if permission_result == PermissionResult.DENY:
        return f"Permission denied: Cannot write to {path} in {engine.mode.value} mode"

    if permission_result == PermissionResult.ASK:
        # Trigger approval flow (user confirmation)
        return f"Approval required to write {path}. Confirm? (y/n)"

    # ALLOW - proceed with write
    # ... existing write logic
```

### Deliverables
- [ ] `penguin/security/permission_engine.py` (200 lines)
- [ ] Config schema updates
- [ ] Prompt updates (remove vague references, add clear sections)
- [ ] Tool wrapper integration
- [ ] Tests for permission logic
- [ ] Documentation: [security_model.md](security_model.md)

**Time estimate:** 4-6 hours

---

## Phase 1: Prompt Streamlining (3-5 hours)

### Target: Reduce OUTPUT_STYLE from 226 → ~80 lines, streamline formatting

**IMPORTANT:** Keep ALL tool capability descriptions. Only reduce:
- Excessive BAD/GOOD styling examples
- Verbose explanations of anti-patterns
- Redundant formatting examples

### 1.1 ACTION_SYNTAX: Keep complete tool list, improve organization

**Current structure:**
```python
ACTION_SYNTAX = """
[693 lines of tool documentation with all capabilities]
"""
```

**New structure (KEEP ALL TOOLS):**
```python
ACTION_SYNTAX = """
## Core Actions (Organized by Category)

### File Operations
<enhanced_read>path:show_line_numbers:max_lines</enhanced_read>
<enhanced_write>path:content:backup</enhanced_write>
<apply_diff>path:diff:backup</apply_diff>
<multiedit>content</multiedit>  # Multi-file atomic edits

### Code Execution
<execute>python_code</execute>

### Search & Memory
<search>pattern</search>
<memory_search>query</memory_search>
<perplexity_search>query:max_results</perplexity_search>

### Project Management
<update_plan>json_state</update_plan>  # NEW - Codex pattern
<task_create>, <task_update>, <task_complete>
<project_create>, <project_update>

### Browser Automation
<pydoll_browser_navigate>url</pydoll_browser_navigate>
<pydoll_browser_interact>action:selector:type:text</pydoll_browser_interact>
<pydoll_browser_screenshot></pydoll_browser_screenshot>

### Git & GitHub
[Complete GitHub operations documentation]

### Sub-Agent Tools
<spawn_sub_agent>, <delegate>, <send_message>

## Safety Rules
1. Check file.exists() before writing
2. Use apply_diff (automatic backups)
3. Never blind overwrite/delete

[Full documentation for each tool - keep ALL 693 lines of capability info]
[Only remove redundant examples, NOT tool descriptions]
"""
```

**Changes:**
- Add category headers for better organization
- Keep ALL tool capability descriptions (693 lines of actual info)
- Only remove: Redundant examples, excessive styling
- Add `update_plan` tool (new from Phase 2)

### 1.2 OUTPUT_STYLE: 226 → ~80 lines

**Current breakdown:**
- Lines 1-47: General structure (KEEP)
- Lines 48-127: Code formatting with BAD/GOOD examples (REDUCE to 1-2 examples)
- Lines 128-197: Tool acknowledgment anti-pattern (REDUCE to essential rule only)
- Lines 198-226: Reasoning blocks (KEEP)

**New streamlined version:**
```markdown
## Output Format

### Code Blocks
- Fenced blocks with language: ```python\n
- Blank line after imports (Python PEP 8)
- Proper indentation (4 spaces Python, 2 spaces YAML)

### Tool Results (CRITICAL)
ALWAYS acknowledge results before proceeding:
- "Got it: [result]" then continue
- NEVER re-execute without acknowledging

### File References
Use file.py:42 or file.py:42-51 format

### Markdown Preference
Use markdown lists for summaries (not YAML/JSON in terminals)

### Reasoning (Optional)
Use brief [dim]🧠[/dim] prefix for CLI, <details> for TUI
```

**Detailed formatting guide moves to separate file:**
```python
# New file: penguin/prompt/formatting_guide_detailed.md
# Contains all BAD/GOOD examples, edge cases, etc.
```

### 1.3 Extract Strategic Advisor Persona

**Current BASE_PROMPT:**
```python
BASE_PROMPT = """
You are Penguin...

[24 lines of IQ 180, Elon/Linus, strategic advisor]

[Rest of prompt]
"""
```

**New structure:**
```python
# Minimal base (Codex-style)
BASE_PROMPT = """
You are Penguin, a software engineering agent specializing in code analysis,
implementation, and debugging.

**Approach:**
- Fact-based: Verify assumptions before acting
- Helpful: Go the extra mile, prioritize safety
- Clear: Explain reasoning concisely
- Personal: Use brief italicized thoughts for planning

[Rest of capabilities and operational environment]
"""

# Strategic advisor as opt-in mode
# In prompt/profiles.py
MENTOR_MODE_DELTA = """
## Strategic Advisor Persona (Mentor Mode)
Think and work as top engineers do (Carmack, Torvalds, etc.):
- Brutally honest and direct
- Systems thinking and root causes
- Focus on leverage points
- Push beyond comfort zones
- High standards, no excuses
"""
```

**Usage:**
```bash
penguin run          # Uses minimal base prompt
penguin run --mode mentor  # Adds strategic advisor persona
```

### 1.4 Elevate File Reference Format

**Current:** Buried in line 5 of ACTION_SYNTAX

**New:** Top-level communication standard
```markdown
## Communication Standards (MANDATORY)
- **File references:** [file.py:42] or [file.py:42-51] for line numbers
- **Commands:** `monospace` for shell commands
- **Changes:** Show before/after diffs when explaining
- **Rationale:** Explain "why" for non-obvious decisions
```

Place this BEFORE action syntax section (higher visibility).

### Deliverables
- [ ] ACTION_SYNTAX reorganized with category headers (keep all 693 lines of tool info)
- [ ] OUTPUT_STYLE streamlined to ~80 lines (remove redundant examples)
- [ ] MENTOR_MODE_DELTA in profiles.py
- [ ] Communication standards elevated
- [ ] Add `update_plan` tool to ACTION_SYNTAX

**Time estimate:** 3-5 hours

---

## Phase 2: Context Management (2-3 hours)

### 2.1 Context File Consolidation

**Current:**
```
context/
  TASK_CHARTER.md    # Requirements
  TASK_SCRATCHPAD.md # Working notes
  TRACK.md           # Progress log
  DOMAIN_MODEL.md    # Domain modeling
```

**Selected: Option A - 3 files** ✅
```
context/
  PLAN.md       # CHARTER + SCRATCHPAD (requirements + notes)
  PROGRESS.md   # TRACK (what's done, blockers)
  DOMAIN.md     # Domain modeling (for complex projects)
```

**Benefits:**
- Clear separation of concerns
- Easy to navigate
- `update_plan` tool can manage PLAN.md atomically

### 2.2 Add `update_plan` Tool (Codex Pattern)

**Implementation:**
```python
# penguin/tools/planning.py
from pathlib import Path
from typing import List, Optional
import json

@tool
def update_plan(
    current_step: str,
    completed: List[str],
    next_steps: List[str],
    blockers: Optional[List[str]] = None
) -> str:
    """
    Update the current plan state atomically.

    Updates context/PLAN.md with:
    - Current step in progress
    - Completed steps (with checkmarks)
    - Next steps queued
    - Any blockers encountered

    This replaces manual editing of TASK_CHARTER, SCRATCHPAD, and TRACK.

    Example:
    <update_plan>{
      "current_step": "Implementing auth middleware",
      "completed": ["Read requirements", "Designed schema"],
      "next_steps": ["Write tests", "Deploy to staging"],
      "blockers": ["Need AWS credentials for S3 upload"]
    }</update_plan>
    """
    plan_path = Path("context/PLAN.md")

    # Generate markdown
    content = f"""# Current Plan

## 🔄 In Progress
- {current_step}

## ✅ Completed
{chr(10).join(f"- [x] {item}" for item in completed)}

## 📋 Next Steps
{chr(10).join(f"- [ ] {item}" for item in next_steps)}
"""

    if blockers:
        content += f"""
## 🚧 Blockers
{chr(10).join(f"- ⚠️ {item}" for item in blockers)}
"""

    plan_path.write_text(content)
    return f"Updated plan: {len(completed)} done, {len(next_steps)} remaining"
```

**Prompt integration:**
```markdown
## Planning Tool (Use This Instead of Manual Context File Edits)
Update plan state atomically with <update_plan>:

<update_plan>{
  "current_step": "Implementing feature X",
  "completed": ["Step 1", "Step 2"],
  "next_steps": ["Step 3", "Step 4"],
  "blockers": []
}</update_plan>
```

### 2.3 Wire Project Instructions Auto-Loading

**Current status:** Function exists but not wired into pipeline

**Implementation:**
```python
# In penguin/system/context_assembler.py
def assemble_context(self, messages, ...):
    # After system prompt, before dialog
    project_docs = self.loader.load_project_instructions(max_tokens=600)
    if project_docs:
        self.add_to_context(
            content=project_docs,
            category=MessageCategory.CONTEXT,
            priority="high"
        )

    # ... rest of assembly
```

**Logic:**
1. Check for `PENGUIN.md` in repo root
2. Fallback to `README.md` if not found
3. Take first 300-600 tokens
4. Insert after system prompt but before dialog

### Deliverables
- [ ] Implement `update_plan` tool (~60 lines)
- [ ] Wire `load_project_instructions()` into assembler (~20 lines)
- [ ] Update prompts to prefer `update_plan` over manual edits
- [ ] Consolidate context files: PLAN.md + PROGRESS.md + DOMAIN.md
- [ ] Tests for planning tool

**Time estimate:** 2-3 hours

---

## Phase 3: Mode System (3-4 hours)

**Priority:** Implement `review` mode first (P0-P3 rubric), then `mentor` mode

### 3.1 CLI Integration

**Files to modify:**
- `penguin/cli/cli_new.py`
- `penguin/cli/tui.py`
- `penguin/config.py`

**Implementation:**
```python
# cli_new.py
@click.option('--mode',
              type=click.Choice(['direct', 'mentor', 'review', 'terse']),
              default='direct',
              help='Agent interaction mode')
def run(mode: str, ...):
    system_prompt = get_system_prompt(mode=mode)
    # ... rest
```

```python
# tui.py - add command
def handle_command(self, command: str):
    if command.startswith("/mode "):
        mode = command.split()[1]
        if mode in ["direct", "mentor", "review", "terse"]:
            self.set_mode(mode)
            self.display_message(f"Switched to {mode} mode")
```

### 3.2 Add Code Review Mode (PRIORITY 1)

**Implementation:**
```python
# In prompt/profiles.py
REVIEW_MODE_DELTA = """
## Code Review Mode

### Priority Levels
- **[P0] Critical**: Blocks release (security, data loss, crashes)
- **[P1] Urgent**: Fix next cycle (correctness, major bugs)
- **[P2] Normal**: Fix eventually (maintainability, tech debt)
- **[P3] Nice-to-have**: Style, minor improvements

### Review Focus
- Flag only issues author would want to fix
- Focus on changes in current commit/PR (not pre-existing issues)
- Be matter-of-fact, not accusatory
- Keep comments brief (1 paragraph max)
- Avoid excessive flattery

### Output Format
```json
{
  "findings": [
    {
      "priority": "P1",
      "title": "Potential null pointer in getUserData",
      "location": "src/auth.py:42-45",
      "description": "getUserData returns None when user not found, caller doesn't check",
      "confidence": 0.9
    }
  ],
  "verdict": "NEEDS_CHANGES",
  "summary": "1 critical bug, 2 minor style issues"
}
```

### Review Workflow
1. Read files changed in PR/commit
2. Identify issues by priority (P0-P3)
3. Output structured JSON
4. Provide actionable feedback
"""
```

### Deliverables
- [ ] Add `--mode` flag to CLI (~10 lines)
- [ ] Add `/mode` command to TUI (~20 lines)
- [ ] Implement REVIEW_MODE_DELTA with P0-P3 rubric (~80 lines) **[PRIORITY 1]**
- [ ] Implement MENTOR_MODE_DELTA (~30 lines) [Priority 2]
- [ ] Add mode indicator to TUI status bar (~15 lines)
- [ ] Tests for mode switching

**Time estimate:** 3-4 hours

---

## Summary: Total Implementation Time

### Phase 0: Permission Engine (4-6 hours)
Build the foundation that prompts reference but doesn't exist yet

### Phase 1: Prompt Streamlining (3-5 hours)
Reduce OUTPUT_STYLE verbosity, reorganize ACTION_SYNTAX, extract persona

### Phase 2: Context & Planning (2-3 hours)
Consolidate context files, add `update_plan` tool, wire auto-loading

### Phase 3: Mode System (3-4 hours)
Add review mode (P0-P3 rubric) + mentor mode, CLI/TUI integration

**Total time:** ~12-18 hours of focused work

**Expected outcome:**
- OUTPUT_STYLE streamlined (226 → ~80 lines, 65% reduction)
- ACTION_SYNTAX better organized (keep all 693 lines of tool info, improve structure)
- Codex-style directness by default
- Review mode with P0-P3 rubric (priority 1)
- Strategic advisor available via `--mode mentor` (priority 2)
- Clear, implemented safety model with workspace/project distinction
- Cleaner context management with `update_plan` tool
- 3-file context structure (PLAN + PROGRESS + DOMAIN)

---

## Decisions Finalized ✅

1. ✅ **Context file structure:** 3 files (PLAN.md + PROGRESS.md + DOMAIN.md)
2. ✅ **Permission modes:**
   - Workspace mode: Full permissions (especially in containers)
   - Project mode: Only what User grants in project root
3. ✅ **Mode rollout order:** Review mode first (P0-P3), then mentor mode
4. ✅ **Tool documentation:** Keep ALL capability descriptions, only reduce styling/examples
5. ✅ **Time estimates:** Hours/minutes instead of weeks
