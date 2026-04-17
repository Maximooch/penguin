# RunMode Commands and Loop Ownership Audit

## Purpose

This document records the completed audit of Penguin's RunMode command surface and the ownership boundary between:
- CLI run-mode affordances (`--run`, `--247`, `--continuous`, `--time-limit`)
- `RunMode` outer orchestration
- `Engine` inner reasoning/action loops

The goal is to reduce semantic drift, clarify ownership, and create a safe path for future cleanup without blindly rewriting working runtime behavior.

## Audit Scope

### Files Investigated
- `penguin/cli/cli.py`
- `penguin/run_mode.py`
- `penguin/engine.py`
- `penguin/core.py`

### Existing Tests Reviewed
- `tests/test_runmode_continuous_drift.py`
- `tests/test_runmode_task_resolution.py`
- `tests/test_runmode_project_completion.py`
- `tests/test_runmode_clarification_handling.py`
- `tests/test_runmode_streaming.py`
- `tests/api/test_sse_and_status_scoping.py`
- `tests/api/test_web_routes_task_shapes.py`
- `tests/api/test_penguin_api_surface.py`
- `tests/test_stateful_task_clarification_hypothesis.py`

## Completed Findings

### 1. CLI currently exposes runmode through top-level flags, not a dedicated namespace
Observed in `penguin/cli/cli.py:832-905`.

Current public affordances:
- `--run <TASK_OR_PROJECT>`
- `--247` / `--continuous`
- `--time-limit <MINUTES>`
- optional `--description`

This means autonomous execution is not grouped under a dedicated `runmode` command tree. Instead, it is bolted onto the global callback while project/task workflows live under subcommands.

**Implications:**
- weak discoverability
- help-text clutter at the top-level
- hard-to-explain relationship between chat mode, direct prompt mode, and autonomous mode
- higher refactor risk because routing behavior is concentrated in the giant callback

### 2. `--247` is a public alias, but its meaning is product-language fuzzy
Observed in `penguin/cli/cli.py:856-866`.

Today:
- `--247` and `--continuous` are exact aliases
- help text says: `Run in continuous mode until manually stopped.`

That is technically true but semantically incomplete.
It does not explain:
- what happens when there is no explicit task
- how project-scoped continuous mode behaves differently from non-project exploratory mode
- whether shutdown is manual-only or can also happen from idle conditions/time limits

**Implications:**
- user expectation mismatch
- product language is weaker than runtime reality
- `--247` is catchy but not self-explanatory

**Direction:**
`--247` should remain a public first-class flag. Its meaning should be clarified as: Penguin keeps working continuously until the current work is considered done.

### 3. `RunMode` clearly owns the outer orchestration loop
Observed in `penguin/run_mode.py` and supported by `penguin/core.py:3264-3315`.

Core handoff behavior:
- `PenguinCore.start_run_mode(...)` instantiates `RunMode`
- core then delegates to either:
  - `run_mode.start(...)`, or
  - `run_mode.start_continuous(...)`

Current `RunMode` responsibilities include:
- task resolution
- project-scoped task lookup
- DAG/ready-task selection
- continuous-mode orchestration
- idle/shutdown behavior
- synthetic fallback task creation in non-project continuous mode
- clarification answer persistence and resume
- interpretation of clarification-needed state at the task orchestration layer

**Conclusion:**
`RunMode` is not a thin wrapper. It is the owner of autonomous outer-flow orchestration.

### 4. `Engine` owns the inner reasoning/action loops
Observed in `penguin/engine.py`.

Current `Engine` responsibilities include:
- `run_response(...)`
- `run_task(...)`
- `_iteration_loop(...)`
- finish-tool detection (`finish_response`, `finish_task`)
- stop-condition checks
- max-iteration enforcement
- action/tool iteration and response assembly

**Conclusion:**
`Engine` is the owner of intra-task reasoning/action loop execution, not project/task orchestration.

### 5. There is real duplication risk between `Engine.run_task(...)` and `_iteration_loop(...)`
Observed in `penguin/engine.py` during audit.

`run_task(...)` still contains substantial loop/termination logic instead of acting as a thin configuration wrapper over `_iteration_loop(...)`.

This does not prove a bug today, but it creates obvious maintenance risk:
- termination behavior can drift
- finish-tool semantics can drift
- status/event emission can drift
- fixes may land in one loop path but not the other

**Conclusion:**
This is a valid refactor target, but only after contract truth and tests are strong enough.

### 6. Continuous mode has two different behavioral contracts today
Confirmed by code and tests:
- `tests/test_runmode_continuous_drift.py`
- `RunMode.start_continuous(...)`

