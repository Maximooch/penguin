# CLI Refactoring Plan - Controlled Demolition

## Executive Summary

**Goal:** Reduce `penguin/cli/cli.py` from 5,747 lines to ~1,200 lines (79% reduction) while maintaining full functionality.

**Timeline:** 3-5 days with daily availability
**Approach:** Controlled demolition with test safety net
**Risk Tolerance:** High (break temporarily acceptable if reasonable)

## Current State Analysis

### File: `penguin/cli/cli.py` (5,747 lines)

**Key Issues (from `rich_cli_analysis.md`):**

1. **Code Duplication (3+ times)**
   - `CODE_BLOCK_PATTERNS` duplicated in `cli.py`, `ui.py`, `renderer.py`
   - Language detection duplicated across files
   - Diff rendering logic duplicated

2. **Monolithic Class (PenguinCLI: 2,515 lines)**
   - 47 methods handling display, streaming, events, input, session management
   - Should be 5 focused classes

3. **Ignored Infrastructure**
   - `events.py` has EventBus but not used (331-line `handle_event()` instead)
   - `renderer.py` has UnifiedRenderer but display logic duplicated in CLI
   - `streaming_display.py` has StreamingDisplay but 590-line `_ensure_progress_cleared()` used instead

4. **Massive Coupling**
   - 114 imports (slow startup)
   - Direct dependencies on too many modules

### Test Safety Net: ✅ COMPLETE

**File:** `tests/test_cli_integration.py` (34 tests, all passing)

Coverage:
- ✅ CLI module structure and imports
- ✅ Rendering behavior (code blocks, language detection)
- ✅ Display methods existence
- ✅ Streaming behavior (progress, callbacks)
- ✅ Event system integration
- ✅ Command structure (project, config, agent, etc.)
- ✅ Checkpoint functionality
- ✅ Context window management
- ✅ Duplication detection (documents current issues)
- ✅ Architecture assumptions (renderer, event_bus, streaming_display)

## Refactoring Phases

### Phase 0: Quick Wins (Day 0.5 - COMPLETED ✅)
**Status:** Test safety net created and passing

**What was done:**
- Created `tests/test_cli_integration.py` with 34 tests
- All tests passing
- Baseline established for current behavior

**Impact:** Zero code changes, just documentation and testing

---

### Phase 1: Extract Display Logic (Days 1-2)
**Target:** Delete 698 lines from `PenguinCLI` display methods

**Methods to move:**
```python
# Current location: PenguinCLI class
# Target location: UnifiedRenderer

- display_message()
- _display_user_message()
- _display_assistant_message()
- _display_tool_result()
- _display_diff_result()
- _render_diff_message()
- _format_code_block()
- _detect_language()  # Duplicate, delete from CLI
```

**Steps:**
1. Investigate current display methods in `PenguinCLI`
2. Check if `UnifiedRenderer` already has these methods
3. Move missing methods to `UnifiedRenderer`
4. Update `PenguinCLI` to delegate to `self.renderer`
5. Delete old methods from `PenguinCLI`
6. Run tests after each deletion
7. Delete duplicate `CODE_BLOCK_PATTERNS` from `cli.py` (keep in `renderer.py`)
8. Delete duplicate `_detect_language()` from `cli.py` (keep in `renderer.py`)

**Expected Result:**
- ~698 lines deleted from `cli.py`
- Rendering centralized in `UnifiedRenderer`
- Tests still passing

**Risk:** Medium - display is visible, easy to verify

---

### Phase 2: Extract Streaming Logic (Days 2-3)
**Target:** Delete 666 lines from `PenguinCLI` streaming methods

**Methods to move:**
```python
# Current location: PenguinCLI class
# Target location: StreamingDisplay

- _ensure_progress_cleared()  # 590 lines - THE MONSTER
- on_progress_update()
- _finalize_streaming()
- _handle_streaming_token()
- _handle_streaming_reasoning()
- _handle_streaming_tool()
```

**Steps:**
1. Investigate `_ensure_progress_cleared()` (590 lines) - understand what it does
2. Extract to `StreamingDisplay` or new `ProgressManager`
3. Replace all streaming logic with `StreamingDisplay`
4. Delete old methods from `PenguinCLI`
5. Run tests after each deletion

**Expected Result:**
- ~666 lines deleted from `cli.py`
- Streaming centralized in `StreamingDisplay`
- Tests still passing

**Risk:** High - streaming is complex, stateful

---

### Phase 3: Event System Migration (Days 3-4)
**Target:** Delete 343 lines from `PenguinCLI.handle_event()`

**Current State:**
- `PenguinCLI.handle_event()` is 331 lines
- `events.py` has `EventBus` but not used
- `EventType` enum has proper values: TOKEN_UPDATE, TOOL_CALL, TOOL_RESULT, PROGRESS, etc.

**Steps:**
1. Investigate why `events.py` isn't being used (test coverage? bugs?)
2. Replace `handle_event()` with EventBus subscribers
3. Delete 331-line event handler
4. Run tests

**Expected Result:**
- ~343 lines deleted from `cli.py`
- Event-driven architecture actually works
- Tests still passing

**Risk:** Medium - event system should work, just not used

---

### Phase 4: Split PenguinCLI Class (Days 4-5)
**Target:** Split 2,515-line class into 5 focused classes

**Current Classes (after Phases 1-3):**
```python
class PenguinCLI:  # Still ~1,500 lines
    # Should be a coordinator, not do everything
```

