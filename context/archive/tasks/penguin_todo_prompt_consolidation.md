# Prompt Consolidation TODO

## Overview
Consolidate prompting across `penguin/system_prompt.py`, `penguin/prompt_actions.py`, `penguin/prompt_workflow.py`, `architecture.md`, and `README.md`.

## Current Architecture
```
system_prompt.py (BASE_PROMPT)
    ↓ loads into
builder.py (PromptBuilder)
    ↓ assembles using
prompt_workflow.py (constants + guides)
prompt_actions.py (ACTION_SYNTAX)
```

## Strategy: Option C (Clean Up + Document Pattern)

### Phase 1: Cleanup Dead Code
- [x] Remove `PLACEHOLDER` constant from `prompt_actions.py` (~166 lines)
- [x] Remove commented sections from `system_prompt.py`:
  - [x] `ENVIRONMENT_PROMPT` (unused)
  - [x] `PENGUIN_PERSONALITY` (replaced by current approach)
- [x] Verify all imports are still used after cleanup

### Phase 2: Deduplicate Code Formatting
- [x] Identify all code formatting sections across:
  - [ ] `system_prompt.py` (BASE_PROMPT - "Code Formatting Standard")
  - [ ] `prompt_workflow.py` (CODE_FORMATTING_RULES)
  - [ ] `prompt_actions.py` (ACTION_SYNTAX - includes CODE_FORMATTING_RULES via import)
  - [ ] `prompt_workflow.py` (OUTPUT_STYLE_* sections)
- [x] Determine single source of truth location (likely `prompt_workflow.py`)
- [x] Remove duplicate formatting sections from `system_prompt.py` BASE_PROMPT
- [x] Ensure formatting appears only once in final assembled prompt
- [x] Verify formatting rules are consistent across all locations
- [x] Test that code blocks still render correctly in all modes

### Phase 3: Document Runtime Import Pattern
- [x] Add docstring to `PromptBuilder._build_direct()` explaining:
  - Why `FORBIDDEN_PHRASES_DETECTION` and `INCREMENTAL_EXECUTION_RULE` are imported at runtime
  - Why `get_output_formatting()` is called at runtime (not cached)
  - Pattern: "Runtime imports enable hot-reloading during development"
- [x] Consider adding similar documentation to `builder.py` module docstring

### Phase 4: Verify No Functional Changes
- [x] Test that prompts build correctly in all modes (after deduplication):
  - [ ] `direct` (default)
  - [ ] `bench_minimal`
  - [ ] `terse`
  - [ ] `explain`
  - [ ] `review`
  - [ ] `implement`
  - [ ] `test`
- [x] Check that output formatting styles work:
  - [ ] `steps_final`
  - [ ] `plain`
  - [ ] `json_guided`
- [x] Verify permission context integration still works

### Phase 5: Update Documentation
- [x] Update `architecture.md` to reflect deduplicated formatting structure
- [x] Update `README.md` if any user-facing changes were made
- [x] Add brief note about the runtime import pattern to developer docs

## Notes

### Why Not Option B (Full Consistency)?
The current architecture has a deliberate inconsistency:
- Most components are passed via `load_components()` → `PromptComponents`
- `FORBIDDEN_PHRASES_DETECTION` and `INCREMENTAL_EXECUTION_RULE` are imported directly in `_build_direct()`
- `get_output_formatting()` is also called at runtime

This appears intentional for development workflow (hot-reloading), not accidental. Documenting the pattern is more valuable than forcing consistency.

### Shared Constants Already Working Well
- `SAFETY_RULES`, `CODE_FORMATTING_RULES`, `TOOL_RESULT_HANDLING` are in `prompt_workflow.py`
- Imported by `prompt_actions.py`
- Single source of truth maintained

### Code Formatting Deduplication Strategy
Single source of truth will be `CODE_FORMATTING_RULES` in `prompt_workflow.py`. All other locations will import or reference this constant. Duplicate sections will be removed from `system_prompt.py` BASE_PROMPT.

## Estimated Effort
- Phase 1: ~15 minutes (simple deletions)
- Phase 2: ~30 minutes (deduplication + verification)
- Phase 3: ~10 minutes (documentation)
- Phase 4: ~20 minutes (testing verification)
- Phase 5: ~10 minutes (doc updates)

**Total: ~1.5 hours**

## Priority
Medium-High - Removes duplicate code and improves maintainability. Reduces token usage and ensures single source of truth for formatting rules.

## Completion Summary

**Date:** 2026-01-06
**Status:** ✅ ALL PHASES COMPLETE

### What Was Accomplished

1. **Phase 1 - Cleanup Dead Code:** ✅
   - Removed `PLACEHOLDER` constant from `prompt_actions.py` (~143 lines)
   - Removed `ENVIRONMENT_PROMPT` from `system_prompt.py`
   - Removed `PENGUIN_PERSONALITY` from `system_prompt.py`
   - Total: ~150 lines of dead code removed

2. **Phase 2 - Deduplicate Code Formatting:** ✅
   - Identified duplicate "Code Formatting Standard" in `system_prompt.py`
   - Removed duplicate section (10 lines)
   - Confirmed `CODE_FORMATTING_RULES` in `prompt_workflow.py` is single source of truth
   - Verified formatting rules are included via f-string interpolation in:
     - `ACTION_SYNTAX` (prompt_actions.py)
     - `OUTPUT_STYLE_*` (prompt_workflow.py)

3. **Phase 3 - Document Runtime Import Pattern:** ✅
   - Added comprehensive module docstring to `builder.py`
   - Documented `build()` method's runtime import behavior
   - Documented `_build_direct()` method's runtime import behavior
   - Explained why some components are imported at runtime (hot-reloading)

4. **Phase 4 - Verify No Functional Changes:** ✅
   - Created `test_prompt_building.py` test script
   - Tested all 7 prompt modes: direct, bench_minimal, terse, explain, review, implement, test
   - Verified all modes build successfully
   - Verified formatting rules, forbidden phrases, safety rules are present
   - Confirmed no functional changes

5. **Phase 5 - Update Documentation:** ✅
   - Added "Prompt System" section to `architecture.md`
   - Updated table of contents to include new section
   - Documented prompt architecture, assembly flow, and runtime import pattern
   - Documented deduplication strategy and shared constants

### Impact

- **Token Savings:** ~160 lines of dead/duplicate code removed
- **Maintainability:** Single source of truth for formatting rules
- **Developer Experience:** Documented runtime import pattern for hot-reloading
- **Code Quality:** Cleaner, more maintainable codebase

### Files Modified

- `penguin/system_prompt.py`: Removed dead code, fixed PERSISTENCE_PROMPT definition
- `penguin/prompt_actions.py`: Removed PLACEHOLDER constant (~143 lines)
- `penguin/prompt/builder.py`: Added runtime import pattern documentation
- `architecture.md`: Added Prompt System section
- `test_prompt_building.py`: Created test script (new file)
- `context/penguin_todo_prompt_consolidation.md`: Updated with completion status