Current behavior:
- **Project-scoped continuous mode**: does not synthesize `determine_next_step`; it idles/shuts down honestly when no project task is ready.
- **Non-project continuous mode**: still synthesizes `determine_next_step` when no explicit task is available.

This split is intentional in behavior, but weakly documented in user-facing language.

**Conclusion:**
There are really two continuous-mode contracts today:
1. project workflow automation
2. exploratory autonomous continuation

That distinction should be made explicit.

**Direction:**
The exploratory/no-project path should remain for now, but it should be documented more honestly as:
- we do not have a fully explicit plan yet
- Penguin will determine next steps as it goes
- Penguin should document progress and judgment calls in journal/context artifacts when appropriate

### 7. Clarification ownership is split, but currently coherent
Confirmed by:
- `tests/test_runmode_clarification_handling.py`
- `tests/api/test_web_routes_task_shapes.py`
- `tests/api/test_sse_and_status_scoping.py`

Current split:
- `Engine` produces responses/tool flows that can imply clarification is needed
- `RunMode` interprets that at the task-orchestration layer and persists clarification requests
- CLI/web/API surface `waiting_input`, `clarification_needed`, and resume behavior

Important proven behavior:
- clarification does **not** falsely complete the task
- clarification can be resumed end-to-end
- `waiting_input` truth is preserved on public surfaces

**Conclusion:**
Clarification waiting/resume belongs conceptually at the `RunMode`/task orchestration layer, not inside Engine’s inner loop contract.

### 8. Final project-task completion is intentionally not owned by `RunMode`
Confirmed by `tests/test_runmode_project_completion.py`.

`RunMode.start(...)` may return `completed`, but it does not directly finalize project-task status in the project manager.

**Conclusion:**
Project completion/review semantics remain above `RunMode` in the broader orchestration stack. This is good and should stay explicit.

### 9. Task resolution and project scoping are materially improved and already protected by tests
Confirmed by `tests/test_runmode_task_resolution.py`.

Protected behaviors:
- no global fallback when `task_id` is missing
- ambiguous title resolution within scope fails honestly
- title resolution is project-scoped when `project_id` is present

**Conclusion:**
This is one of the stronger parts of the current RunMode contract and should not be destabilized casually.

### 10. CLI wording around runmode remains weaker than the actual runtime truth
Observed in `_handle_run_mode(...)` and top-level flag help.

Examples:
- continuous mode help text is minimal and hides the dual contract
- top-level wording does not explain project vs exploratory behavior
- completion messaging is generic (`Run mode execution completed.`) even though outcomes may include clarification waiting, idle exit, or time-limited exit

**Conclusion:**
The first cleanup should be wording/contract truth, not refactoring loop ownership.

## Existing Coverage Summary

### Already Protected Well Enough To Refactor Carefully Later
- project-scoped task resolution
- no-task continuous drift policy split
- clarification wait/resume happy path
- no false project-task completion from `RunMode`
- web/API preservation of waiting-input truth

### Under-Protected / Missing Coverage
- CLI help/output truth for runmode flags
- top-level `--247` / `--continuous` messaging and examples
- idle/time-limit/shutdown wording behavior
- consistency between `Engine.run_task(...)` and `_iteration_loop(...)`
- direct contract tests that compare single-task mode vs continuous mode outcomes
- blueprint-defined time-limit behavior versus generic manual limits

## Open Questions

### Public Command Questions
- Should future autonomous execution move toward a dedicated command namespace later (for example, `penguin run ...`)?
- Should top-level flags remain supported for compatibility even if a new namespace is added?

### Continuous-Mode Contract Questions
- What should the public docs say about continuous mode when no explicit task is given?
- Should project-scoped continuous mode surface a clearer idle/no-ready-task summary instead of generic completion wording?
- How should blueprint-defined time limits interact with CLI `--time-limit` and idle shutdown behavior?
- Should time-limit wording distinguish between:
  - explicit CLI/user-imposed limit
  - blueprint/task-defined limit
  - idle/no-work shutdown

### Ownership Questions
- Should `RunMode` remain the long-term owner of outer continuous orchestration? Current evidence says yes.
- Should `Engine.run_task(...)` be reduced into a thinner wrapper over `_iteration_loop(...)`? Yes, but it should be treated as a follow-up cleanup unless a small, test-backed simplification clearly fits within the first PR.
- Should clarification waiting/resume remain anchored at RunMode/task orchestration? Current evidence says yes.