**Target Classes:**
```python
class SessionManager:      # Session state, ~300 lines
    - load_session()
    - save_session()
    - continue_session()
    - get_session_info()

class DisplayManager:     # Wraps renderer, ~150 lines
    - display_message()
    - display_error()
    - display_warning()

class StreamingManager:   # Wraps streaming display, ~200 lines
    - start_streaming()
    - handle_token()
    - finalize_streaming()

class EventManager:       # Wraps EventBus, ~150 lines
    - subscribe_to_events()
    - handle_event()
    - publish_event()

class InputManager:       # prompt_toolkit, ~100 lines
    - get_user_input()
    - handle_key_bindings()

class PenguinCLI:         # Coordinator, ~200 lines
    - __init__()
    - chat_loop()
    - coordinate_managers()
```

**Steps:**
1. Extract `SessionManager` from `PenguinCLI`
2. Extract `DisplayManager` (delegates to renderer)
3. Extract `StreamingManager` (delegates to streaming_display)
4. Extract `EventManager` (delegates to EventBus)
5. Extract `InputManager` (handles prompt_toolkit)
6. Keep `PenguinCLI` as coordinator
7. Run tests after each extraction

**Expected Result:**
- ~1,500 lines deleted from `cli.py` (now ~1,200 lines total)
- Clear separation of concerns
- Each class focused on one responsibility
- Tests still passing

**Risk:** High - biggest change, but most impactful

---

## Import Optimization (Post-Refactoring)

**Current:** 114 imports (slow startup: 1-2 seconds)

**Target:** < 50 imports (fast startup: < 1 second)

**Strategy:**
1. Identify unused imports (use `autoflake` or manual audit)
2. Lazy load heavy modules (only import when needed)
3. Remove duplicate imports
4. Consolidate related imports

**Questions to Resolve:**
- Are there specific imports causing slowdown?
- Can we defer ToolManager initialization?
- Can we defer memory indexing?

---

## Parallel Strategy with Sub-Agents

We can delegate work to sub-agents for parallel execution:

```python
# Agent 1: Test Creation Agent (DONE ✅)
# Task: Create comprehensive integration tests for CLI
# Output: tests/test_cli_integration.py (34 tests, all passing)

# Agent 2: Display Refactoring Agent  
# Task: Extract display logic to UnifiedRenderer
# Tools: apply_diff, enhanced_read
# Output: Updated renderer.py, reduced cli.py

# Agent 3: Streaming Refactoring Agent
# Task: Extract streaming logic to StreamingDisplay
# Tools: apply_diff, enhanced_read
# Output: Updated streaming_display.py, reduced cli.py

# Agent 4: Event Migration Agent
# Task: Migrate to EventBus system
# Tools: apply_diff, enhanced_read
# Output: Updated events.py, reduced cli.py
```

---

## Success Criteria

**Quantitative:**
- ✅ `cli.py` reduced from 5,747 to ~1,200 lines (79% reduction)
- ✅ `PenguinCLI` reduced from 2,515 to ~200 lines (92% reduction)
- ✅ Imports reduced from 114 to < 50 (56% reduction)
- ✅ All 34 integration tests passing
- ✅ No regressions in functionality

**Qualitative:**
- ✅ Clear separation of concerns (5 focused classes)
- ✅ Event-driven architecture working
- ✅ Rendering centralized in UnifiedRenderer
- ✅ Streaming centralized in StreamingDisplay
- ✅ Easier to onboard new developers
- ✅ Easier to add new features
- ✅ Easier to test individual components

---

## Risk Mitigation

**Before each phase:**
1. Run full test suite to establish baseline
2. Create git commit (checkpoint)
3. Document what will change

**During each phase:**
1. Make small, incremental changes
2. Run tests after each change
3. Roll back immediately if tests fail

**After each phase:**
1. Run full test suite
2. Manual smoke test (start CLI, send message)
3. Update documentation
4. Create git commit

**If tests fail:**
1. Identify root cause
2. Fix or roll back
3. Update tests if needed (behavior changed intentionally)
4. Document decision

---

## Documentation Updates

**After each phase, update:**
- `docs/docs/usage/cli_commands.md` (if commands changed)
- `docs/docs/cli/checkpoint-guide.md` (if checkpoints affected)
- `docs/docs/getting_started.md` (if startup changed)
- `README.md` (if architecture changed)

**New documentation:**
- Architecture diagram showing new class structure
- Migration guide for external tools using `penguin.cli.cli`
- Performance benchmarks (before/after import time)

---

## Open Questions

1. **Why isn't `events.py` being used?**
   - Test coverage issues?
   - Bugs in EventBus?
   - Historical reasons?

2. **Why did 40 Typer commands not migrate to `CommandRegistry`?**
   - Incomplete migration?
   - Backward compatibility concerns?
   - Technical blockers?

3. **What's the distinction between `ui.py` (821 lines) and `renderer.py` (1,229 lines)?**
   - Overlapping responsibilities?
   - Historical artifact?

4. **Are there external scripts/tools using `penguin.cli.cli` directly?**
   - Need to maintain backward compatibility?
   - Can we break them?

---

## Next Steps

**Immediate (Day 1):**
1. ✅ Create test safety net (DONE)
2. Start Phase 1: Extract Display Logic
3. Investigate current display methods in `PenguinCLI`
4. Check `UnifiedRenderer` capabilities

**Week 1:**
- Complete Phases 1-3 (display, streaming, events)
- Reduce `cli.py` to ~2,000 lines

**Week 2:**
- Complete Phase 4 (split PenguinCLI)
- Optimize imports
- Final documentation updates
- Performance benchmarking

---

## References

- Analysis: `context/architecture/rich_cli_analysis.md`
- Architecture: `architecture.md`
- CLI Commands: `docs/docs/usage/cli_commands.md`
- Checkpoint Guide: `docs/docs/cli/checkpoint-guide.md`
- Getting Started: `docs/docs/getting_started.md`
- Test Suite: `tests/test_cli_integration.py`