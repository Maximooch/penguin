# Follow-Up PR Todo

## Purpose

This file tracks the follow-up PRs that should come after the current
RunMode / Project / ITUV core-systems branch.

It is intentionally biased toward:
- keeping the current branch scoped
- separating core runtime truth from interface ergonomics
- making the next PR sequence explicit

## Current PR Closeout

These are still reasonable to finish inside the current PR because they are
directly tied to the runtime refactor and would be redundant as a standalone PR.

### Category: Current PR / Docs Alignment
- [x] Update public docs for typed dependencies, diagnostics, and clarification handling
- [x] Review `context/process/blueprint.template.md` for typed dependency and diagnostics drift
- [x] Review `context/tasks/testing_scenarios.md` for stale scenarios after clarification, diagnostics, and dependency-policy changes
- [x] Final docs pass for README / architecture / surface docs so they match current branch truth
- [x] PR write-up: summarize what this branch fixed, what it verified, and what is explicitly deferred

## Follow-Up PRs

### Category: Python Library Surface

#### PR: PenguinAPI Surface Refresh
- [ ] Audit `PenguinAPI` method contracts against current runtime truth
- [ ] Verify clarification-flow parity through the Python API surface
- [ ] Review/normalize result shapes where needed
- [ ] Refresh Python API docs/examples
- [ ] Add a dedicated library-surface verification trail

Reference:
- `context/tasks/penguinapi-surface-refresh-plan.md`

### Category: CLI Interface Ergonomics

#### PR: CLI Workspace Semantics and Ergonomics
- [ ] Resolve the `project create --workspace` honesty gap
- [ ] Clarify execution root vs project workspace behavior
- [ ] Improve project creation output so location semantics are obvious
- [ ] Improve help/discoverability for project/task workflows
- [ ] Reduce safe CLI duplication only where tests protect behavior

Reference:
- `context/tasks/cli-interface-ergonomics-plan.md`

### Category: Project Workflow UX

#### PR: Project Bootstrap Workflow MVP
- [ ] Add `penguin project init "name" --blueprint ./blueprint.md`
- [ ] Add `penguin project start <project-id|name>`
- [ ] Make project selection deterministic and honest
- [ ] Preserve orchestration/runtime truth in bootstrap commands
- [ ] Surface clarification / pending-review outcomes clearly in the high-level workflow

Reference:
- `context/tasks/project-bootstrap-workflow.md`

### Category: RunMode UX and Loop Architecture

#### PR: RunMode Commands and Loop Ownership Audit
- [ ] Audit `--run`, `--247`, and `--continuous` semantics for current truth and usability
- [ ] Decide whether `--247` remains a public alias, hidden alias, or internal-only compatibility flag
- [ ] Clarify no-task continuous mode behavior and shutdown/idle semantics
- [ ] Review `RunMode.start(...)` vs `RunMode.start_continuous(...)` command affordances
- [ ] Audit loop ownership boundaries between `RunMode` and `Engine`
- [ ] Decide what should remain in `RunMode` versus what should be unified into engine loop configuration
- [ ] Reduce duplicated or overlapping termination/progress concepts where safe
- [ ] Add targeted docs/tests for the final command and loop contract

Reference:
- `penguin/run_mode.py`
- `penguin/engine.py`
- `penguin/cli/cli.py`

### Category: Verification Hardening

#### PR: Reliability Pass 2
- [ ] Extend Hypothesis/property-based coverage for dependency-policy semantics
- [ ] Add stateful transition tests for `TaskStatus` and `TaskPhase`
- [ ] Add clarification lifecycle invariants for waiting/resume behavior
- [ ] Decide whether waiting tasks should release execution slots for other ready tasks
- [ ] Keep verification-planning docs aligned without pulling in premature TLA+ v2 scope

Reference:
- `context/tasks/runmode-project-ituv-checklist.md`
- `context/tasks/penguin_tla.md`

## Suggested Order

1. Finish current PR docs alignment
2. PenguinAPI Surface Refresh
3. CLI Workspace Semantics and Ergonomics
4. Project Bootstrap Workflow MVP
5. RunMode Commands and Loop Ownership Audit
6. Reliability Pass 2

## Notes

- Docs drift cleanup is folded into the current PR on purpose.
- The current branch should remain the core truth / verification PR.
- Interface ergonomics and higher-level workflow sugar should land after that, not inside it.
