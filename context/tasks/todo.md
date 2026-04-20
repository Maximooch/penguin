# Follow-Up PR Todo

## Purpose

This file is the **current status snapshot** for the major follow-up workstreams after the
RunMode / Project / ITUV core-systems push.

It is intentionally organized by execution reality, not by the original planned order.
The previous version of this file became stale once several follow-up threads started in
parallel.

---

## Done

### RunMode / Project / ITUV Core Truth
- [x] Restore core RunMode / Project / ITUV truth and verification path
- [x] Add clarification wait/resume proof path
- [x] Add CLI scripted surface verification
- [x] Add web/API scripted surface verification
- [x] Align public docs/checklists with current runtime truth
- [x] Archive PR summary for the merged core-systems branch

### Current PR / Docs Alignment
- [x] Update public docs for typed dependencies, diagnostics, and clarification handling
- [x] Review `context/process/blueprint.template.md` for typed dependency and diagnostics drift
- [x] Review `context/tasks/testing_scenarios.md` for stale scenarios after clarification, diagnostics, and dependency-policy changes
- [x] Final docs pass for README / architecture / surface docs so they match current branch truth
- [x] PR write-up: summarize what the core-systems branch fixed, what it verified, and what was explicitly deferred

### Release / Versioning
- [x] Bump version to `0.6.3`
- [x] Update README version highlights for OpenAI / Codex integration emphasis
- [x] Push `v0.6.3` git tag

---

## In Progress

### PR: CLI Workspace Semantics and Ergonomics
**Status:** materially underway / first implementation slice exists

Completed in this thread:
- [x] Resolve the `project create --workspace` honesty gap
- [x] Clarify execution root vs project workspace behavior in command output
- [x] Improve project creation output so location semantics are obvious
- [x] Add/update regression coverage for explicit/default workspace behavior
- [x] Refresh relevant docs for project-create workspace semantics

Still remaining in this PR/workstream:
- [ ] Improve help/discoverability for project/task workflows more broadly
- [ ] Reduce safe CLI duplication only where tests protect behavior

Reference:
- `context/tasks/cli-interface-ergonomics-plan.md`
- `context/tasks/cli-refactor-and-bootstrap-audit.md`
- `context/tasks/cli-workspace-semantics-pr1-checklist.md`

### PR: RunMode Commands and Loop Ownership Audit / Command Truth
**Status:** audit done, Phase 1/3/5 done, Phase 2 mostly in, not fully closed yet

Completed in this thread:
- [x] Audit `--run`, `--247`, and `--continuous` semantics for current truth and usability
- [x] Decide `--247` remains a public alias / product-language flag
- [x] Clarify the current no-task continuous-mode behavior in the audit and checklist
- [x] Audit loop ownership boundaries between `RunMode` and `Engine`
- [x] Record completed findings, open questions, and recommended first PR scope
- [x] Create exact PR1 checklist for command-truth cleanup
- [x] Complete Phase 1 contract-definition pass
- [x] Complete Phase 3 time-limit truth investigation
- [x] Complete Phase 5 docs alignment for RunMode truth
- [x] Land most Phase 2 CLI help/output truth changes

Still remaining in this workstream:
- [ ] Finish Phase 2 test cleanup / closeout cleanly
- [ ] Decide whether any tiny `Engine.run_task(...)` cleanup belongs in this PR or should be deferred
- [ ] Decide whether to include the later web/API truth pass in the same PR or defer it
- [ ] Commit/push the remaining checklist/docs/ignore cleanup if not already bundled

Reference:
- `context/tasks/runmode-command-loop-audit.md`
- `context/tasks/runmode-command-truth-pr1-checklist.md`

---

## Next

### PR: Project Bootstrap Workflow MVP
**Why next:** high leverage once workspace semantics and runmode command truth are stable enough

