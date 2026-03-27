# Tool Root Resolution Hardening TODO

## Objective

- Make project/workspace write-root resolution predictable, testable, and debuggable.
- Reduce “wrong root” bugs when `PENGUIN_PROJECT_ROOT`, workspace settings, and write-root mode interact.
- Ensure file tools consistently explain where they are allowed to read/write.

## Why This Exists

- ToolManager currently layers multiple root-resolution paths:
  - env override
  - auto-detected allowed roots
  - workspace root
  - default write-root mode
- That flexibility is useful, but it is also a classic source of subtle path bugs.

## Audit Evidence

- `penguin/tools/tool_manager.py:187-228`
- `penguin/utils/path_utils.py`
- `penguin/system/execution_context.py`
- `tests/test_root_override.py`
- `tests/test_permission_engine.py`

## Progress Snapshot

- [ ] Document the canonical root-resolution order
- [ ] Add regression tests for conflicting env/config combinations
- [ ] Expose final resolved roots in diagnostics/tool output where appropriate
- [ ] Simplify root selection logic if equivalent branches can be collapsed
- [ ] Confirm permission policy uses the same normalized root semantics

## Checklist

### Phase 1 - Behavior Freeze
- [ ] Create a matrix of env/config/root-mode combinations
- [ ] Capture current behavior in tests before refactoring
- [ ] Identify ambiguous or surprising cases

### Phase 2 - Simplification
- [ ] Define one canonical resolution flow
- [ ] Normalize paths early
- [ ] Ensure project-root and workspace-root decisions are made in one place

### Phase 3 - Visibility
- [ ] Improve logs/diagnostics for resolved roots
- [ ] Expose helpful messages on permission or boundary failures
- [ ] Document the behavior in tooling/docs

## Verification Targets

- `tests/test_root_override.py`
- `tests/test_permission_engine.py`
- `tests/test_execution_context.py`
- targeted file edit/read smoke tests

## Notes

- Users tolerate restrictions.
- Users do not tolerate random-looking path behavior.
