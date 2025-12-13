# Penguin Codebase Improvements

A prioritized list of technical debt and architectural improvements identified during the max_tokens migration and auto-continuation bug fix session.

---

## 🔴 Critical Priority (Actually Stupid)

### 1. The Codebase is Too Big and Tangled

**Files:**
- `penguin/core.py`: 3500+ lines
- `penguin/cli/cli.py`: 5200+ lines  
- `penguin/cli/interface.py`: 2400+ lines
- `penguin/engine.py`: 1000+ lines

**Problem:** When everything is in one file, every change risks breaking something else. The token migration touched 38 files because concerns aren't separated. This slows development and breeds bugs.

**Solution:** Extract focused modules. `core.py` should be <500 lines orchestrating smaller components.

**Suggested Breakdown for core.py:**
- `core/orchestrator.py` - Main coordination logic
- `core/agent_manager.py` - Agent registration/lifecycle
- `core/message_processor.py` - Message handling
- `core/streaming.py` - Streaming logic
- `core/config_runtime.py` - Runtime configuration

**Estimated Effort:** Large (multiple sessions)

---

### 2. Inconsistent Patterns Everywhere

**Examples Found:**
- Config access: `data.get("key")` vs `getattr(obj, "key", None)` vs direct attribute
- Async patterns: Some async, some sync, some mixed in same class
- Config types: Dict-based AND dataclass AND Pydantic models
- File editing: `apply_diff` vs `multiedit` vs `enhanced_write` (3 ways to edit files)
- Logging: `logger.debug` vs `print()` vs `console.print()`

**Problem:** New code copies random patterns. Bugs hide in the inconsistency. Onboarding is painful.

**Solution:** 
1. Document the "blessed" approach for each concern
2. Create an AGENTS.md or CONTRIBUTING.md with patterns
3. Gradually refactor to consistency

**Estimated Effort:** Medium (ongoing)

---

### 3. The System Prompt is 64KB

**Location:** `penguin/prompt_actions.py`, `penguin/system_prompt.py`

**Problem:**
- ~64,000 characters / ~16,000 tokens just for instructions
- 10% of context window consumed before conversation starts
- Redundant sections (20 mentions of `finish_response` alone)
- Contradictory instructions in places

**Solution:**
1. Audit and deduplicate instructions
2. One clear instruction > five redundant ones
3. Consider dynamic prompt assembly based on task type
4. Move examples to a separate retrievable section

**Estimated Effort:** Medium (1-2 focused sessions)

**Quick Wins:**
- Remove duplicate `finish_response` documentation
- Consolidate code formatting rules (repeated 3+ times)
- Remove verbose examples that aren't referenced

---

## 🟡 Medium Priority (Annoying but Survivable)

### 4. No Clear Error Boundaries

**Pattern Found:**
```python
except Exception as e:
    logger.warning(f"Something failed: {e}")
    # continue anyway
```

**Problem:** Silent failures are worse than loud crashes. You don't know what's broken until it's really broken.

**Solution:**
1. Fail fast and loud for unexpected errors
2. Only catch specific, recoverable exceptions
3. Add error classification (recoverable vs fatal)
4. Consider a central error handler

**Files to Audit:**
- `penguin/core.py` - Many broad exception catches
- `penguin/engine.py` - Silent swallows in loop
- `penguin/llm/adapters/*.py` - API error handling

**Estimated Effort:** Medium

---

### 5. Testing is Sparse

**Current State:**
- Mostly integration tests and mocks
- No unit tests for core logic

**Missing Unit Tests For:**
- Token budget calculations (`context_window.py`)
- Action parsing (`utils/parser.py`)
- Context window trimming logic
- Config merge/override logic
- Message categorization

**Problem:** Refactoring is scary. Bugs in core logic go undetected.

**Solution:**
1. Add unit tests for math/logic parts (fast, catch regressions)
2. Start with `context_window.py` - critical and complex
3. Add test for auto-continuation (verify loop behavior)

**Estimated Effort:** Medium (ongoing)

---

### 6. Configuration is a Maze

**Config Sources:**
1. `config.yml` (user settings)
2. Environment variables
3. Dataclass defaults
4. Runtime overrides
5. CLI arguments
6. Per-agent settings
7. Model-specific settings

**Problem:** "Where does this value come from?" is unanswerable without tracing 5+ files.

**Solution:**
1. Document clear override precedence
2. Single `ConfigResolver` that logs where values came from
3. Add `--show-config-sources` debug flag
4. Reduce config sources if possible

**Estimated Effort:** Medium

---

## 🟢 Low Priority (Polish Later)

### 7. Dead Code / Commented Blocks

**Problem:** Lots of `# TODO`, `# DEPRECATED`, commented-out code blocks adding noise.

**Solution:** 
- Remove truly dead code
- Convert important TODOs to GitHub issues
- Delete commented code (git has history)

**Estimated Effort:** Small (cleanup session)

---

### 8. Inconsistent Logging

**Current State:**
- `logger.debug()` in some places
- `print()` in others
- `console.print()` (Rich) in CLI
- Some debug prints left in production code

**Solution:**
1. Use `logger` everywhere except CLI display
2. CLI display uses `console.print()` only in CLI layer
3. Remove debug `print()` statements
4. Add log level configuration

**Estimated Effort:** Small

---

### 9. Magic Numbers

**Examples Found:**
- `max_iters = 5000` (engine.py)
- `0.85` safety fraction (context_window.py)
- `200000` default context (multiple places)
- `8000` / `8192` default output tokens
- `0.05` sleep delays

**Solution:**
1. Move to named constants with docstrings
2. Centralize in a `constants.py` or config
3. Document why each value was chosen

**Estimated Effort:** Small

---

## Suggested Session Order

1. **System Prompt Trim** - High impact, relatively safe, immediate token savings
2. **Add Unit Tests for Context Window** - Safety net before refactoring
3. **Split core.py** - Biggest architectural win, enables everything else
4. **Error Boundary Audit** - Find and fix silent failures
5. **Configuration Cleanup** - Make debugging easier
6. **Pattern Documentation** - Prevent future inconsistency
7. **Polish items** - Dead code, logging, magic numbers

---

## Related Issues

- Dependabot: 26 vulnerabilities (1 critical, 5 high) - see GitHub Security tab
- Auto-continuation bug: Fixed in commit d4fe084
- Token naming: Completed in commit b66d692

---

*Created: Session with Penguin, following max_tokens migration*
*Last Updated: Same session*