- [ ] Add `penguin project init "name" --blueprint ./blueprint.md`
- [ ] Add `penguin project start <project-id|name>`
- [ ] Make project selection deterministic and honest
- [ ] Preserve orchestration/runtime truth in bootstrap commands
- [ ] Surface clarification / pending-review outcomes clearly in the high-level workflow

Reference:
- `context/tasks/project-bootstrap-workflow.md`
- `context/tasks/cli-refactor-and-bootstrap-audit.md`

### PR: RunMode Command Truth Cleanup Closeout
**Why next:** if the current runmode truth branch/PR is left half-finished, the audit loses value

- [ ] Finish remaining Phase 2 cleanup/tests
- [ ] Decide whether to execute Phase 6 web/API truth pass now
- [ ] Merge the runmode command-truth work or intentionally split remaining pieces

Reference:
- `context/tasks/runmode-command-truth-pr1-checklist.md`

---

## Deferred

### PR: PenguinAPI Surface Refresh
**Reason deferred:** lower immediate leverage than CLI/web/runtime truth; still important, but not the bottleneck this week

- [ ] Audit `PenguinAPI` method contracts against current runtime truth
- [ ] Verify clarification-flow parity through the Python API surface
- [ ] Review/normalize result shapes where needed
- [ ] Refresh Python API docs/examples
- [ ] Add a dedicated library-surface verification trail

Reference:
- `context/tasks/penguinapi-surface-refresh-plan.md`

### PR: Reliability Pass 2
**Reason deferred:** valuable hardening, but not the immediate unlock for product-facing flow

- [ ] Extend Hypothesis/property-based coverage for dependency-policy semantics
- [ ] Add stateful transition tests for `TaskStatus` and `TaskPhase`
- [ ] Add clarification lifecycle invariants for waiting/resume behavior
- [ ] Decide whether waiting tasks should release execution slots for other ready tasks
- [ ] Keep verification-planning docs aligned without pulling in premature TLA+ v2 scope

Reference:
- `context/tasks/runmode-project-ituv-checklist.md`
- `context/tasks/penguin_tla.md`

### Later / Larger Runtime Cleanup
**Reason deferred:** architecture cleanup should follow explicit contract truth, not race ahead of it

- [ ] Broader `cli.py` decomposition/refactor
- [ ] Larger `RunMode` / `Engine` loop cleanup beyond the surgical command-truth slice
- [ ] Unify time-limit semantics across RunMode, task/project budgets, and ITUV phase timeouts
- [ ] Deeper web/API surface truth pass if not included in the current runmode truth PR
- [ ] `penguin/llm` Responses/Codex follow-up refactor: preserve more structured Responses semantics end-to-end so OpenAI/Codex tool-only turns rely less on engine-side empty-loop heuristics and more on first-class tool/result/response state

Reference:
- `context/tasks/web-and-tui-bugfix.md`
- `context/tasks/tui-opencode-fork-alignment-plan.md`

---

## Strategic Read (April 17, 2026)

Current state:
- We are **behind on the original April feature timeline** in visible product terms.
- We are **ahead of where the repo was** on runtime truth, clarification handling, and public-surface verification.
- The last ~3 days produced the majority of the meaningful structural progress after ~2 weeks that were more dominated by bug-fixing and recovery work.

That means the correct interpretation is:
- not "everything is off the rails"
- not "the plan is on track"
- but rather: **the substrate is finally getting trustworthy enough that the next visible product steps can land on something real**.

---

## Suggested Immediate Order

1. Finish / close the RunMode command-truth PR cleanly
2. Finish / merge the CLI workspace semantics PR cleanly
3. Move to Project Bootstrap Workflow MVP
4. Revisit PenguinAPI Surface Refresh
5. Do Reliability Pass 2 after the product-facing path is less mushy

---

## Notes

- This file should be updated when work actually moves between buckets.
- Do not treat the original PR ordering as sacred if the real dependency graph changes.
- Track capabilities shipped, not just number of PRs opened.
