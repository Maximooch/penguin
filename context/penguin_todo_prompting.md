# Penguin Prompting System Overhaul TODO

Based on analysis of OpenAI Terminal Bench prompting vs Penguin's current approach, this document outlines the roadmap for achieving Claude Code-style directness and persistence while maintaining Penguin's architectural strengths.

## Core Philosophy Shift

**From:** Safety-first verification loops with extensive pre-checks
**To:** Persistence-first execution with guardrails, smart recovery, and minimal friction

### Key Principles
1. **Persistence over perfection** - Keep going until task completion; avoid analysis loops.
2. **Guardrailed confidence** - Reduce verification overhead but preserve essential safety invariants.
3. **Recover gracefully** - On errors, fix and continue; pause only on critical failures.
4. **Minimize cognitive load** - Streamline prompts to focus on essential behaviors.
5. **Respect permissions** - Adhere to allow/ask/deny policy and dry‑run defaults for edits.

---

## Phase 1: Core Prompt Streamlining (P0 - Week 1-2)

### 1.1 Slim Verification To Essential Invariants
- **Problem**: Excessive "verify before act" creates analysis paralysis.
- **Action**: Keep only non-negotiable checks and make them concise.
- **Essential invariants (retain):**
  1) Pre-write existence check (path exists?).
  2) Edits produce diffs and create backups automatically.
  3) Respect permission engine (allow/ask/deny) and path allow/deny lists.
  4) Post-write verification for touched files only (existence + expected snippet), not global.
  5) Avoid destructive ops unless explicitly allowed.
- **Files to modify**:
  - `penguin/prompt_workflow.py` – Streamline `MULTI_STEP_SECTION`/verification prose to these 4–5 rules.
  - `penguin/system_prompt.py` – Replace verbose `CORE_MANDATES` with crisp invariants.

### 1.2 Add Persistence Directive (with Guardrails)
- **Inspiration**: OpenAI's "keep going until resolved" approach.
- **Implementation**:
  ```python
  PERSISTENCE_PROMPT = """
  ## Execution Persistence (Guarded)
  - Continue working until the user's task is fully complete.
  - On recoverable errors, fix and keep going; summarize the fix.
  - Respect the permission engine (allow/ask/deny) at all times.
  - Treat edits as dry-run by default; auto-apply only if approved or mode/flag allows.
  - Pause on permission-denied, managed-policy conflicts, or critical failures.
  """
  ```
- **Integration**: Append to builder/base prompt (or `BASE_PROMPT`) in `system_prompt.py`.

### 1.3 Streamline Action Syntax
- **Problem**: Verbose action docs create cognitive overhead.
- **Action**: Consolidate `ACTION_SYNTAX` to essential patterns only.
- **Keep visible**: `execute`, `apply_diff` (and/or `multiedit.apply`), minimal TUI formatting tips.
- **Hide complexity**: Keep enhanced ops as low-noise backends that ensure backups/diffs.
- **File**: `penguin/prompt_actions.py`.

---

## Phase 2: Context Window Management Overhaul (P0 - Week 3-4)

### 2.1 Implement Smart Context Assembly (Minimal Approach)
**Keep existing categories, improve allocation within them:**

#### 2.1.1 Context Contributors Within CONTEXT Category
- **Approach**: Use existing `CONTEXT` category, add contributor ranking within it
- **Contributors within CONTEXT**:
  - Working files (touched/active files) - weight 0.4
  - Project docs (PENGUIN.md, README) - weight 0.15  
  - Retrieval results (search hits) - weight 0.25
  - Codebase map (file tree summary) - weight 0.2
- **No new MessageCategory values** - partition internally

#### 2.1.2 Dynamic Reallocation Within Existing Categories  
- **Implementation**: Extend existing `ContextWindowManager` borrowing logic
- **Borrowing rules**: Working files can borrow from DIALOG when needed
- **Files**:
  - Extend `penguin/system/context_window.py` (add borrowing to existing TokenBudget)
  - Add contributor ranking logic to existing allocation methods

#### 2.1.3 Heuristic Summarization (No LLM Initially)
- **Problem**: Long files/conversations blow out context
- **Solution**: Simple heuristic compaction, not LLM-based
- **Features**:
  - Files: headers + signatures + recent hunks + N lines context; collapse long middles
  - Conversations: keep last K exchanges; strip verbose tool noise
  - Retrieval: quote "evidence bundles" (path + short quoted lines) vs full chunks
  - Add tiny utilities, avoid subagent complexity initially