### Status / Termination Questions
- Which layer should own final user-facing wording for idle exit, time-limit exit, clarification pause, and continuous shutdown?
- Should review/pending-review remain a task/orchestration-only concept and stay out of Engine? Current evidence says yes.

## Decisions Made After Audit Review

- `--247` stays public. It is part of the Penguin product language and should mean: Penguin keeps working continuously until the current work is considered done.
- The exploratory no-task continuous mode stays for now. It should be documented honestly as opportunistic/autonomous continuation rather than pretending a fully explicit plan already exists.
- `RunMode` remains the owner of outer orchestration.
- Clarification waiting/resume remains anchored in `RunMode` / task orchestration.
- `Engine.run_task(...)` should become thinner over time, especially around the task-step loop, but deeper cleanup should follow contract-truth work rather than lead it.
- Time-limit behavior deserves explicit review, especially when limits are defined in project/blueprint/task metadata rather than only via CLI flags.

## Recommended First PR Scope

### Goal
Improve runmode command truth and safety **without** changing the deeper runtime architecture yet.

### Why This First
Because the current problems are more semantic than structural:
- users see fuzzy command behavior before they see loop-ownership internals
- wording and contract truth can be fixed with low blast radius
- deeper refactors need stronger tests first

### PR 1: RunMode Command Truth and Contract Cleanup

#### In Scope
- document the current meaning of `--run`, `--continuous`, and `--247`
- clarify the two continuous-mode contracts:
  - project-scoped workflow mode
  - exploratory/no-project fallback mode
- improve CLI help and output wording for:
  - continuous mode
  - no-task behavior
  - time-limit behavior
  - idle/shutdown behavior
- explicitly review how blueprint/task-defined time limits surface versus plain CLI `--time-limit`
- add/strengthen CLI and RunMode tests for those contracts

#### Out of Scope
- moving loop ownership between `RunMode` and `Engine`
- introducing a new `runmode`/`run` command namespace
- rewriting `cli.py`
- removing exploratory fallback behavior entirely

#### Maybe In Scope If It Stays Surgical
- small, test-backed simplification in `Engine.run_task(...)` where the task-step loop is obviously duplicative with `_iteration_loop(...)`
- only if it reduces risk without broadening the PR into architectural churn

#### Files Likely Involved
- `penguin/cli/cli.py`
- `penguin/run_mode.py`
- `docs/docs/usage/automode.md`
- `docs/docs/usage/cli_commands.md`
- new/updated tests for runmode CLI messaging and no-task behavior

#### Suggested Tests
- CLI help/output for `--run`, `--continuous`, `--247`
- explicit assertions for no-task project-scoped continuous mode behavior
- explicit assertions for no-task non-project exploratory fallback behavior
- explicit assertions for idle vs clarification vs completed messaging distinctions
- assertions for explicit CLI `--time-limit` wording/behavior
- assertions for blueprint/task-defined time-limit behavior where that contract already exists

## Mapped Change Buckets Needed Later

### Bucket A: Docs / Contract
- runmode command truth
- continuous-mode semantics
- idle/shutdown/time-limit wording
- blueprint-defined time-limit wording and precedence rules
- clarification visibility contract

### Bucket B: CLI Semantics
- help/discoverability cleanup
- possible future namespace redesign
- de-emphasize `--247` if needed without breaking compatibility

### Bucket C: RunMode Cleanup
- explicit continuous-mode policy handling
- synthetic fallback policy clarity
- clearer event/status naming for orchestration states

### Bucket D: Engine Loop Cleanup
- reduce duplication between `run_task(...)` and `_iteration_loop(...)`
- unify termination semantics where safe
- make task-step loop/event behavior easier to reason about

### Bucket E: Tests / Verification
- CLI runmode help/output tests
- cross-layer status wording tests
- Engine loop equivalence tests
- additional idle/shutdown/time-limit assertions

## Recommended Order

1. Fix command/help/contract truth
2. Add stronger tests around runmode semantics
3. Normalize status/output wording
4. Only then refactor loop ownership boundaries
5. Consider larger command-surface redesign later

## Bottom Line

The audit is now complete enough to support a real next step.

### Final recommendation
Do **not** start with a loop refactor.

Start with a small PR that makes the public runmode contract honest:
- what `--run` means
- what `--continuous` / `--247` mean
- what happens with no task
- how exploratory no-task behavior should be explained and journaled
- how explicit versus blueprint-defined time limits should be surfaced
- how clarification/idle/shutdown states are surfaced

Once that contract is explicit and test-backed, the deeper `RunMode` vs `Engine` cleanup becomes much less dangerous.