### 2.2 Project Instructions Auto-loading
- **Feature**: Auto-load `PENGUIN.md` from repo root; fallback to README.md
- **Implementation**: Small guaranteed min within CONTEXT category contributor system
- **Scope**: First 300-600 tokens of project docs
- **File**: Extend `penguin/system/context_loader.py`

---

## Phase 3: Atomic Multi-File Operations (P1 - Week 5-6)

### 3.1 Enhanced Patch System
Inspired by OpenAI's `apply_patch`, adding Penguin’s safety and UX:

#### 3.1.1 New Tool: `multiedit.apply()`
```python
# Example usage in prompt
<multiedit>
file1.py:
--- a/file1.py
+++ b/file1.py
@@ -10,2 +10,3 @@
 def hello():
 +    """Say hello"""
      print("hello")

file2.py:
--- a/file2.py
+++ b/file2.py
@@ -5,1 +5,2 @@
 import sys
 +from file1 import hello
</multiedit>
```

#### 3.1.2 Semantics & Safety
- **Transactional**: All changes apply or none do (atomic).
- **Backups**: Create automatic backups for every touched file.
- **Rollback**: Auto-rollback on any per-file failure.
- **Dry-run**: Dry-run preview by default with summarized per-file hunks; require approval/mode for apply.
- **Per-file reporting**: Clear success/failure per file with reasons.
- **Format**: Unified diff; restrict file path resolution to workspace + allowlist.
- **Implementation**: New file `penguin/tools/multiedit.py` with tests for rollback and error cases.

### 3.2 Simplify Enhanced Operations Surface
- **Goal**: Reduce verbosity without losing safety and precision.
- **Approach**: Keep enhanced ops as backends (backups, diffs, precise edits) but surface fewer, simpler entry points.
- **Expose**: `apply_diff` and `multiedit.apply` for edits; keep `execute` for checks and simple ops.

### 3.3 Robust Patching Backend (Optional, Low Debt)
- **Problem**: Unified diff application is brittle on context drift; error reporting can be noisy.
- **Solution**: Add optional robust backends behind the same `multiedit.apply` surface.
- **Backends**:
  - `git apply --check` preflight validation (+ optional `--3way` fallback on drift)
  - `unidiff` for structure parsing/validation and better dry‑run previews (files, hunks, adds/dels)
  - Fallback to existing `support.py` apply engine when git is unavailable
- **Safety**: Always enforce `enforce_allowed_path` and `PENGUIN_WRITE_ROOT` before invoking any backend.
- **New‑file semantics**: Treat `/dev/null -> b/<path>` as creation. On rollback, delete any created files.
- **Current behavior (pre‑worktree)**: Robust backend applies changes to the working tree only — it does NOT commit or push. Commits/PRs are opt‑in and will be introduced via the shadow worktree/Checkpoint integration below.

### 3.4 Checkpoint & Worktree Integration
- **Goal**: Make multi‑file edits first‑class, auditable steps.
- **Approach**: Integrate with the existing Checkpoint system using a shadow git worktree (code plane).
- **Flow**:
  1) Normalize patch → `git apply --check` in worktree
  2) Apply (optionally with `--3way`) → commit a "multiedit" checkpoint with file list + summary metadata
  3) Propagate changes to active workspace (copy back with backups) or keep worktree as canonical per session
  4) Rollback via checkpoint commit (and delete any newly created files)
- **Config toggles**: `robust_apply`, `three_way_fallback`, `commit_on_success`, `copy_back` (defaults conservative)
- **User repo safety**: Penguin will never commit/push to the user’s repo by default. All commits occur in the shadow worktree/branch that Penguin manages. Merges/PRs happen only when explicitly requested by the user.

### 3.5 Tooling & UX Improvements
- **Dry‑run default**: `multiedit.apply` previews by default; `apply=true` to execute
- **Structured results**: Per‑file success/failure, backups, created files, rollback flag; JSON shape stable for UI/TUI
- **Logging**: On failure, log patch + original to `errors_log/diffs/**` and reference path in error message
- **Input formats**: Accept both standard multi‑file unified patches and LLM‑friendly per‑file blocks; normalize internally

---

## Phase 4: Mode System Implementation (P1 - Week 7-8)

### 4.1 Prompt Builder Architecture
Based on `prompting_overhaul.md`:

#### 4.1.1 Core Builder
- **New file**: `penguin/prompt/builder.py`
- **Purpose**: Compose prompts from modular components
- **Components**:
  - Base rules (minimal, non-negotiable)
  - Mode deltas (personality, verbosity, structure)
  - Tool usage patterns
  - Context policies

#### 4.1.2 Mode Profiles
- **New file**: `penguin/prompt/profiles.py`
- **Modes to implement**:
  - `direct` – Minimal explanations, maximum persistence, with invariants (default).
  - `bench_minimal` – Harness-compatible, no persona, minimal protocol.
  - `explain` – Educational mode with reasoning.
  - `terse` – Ultra-minimal responses.
  - `review` – Code review focus with checklists.
  - `research` – Information gathering with citations.

#### 4.1.3 CLI Integration
- **Command**: `/mode <name>` in TUI
- **Flag**: `--mode <name>` in CLI
- **Config**: `default_mode` in settings

### 4.2 Personality Modularization
- **Current**: Heavy advisor persona in base prompt
- **Future**: Light "Penguin DNA" by default, persona as opt-in mode
- **Implementation**: Move personality to separate profile that can be toggled

### 4.3 Completion Phrases Per Mode (Optional)
- Make completion phrases (e.g., `TASK_COMPLETED`) opt-in via mode; keep core invariants constant.

---

## Phase 5: Performance and Polish (P2 - Week 9-10)

### 5.1 Reasoning Budget Controls
- **Feature**: `/reflect` command for deeper analysis when needed
- **Implementation**: Toggle reasoning depth via mode
- **Default**: Fast, direct responses unless explicitly requested

### 5.2 Context Caching
- **Problem**: Rebuilding context every turn is expensive
- **Solution**: Cache stable context slots (project info, tool docs)
- **Implementation**: Extend `ContextWindowManager` with caching layer

### 5.3 Performance Metrics
- **Add telemetry (local-only)**: Response time, token usage, context efficiency; no exfiltration by default.
- **Dashboard**: Show context slot utilization in TUI status
- **Optimization**: Identify and fix context bloat

---

## Implementation Strategy

### Week-by-Week Breakdown

**Weeks 1-2: Foundation**
- Streamline existing prompts
- Add guarded persistence directive
- Replace verbose verify-before-act text with crisp invariants

**Weeks 3-4: Context Revolution**
- Build slot-based context system
- Implement token budgeting
- Add auto-summarization
 - Add TUI debug view of slot allocations

**Weeks 5-6: Power Tools**
- Create atomic multi-file editing
- Simplify file operations
- Add rollback capabilities
 - Ship dry-run preview + per-file reporting
 - Add optional robust backend: `git apply --check` + `--3way` fallback; validate with `unidiff`
 - Integrate with CheckpointManager using a shadow worktree (commit on success, rollback friendly)

**Weeks 7-8: Modes & Flexibility**
- Build prompt composer
- Implement mode system
- Add CLI integration
 - Ship `bench_minimal` profile; default to `direct` (with invariants)

**Weeks 9-10: Polish & Performance**
- Add reasoning controls
- Implement context caching
- Performance optimization
 - Add patch stress tests and limits reporting (max files per op, patch size, typical failure modes)

---

## Phase 6: Structural Editing (Future)

### 6.1 Language‑Aware Refactors
- **Python (near‑term)**: LibCST/Bowler for safe refactors (rename, import insert, API shifts)
- **General (future)**: ast‑grep (`sg`) wrapper for multi‑language tree queries/rewrites
- **Integration**: AST tools produce unified diffs → hand off to `multiedit.apply` → reuse the same safety/rollback path

### 6.2 Policy & Safety
- Maintain the same invariants (path allowlists, backups, dry‑run by default)
- Prefer AST tools only when patterns are structural; otherwise use diff‑first editing

---

## Supporting Libraries (Low Tech Debt, Optional)

- `unidiff`: Parse/validate unified patches; generate high‑quality previews
- `charset-normalizer`: Robust encoding detection for read/apply while preserving newline style
- `pathspec`: Git‑ignore compatible filtering in enhanced list/find tools
- `git` CLI: Optional robust patch engine via `git apply`; fallback to internal engine when missing

---

## Status & Checklist

### Phase 1: Core Prompt Streamlining
- [x] Slim verification to essential invariants (pre‑write check, backups/diffs, permission policy, scoped post‑verify)
- [x] Add guarded persistence directive
- [x] Streamline action syntax (kept execute/apply_diff; documented multiedit)

### Phase 2: Context Window Management
- [x] Dynamic reallocation/borrowing (CONTEXT borrows from DIALOG)
- [~] Project instructions auto‑loading (function implemented; not yet wired into default pipeline)
- [ ] Heuristic summarization (headers/signatures/last‑K; retrieval “evidence bundles”) 
<!-- TODO: (this really should be using sub-agents for LLM-based summarization) -->
- [~] Smart contributor system (scaffold exists; currently disabled behind feature flag)

### Phase 3: Atomic Multi‑File Operations
- [x] `multiedit.apply` facade (dry‑run default; structured results)
- [x] New‑file semantics in unified patch (`/dev/null` → create; delete on rollback)
- [x] Transactional apply/rollback in Python fallback path
- [ ] Robust backend: `git apply --check` (+ optional `--3way`), `unidiff` validation
- [ ] Checkpoint/worktree integration (commit multiedit checkpoints; rollback via commit)
- [ ] Test suite (atomic rollback, path policy, new‑file create/delete, failure logging)

### Phase 4: Mode System
- [x] Prompt builder and multiple modes available (direct, bench_minimal, terse, explain, review)
- [ ] CLI/TUI mode control (`/mode <name>`, `--mode` flag end‑to‑end)
- [~] Personality modularization (base trimmed; fuller modular persona TBD)
- [ ] Completion phrases per mode (optional)

### Phase 5: Performance & Polish
- [~] Performance metrics (CWM stress harness with JSON/CSV reports)
- [ ] Reasoning budget controls (`/reflect` or depth toggle)
- [ ] Context caching (stable slots)
- [ ] End‑to‑end patch stress tests and limits reporting

### Phase 6: Structural Editing (Future)
- [ ] Python codemods via LibCST/Bowler → unified diffs → multiedit
- [ ] Multi‑language structural queries/rewrites via ast‑grep wrapper → diffs → multiedit
- [ ] Keep invariants (path policy, backups, dry‑run) in AST tools

### Supporting Libraries
- [ ] `unidiff` for patch parsing/preview
- [ ] `charset-normalizer` for encodings/newlines
- [ ] `pathspec` for ignore patterns in list/find tools
- [ ] Optional git backend (`git apply`) with graceful fallback

Legend: [x] done · [~] partial/in progress · [ ] pending

### Success Criteria

1. **Persistence**: Penguin continues working through errors without stopping
2. **Directness**: Responses are concise and action-oriented by default
3. **Context Efficiency**: Better information density in context window
4. **Mode Flexibility**: Easy switching between interaction styles
5. **Performance**: Faster responses with better context management
6. **Safety**: Essential invariants enforced (pre-check, backup+diff, permission policy, scoped post-verify)
7. **Determinism**: Context assembler shows stable slot budgets and logs allocations

### Risk Mitigation

1. **Over-reduction of safety**: Keep essential invariants always; dry-run edits by default; enforce permission engine.
2. **Context slot conflicts**: Implement clear precedence rules and fallbacks
3. **Mode confusion**: Start with minimal set, expand based on usage
4. **Performance regression**: Benchmark before/after, optimize hot paths

### Immediate Next PRs (Quick Wins)
1. Slim `system_prompt.py`/`prompt_workflow.py`: add guarded `PERSISTENCE_PROMPT`, replace verification prose with 4–5 invariants, trim `ACTION_SYNTAX`.
2. Builder/profiles skeleton: `penguin/prompt/builder.py`, `penguin/prompt/profiles.py`; implement `direct` and `bench_minimal`; wire `SYSTEM_PROMPT` to builder.
3. Context assembler skeleton: `system/context_assembler.py` with fixed slots/budgets + debug logging; integrate with `context_window.py`.
4. `multiedit.apply` MVP: dry-run preview, atomic apply with backups/rollback, per-file reporting; tests for failure paths.

---

## Files to Create/Modify

### New Files
- `penguin/prompt/builder.py`
- `penguin/prompt/profiles.py`
- `penguin/tools/multiedit.py`

### Modified Files
- `penguin/system_prompt.py` - Core prompt streamlining
- `penguin/prompt_workflow.py` - Reduce verification overhead
- `penguin/prompt_actions.py` - Simplify action syntax
- `penguin/system/context_window.py` - Add slot budgeting
- `penguin/system/context_loader.py` - Auto-load project instructions
- `penguin/cli/cli_new.py` - Add mode flags
- `penguin/cli/tui.py` - Add mode switching

### Configuration Changes
- Add `prompt.mode` and `prompt.persistence_level` to config schema
- Add context slot budget configuration
- Add mode-specific overrides

---

## Testing Strategy

1. **Prompt Regression Tests**: Ensure core behaviors don't break
2. **Context Efficiency Tests**: Measure token usage before/after
3. **Mode Switching Tests**: Verify mode deltas apply correctly
4. **Multi-file Edit Tests**: Test atomic operations and rollbacks
5. **Persistence Tests**: Verify continued execution through common error scenarios

This overhaul will transform Penguin from a safety-focused, verbose assistant into a persistent, direct, and efficient coding partner while maintaining its architectural advantages and extensibility.
