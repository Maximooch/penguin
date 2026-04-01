# RunMode + Project Management + Blueprint/ITUV Gap Matrix

## Purpose

This document captures the current state of the `RunMode`, project management, blueprint, and ITUV plumbing. It focuses on what is actually implemented, what is only modeled, what is broken or ambiguous, and the minimum plan required to make the system function reliably.

## Technical Overview

### System Components

- `penguin/project/manager.py`
  - Primary control plane for projects and tasks.
  - Handles project/task CRUD, status transitions, dependency checks, DAG construction, DAG frontier selection, and blueprint sync.
- `penguin/project/models.py`
  - Defines `Task`, `Project`, `Blueprint`, `BlueprintItem`, `TaskStatus`, and `TaskPhase`.
  - Contains most of the schema needed for ITUV, but schema is not the same as enforcement.
- `penguin/project/blueprint_parser.py`
  - Parses blueprint files from Markdown, YAML, or JSON.
  - Supports frontmatter, tasks, dependencies, acceptance criteria, recipe references, validation blocks, and usage recipes.
- `penguin/run_mode.py`
  - Executes a task autonomously.
  - Supports single-task and continuous mode.
  - Can optionally use DAG selection when a `project_id` is present.
- `penguin/project/workflow_orchestrator.py`
  - The current orchestration layer tying task selection, execution, validation, and completion together.
- `penguin/project/validation_manager.py`
  - Current validation gate.
  - Today it is basically a pytest runner with permissive fallback behavior.
- `penguin/project/task_executor.py`
  - Bridges project tasks into `RunMode` execution.

### Current Functional Flow

#### Blueprint Path

1. Blueprint file is parsed into a `Blueprint` plus `BlueprintItem`s.
2. `ProjectManager.sync_blueprint()` creates or updates project tasks.
3. Blueprint dependency IDs are resolved into task IDs.
4. DAG cache is invalidated.
5. Continuous mode can later pull the next ready task using DAG selection.

#### Task Execution Path

1. `WorkflowOrchestrator.run_next_task()` asks `ProjectManager` for the next task.
2. Task is marked `RUNNING`.
3. `ProjectTaskExecutor.execute_task()` invokes `RunMode.start()`.
4. `RunMode` executes the task via the core engine.
5. Validation may run afterward.
6. Task is eventually marked `COMPLETED`, `FAILED`, or left in an unexpected state.

### What ITUV Means in This Codebase Today

The codebase defines ITUV phases:

- `PENDING`
- `IMPLEMENT`
- `TEST`
- `USE`
- `VERIFY`
- `DONE`
- `BLOCKED`

However, the execution system does not yet enforce a real phase machine. The phases are present in models and blueprint metadata, but the main execution path still behaves more like:

- execute task once
- maybe run pytest
- maybe mark completed

That is not a true Implement → Test → Use → Verify pipeline.

## Gap Matrix

| Area | Current State | Evidence | Risk | Minimum Fix |
| --- | --- | --- | --- | --- |
| Task model for ITUV | Implemented in schema | `TaskPhase`, `Task.phase`, `recipe`, `acceptance_criteria`, routing metadata | Low | Keep, use as source of truth |
| Blueprint parsing | Mostly implemented | Markdown/YAML/JSON parsing, frontmatter, tasks, dependencies, recipes, validation | Low | Add tests and stricter validation |
| Blueprint → task sync | Implemented | `sync_blueprint()` creates/updates tasks and resolves dependencies | Low | Add tests for update/idempotency/dependency errors |
| DAG scheduling | Implemented for project-scoped execution | `build_dag()`, `get_ready_tasks()`, `get_next_task_dag()` | Medium | Make this the default for project tasks |
| Legacy task selection | Implemented but weaker | `get_next_task()` sorts only by priority/created_at | Medium | Restrict to fallback-only behavior |
| Single-task RunMode resolution | Partially implemented, ambiguous fallback | Falls back from `task_id` to global title match | High | Remove global ambiguity; require scoped lookup |
| Continuous mode project awareness | Partially implemented | DAG is only used if `project_id` exists | Medium | Ensure project-scoped tasks always carry project_id |
| ITUV phase advancement | Mostly missing | No true phase state machine in orchestrator | High | Add explicit phase transitions and gates |
| TEST gate | Weakly implemented | Validation is mostly pytest execution | High | Bind phase-specific tests and fail closed |
| USE gate | Missing as an enforced gate | Recipe is parsed/stored but not executed by orchestrator | High | Add usage recipe execution plumbing |
| VERIFY gate | Weak and permissive | “pytest missing” and “no tests found” can validate | High | Make verify depend on explicit evidence |
| Completion integrity | Broken | `RunMode` can complete a task before validation; orchestrator may skip validation | Critical | Centralize completion in orchestrator only |
| Dependency cycle validation at create time | Incomplete | `_validate_dependencies()` has TODO for cycle detection | Medium | Add cycle detection on create/update |
| Dream workflow | Stale/broken surface | Constructor mismatches with current class signatures | Medium | Mark deprecated or refactor to compile |
| No-task behavior in continuous mode | Functional but risky | Falls back to `determine_next_step` synthetic task | Medium | Guard with project context and operator intent |

## Critical Findings

### 1. Completion Can Bypass Validation

This is the biggest integrity bug.

Current behavior:

- `RunMode.start()` can mark a task `COMPLETED` after successful execution.
- `WorkflowOrchestrator.run_next_task()` reloads the task.
- If the task is already `COMPLETED`, validation is skipped.

Result:

- A task may be considered done without going through TEST/USE/VERIFY.

That defeats the point of ITUV.

### 2. ITUV Exists in Metadata, Not in Control Flow

The code stores:

- phase
- phase timeboxes
- recipe
- acceptance criteria

But it does not operate on them as hard gates. That means the project system can claim ITUV support while still behaving like a one-shot executor.

### 3. Validation Fails Open

Current validation behavior is too forgiving:

- if changed test files exist, run them
- otherwise run full pytest
- if pytest is missing, validation passes
- if no tests are found, validation passes

That is acceptable for a toy MVP, not for a trustworthy project management workflow.

### 4. Task Resolution Is Ambiguous

When `task_id` lookup fails, `RunMode` falls back to a global title match across all tasks. That can select the wrong task when different projects use similar titles like “Add auth tests” or “Refactor logging”.

### 5. Continuous Mode Still Has Drift Risk

When no task is found, continuous mode synthesizes `determine_next_step`. That may be useful in exploratory workflows, but it is dangerous for project execution because it allows the system to escape the explicit work graph.

## Plan To Fix Missing Plumbing

This is the minimum viable plumbing plan. No gold plating. Just enough to make the system functional and trustworthy.

### Phase 0: Define the State Machine Contract

#### Goal

Define the canonical relationship between task `status`, task `phase`, review state, and synthetic task persistence before patching execution flow.

#### Why This Comes First

Right now the codebase effectively has two state machines pretending to be one:

- `status`: lifecycle and review progression
- `phase`: ITUV execution progression

If the allowed combinations are not defined first, the implementation work in later phases will just move bugs around. That is how you end up with nonsense states like `status=COMPLETED` while `phase=IMPLEMENT`.

#### Changes

- Define allowed `status` × `phase` combinations.
- Define terminal states and review semantics.
- Define when automatic verification may promote `PENDING_REVIEW` to `COMPLETED`.
- Define the persistence contract for synthetic tasks created during continuous mode.
- Define invalid states and how the system should reject or repair them.

#### Required Invariants

- `status=COMPLETED` implies `phase=DONE`.
- `phase=DONE` implies `status in {PENDING_REVIEW, COMPLETED}`.
- `status=RUNNING` implies `phase in {IMPLEMENT, TEST, USE, VERIFY}`.
- `status=FAILED` implies `phase != DONE`.
- project-managed execution must resolve tasks by ID, not ambiguous title lookup.
- synthetic tasks must persist provenance, reason, generator, and project linkage.

#### Acceptance Criteria

- The plan defines one canonical state machine contract for tasks.
- Later phases reference this contract instead of inventing their own rules.
- Invalid status/phase combinations are listed explicitly.
- Synthetic task persistence requirements are defined explicitly.

#### Deliverables

Phase 0 should produce the following concrete artifacts:

- A written contract defining the canonical meanings of `TaskStatus` and `TaskPhase`.
- A status/phase transition table.
- An invalid-state table listing forbidden `status × phase` combinations.
- A short review-semantics section defining:
  - when `PENDING_REVIEW` is entered
  - when `PENDING_REVIEW -> COMPLETED` is allowed
  - when a task is reopened back into active execution
- A synthetic-task contract defining:
  - required fields
  - persistence format and location
  - linkage to project/task graph
  - execution eligibility rules
- A migration/repair note for pre-existing invalid tasks.
- A list of enforcement points in code, at minimum covering:
  - `penguin/project/models.py`
  - `penguin/project/manager.py`
  - `penguin/run_mode.py`
  - `penguin/project/workflow_orchestrator.py`
  - storage-layer validation if needed
- A compact invariant list that later tests and `penguin_tla.md` can reuse.

#### Definition Checklist

Before Phase 0 is considered complete, the plan must explicitly answer these questions:

- What does each `TaskStatus` mean operationally?
- What does each `TaskPhase` mean operationally?
- Which status/phase combinations are allowed?
- Which combinations are invalid?
- Which transitions are legal?
- Who or what is allowed to trigger each transition?
- What are the terminal states?
- What is the exact difference between `DONE + PENDING_REVIEW` and `DONE + COMPLETED`?
- Under what conditions can automatic verification promote a task to `COMPLETED`?
- How are synthetic tasks persisted and linked back to project scope?
- How are already-invalid tasks detected and repaired?

#### Acceptance Artifact

Phase 0 should end with a canonical contract in `context/architecture/ituv-task-state-machine-contract.md`.

This gap-matrix document should keep:

- the problem statement
- the technical overview
- the phased plan
- the Phase 0 checklist and deliverables
- a short summary of the most important invariants
- future fixes and out-of-scope backlog

This gap-matrix document should not become a second copy of the full state-machine contract tables. If the contract is duplicated across planning docs, it will drift.

### Phase 1: Restore Completion Integrity

#### Goal

Ensure no task becomes `COMPLETED` unless it has passed orchestration gates.

#### Changes

- Remove direct task completion from `RunMode.start()`.
- Make `RunMode` return execution outcome only.
- Reserve final status transitions for `WorkflowOrchestrator`.
- If execution succeeds, task should remain `RUNNING` or move to phase-specific review state.

#### Acceptance Criteria

- A successful `RunMode` execution does not directly mark a project task `COMPLETED`.
- `WorkflowOrchestrator` always decides terminal state.
- Validation is never skipped solely because executor pre-completed the task.

### Phase 2: Add Real ITUV Phase Progression

#### Goal

Make task phases part of control flow, not decoration.

#### Changes

Add explicit phase transitions:

1. `IMPLEMENT`
   - Execute coding work.
   - Capture changed files, tool usage, and execution record.
2. `TEST`
   - Run targeted tests first.
   - Fall back to broader suite only when needed.
3. `USE`
   - If a task has a `recipe`, execute or validate that recipe.
   - Record outputs and pass/fail state.
4. `VERIFY`
   - Evaluate acceptance criteria against test/use evidence.
5. `DONE`
   - Only reached after gates pass.

#### Acceptance Criteria

- `Task.phase` changes during execution.
- Failed tests keep task out of `DONE`.
- Missing required usage recipe evidence blocks completion when a recipe is defined.
- Acceptance criteria are evaluated before completion.

### Phase 3: Harden Validation

#### Goal

Stop passing tasks without evidence.

#### Changes

- Change `ValidationManager` to fail closed by default.
- Treat `pytest` missing as failure unless task explicitly opts out.
- Treat “no tests found” as failure unless task explicitly indicates no tests are required.
- Add structured validation result fields:
  - `tests_run`
  - `tests_passed`
  - `usage_checks_run`
  - `acceptance_checks`
  - `evidence`

#### Acceptance Criteria

- Validation returns machine-usable evidence, not just a summary string.
- Tasks without tests or other verification paths do not silently pass.

### Phase 4: Wire the USE Gate to Blueprint Recipes

#### Goal

Make blueprint recipes actually matter.

#### Changes

- Create a lightweight recipe runner that supports a narrow, safe recipe vocabulary.
- Start with support for:
  - shell command checks
  - HTTP checks
  - Python snippets only if already trusted/contained
- Map `Task.recipe` to a named blueprint recipe.
- Store recipe execution results in task execution history or validation evidence.

#### Acceptance Criteria

- A task with `recipe` references a known recipe.
- USE step produces pass/fail evidence.
- Missing recipe reference fails validation.

### Phase 5: Fix Task Resolution and Scheduling Ambiguity

#### Goal

Make project execution deterministic.

#### Changes

- In `RunMode.start()`, stop using global title fallback for project tasks.
- Require `task_id` for project-managed execution.
- In continuous mode, when `project_id` is provided, prefer DAG selection only.
- Limit synthetic `determine_next_step` behavior to explicit exploratory sessions.

### Phase 8: Typed Dependency Policy Semantics

#### Goal

Stop treating every dependency edge as if it means the same thing.

#### Problem

The current system stores dependencies as plain task IDs. That is enough for a weak scheduler and not enough for a strong one.

Without explicit edge policy, the scheduler can only guess:

- whether downstream work must wait for `COMPLETED`
- whether `PENDING_REVIEW` is enough
- whether a specific artifact should unlock work
- whether trusted auto-verification changes readiness

That guesswork should not live in ad hoc `if dep.status == ...` checks.

#### Changes

- Introduce explicit dependency policy semantics with conservative defaults.
- Support a backward-compatible shorthand where plain dependency IDs mean `completion_required`.
- Add typed edge support for:
  - `completion_required`
  - `review_ready_ok`
  - `artifact_ready`
- Keep `trusted_auto_verify` as a completion-promotion policy, not a dependency-edge type.
- Centralize dependency readiness evaluation in one scheduler helper.
- Add focused tests proving that:
  - `completion_required` does not unlock on `PENDING_REVIEW`
  - `review_ready_ok` does unlock on `PENDING_REVIEW`
  - existing blueprints preserve old meaning by default

#### Acceptance Criteria

- The contract explicitly defines dependency policy types and default semantics.
- Existing dependency syntax remains backward-compatible and conservative.
- Scheduler readiness logic is policy-driven rather than hard-coded to one global meaning.
- Review gating is preserved by default.
- Policy exceptions are explicit in blueprint/task data, not inferred.

## Suggested Execution Order

1. Define the state machine contract.
2. Fix completion bypass.
3. Make validation fail closed.
4. Add explicit ITUV phase transitions.
5. Wire recipe execution for USE.
6. Fix task resolution and continuous mode drift.
7. Add cycle detection on dependency validation.
8. Add typed dependency policy semantics.
9. Remove or repair stale workflow code.

That order is important. If the state machine contract and completion logic are still wrong, everything else is theater.

## Related Rationale

For dependency-library/tooling choices related to this plan, see:

- `context/rationale/dependency-library-evaluation.md`

That note captures the current adopt/defer/reject stance for:

- `networkx`
- `pydantic`
- `hypothesis`
- `transitions`
- TLA+/bridge tooling
- migration/runtime type-checking candidates

Use it to avoid re-litigating library choices from scratch while Phase 8 dependency-policy work is still settling.

#### Changes

- Add cycle detection in dependency validation during task create/update.
- Reject invalid dependency graphs before persisting broken tasks.
- Add tests for self-dependency, two-node cycle, and longer cycles.

#### Acceptance Criteria

- Invalid dependency graphs are rejected at creation/sync time.
- DAG build is no longer the first place cycles are discovered.

### Phase 7: Clean Up Stale Workflow Surfaces

#### Goal

Reduce misleading or broken entry points.

#### Changes

- Either refactor `dream_workflow.py` to current signatures or mark it deprecated.
- Audit any callers that still assume outdated constructor contracts.
- Keep one obvious orchestration path.

#### Acceptance Criteria

- No dead workflow entry points with broken constructor calls.
- Docs point to the real orchestration path.

## Suggested Execution Order

1. Fix completion bypass.
2. Make validation fail closed.
3. Add explicit ITUV phase transitions.
4. Wire recipe execution for USE.
5. Fix task resolution and continuous mode drift.
6. Add cycle detection on dependency validation.
7. Remove or repair stale workflow code.

That order is important. If the completion logic is still wrong, everything else is theater.

## Functional Definition Of “Good Enough”

The system should be considered functionally usable when all of the following are true:

- Blueprint tasks can be imported into a project.
- Dependencies are valid and DAG scheduling selects only ready tasks.
- RunMode executes only the intended task.
- A task cannot reach `COMPLETED` or `DONE` without passing TEST, USE when applicable, and VERIFY.
- Acceptance criteria are checked using explicit evidence.
- Validation failures are visible and block completion.
- Continuous mode stays inside project scope unless deliberately placed in exploration mode.

## Minimal Functional Pass vs Production Hardening

This plan is intentionally being executed in two layers:

1. **Minimal functional pass**
   - make the ITUV path real
   - remove bypasses
   - persist the right state
   - fail closed
   - prove the core path with focused tests

2. **Production hardening pass**
   - enforce legal transitions more strictly
   - harden concurrency and atomicity
   - improve migrations and repair paths
   - attach richer evidence to acceptance criteria
   - improve observability, retries, and recovery
   - repair stale broad tests and docs drift

That sequencing is deliberate. The current priority is to make the execution path honest before making it exhaustive.

### What “More Production Ready” Means By Phase

#### Phase 1: Completion Ownership

Minimal pass:
- `RunMode` cannot mark project tasks complete.
- The orchestrator owns terminal status decisions.

Production hardening:
- reject any unauthorized direct transition to `COMPLETED`
- audit all completion call sites
- require explicit reopen and audit semantics
- add stronger invalid-transition tests

#### Phase 2: ITUV State Persistence and Transitions

Minimal pass:
- persist `phase`
- expose a manager-level phase API
- move orchestrator through explicit ITUV phases

Production hardening:
- validate legal phase transitions
- record or expose phase transition history more explicitly
- add migration tests for old task rows
- handle interruption, restart, and resume semantics cleanly
- prevent invalid `status × phase` combinations from being persisted

#### Phase 3: Validation and Acceptance Evidence

Minimal pass:
- fail closed on missing `pytest`
- fail closed on no tests collected
- return structured evidence
- surface acceptance criteria and mark whether they are covered or unchecked

Production hardening:
- classify validation failures by type
- link individual acceptance criteria to concrete evidence artifacts
- support richer evaluator types than “tests passed”
- preserve validation artifacts durably
- distinguish “tests passed” from “criterion proved”

### Strategic Rule

Do not confuse “minimal” with “sloppy.”

Minimal means one canonical path, explicit invariants, focused tests, and no fake-success behavior. Hardening comes after that spine exists.

### Future Fixes / Junk Backlog

These items are not required to make the minimum plumbing functional, but they should stay on the radar because they are likely sources of future breakage or trust erosion.

- Task claim atomicity in project execution.
  - Task selection and task claim appear to be separate operations.
  - In a real multi-agent or concurrent executor path, that risks double-claiming the same task.
- Documentation drift in `README.md` and `architecture.md`.
  - The docs present orchestration maturity more confidently than the current code justifies.
  - Fix this after the plumbing is real, not before.
- Stale orchestration surfaces beyond the current plan scope.
  - `dream_workflow.py` is an obvious example, but likely not the only one.
  - Any alternate entry point with outdated constructor assumptions should be audited.
- Parser and blueprint test coverage.
  - Parser bugs are silent plan corruption bugs.
  - Blueprint import, update, and dependency resolution need stronger regression coverage.
- Continuous-mode synthetic task sprawl.
  - Persisting synthetic tasks is necessary, but not sufficient.
  - They will need pruning, deduplication, and operator review rules.
- Status/phase migration for pre-existing tasks.
  - Once stricter invariants are enforced, some existing stored tasks may already be invalid.
  - A migration or repair pass will probably be required.
- Potential sync/async misuse in orchestration paths.
  - Some current call sites deserve audit for incorrect async assumptions.
  - That class of bug is easy to miss and annoying to debug.
- TUI worktree module-resolution instability.
  - `uv run penguin` in the feature worktree currently fails with a Bun/OpenCode module-resolution error for `@opencode-ai/util/error`.
  - This appears to be a frontend/sidecar workspace issue, not the current backend ITUV refactor target.
  - Track it as a future fix unless backend testing becomes blocked on it.
- Stale workflow pytest coverage.
  - Some workflow tests currently patch GitManager internals that no longer exist, so they fail before exercising the current orchestration path.
  - This is test debt and should be repaired, but it is not a blocker for the current Phase 1 backend refactor.
- Dependencies are valid and DAG scheduling selects only ready tasks.
## Recommended First Ticket Set

1. Define and document the canonical task state machine contract.
2. Prevent `RunMode` from directly completing project tasks.
3. Refactor `WorkflowOrchestrator` into an explicit ITUV phase runner.
4. Harden `ValidationManager` to fail closed.
5. Implement minimal recipe execution for USE.
6. Remove ambiguous title fallback for project task resolution.
7. Add cycle detection during dependency validation.
8. Deprecate or repair `dream_workflow.py`.

### Better Evidence Models

- Structured acceptance-criteria evaluators.
- Artifact capture for screenshots, API responses, logs, or command output.
- Rich execution records linked to each ITUV phase.
- Formal artifact evidence contracts for `artifact_ready` dependency edges.

### Next Recommended Ordering

1. Add Hypothesis/property-based invariant testing for status/phase and dependency-policy semantics.
2. Define and implement the artifact evidence contract for `artifact_ready`.
3. Add human-friendly blueprint syntax for typed dependency policies after semantics are stable.

This order is deliberate:

- invariants first, so semantics are stress-tested before expanding capability
- artifact evidence second, so `artifact_ready` stops being a stub and becomes a real contract
- blueprint UX third, so authoring syntax does not ossify around unstable semantics

### Smarter Scheduling

- Make DAG selection phase-aware.
- Support parallel execution for `parallelizable` tasks.
- Use effort/value/risk as real scheduling inputs, not just stored metadata.

### Agent Routing

- Route by `agent_role` and `skills` to specialized sub-agents.
- Enforce tool restrictions using `required_tools`.
- Add reviewer/QA passes before final completion.

### Blueprint Quality Tooling

- Lint blueprint files before sync.
- Detect missing acceptance criteria or recipes.
- Detect orphan dependencies and duplicate blueprint IDs.

### Human Governance

- Approval checkpoints for risky tasks.
- PR gating tied to VERIFY evidence.
- Explicit reopen flow for failed or partially validated tasks.

## Potential User Stories

### Blueprint Author

- As a blueprint author, I want to define tasks, dependencies, acceptance criteria, and usage recipes in one document so that project execution can be driven from a single source of truth.

### Project Operator

- As a project operator, I want continuous mode to work only on ready tasks in a specific project so that autonomous execution does not drift into unrelated work.

### QA Owner

- As a QA owner, I want tasks to fail closed when tests, recipes, or acceptance evidence are missing so that “completed” actually means something.

### Implementer

- As an implementer, I want tasks to progress through Implement, Test, Use, and Verify phases with visible state transitions so that failures are diagnosable and work can be resumed cleanly.

### Reviewer

- As a reviewer, I want each completed task to include structured evidence from tests and usage checks so that I can approve outcomes instead of guessing.

### Maintainer

- As a maintainer, I want stale workflow entry points removed or repaired so that the codebase has one reliable execution path instead of several conflicting ones.

## Recommended First Ticket Set

1. Prevent `RunMode` from directly completing project tasks.
2. Refactor `WorkflowOrchestrator` into an explicit ITUV phase runner.
3. Harden `ValidationManager` to fail closed.
4. Implement minimal recipe execution for USE.
5. Remove ambiguous title fallback for project task resolution.
6. Add cycle detection during dependency validation.
7. Deprecate or repair `dream_workflow.py`.

## Final Note

The codebase is closer to “promising scaffolding” than “finished workflow engine”. The good news is that the missing pieces are mostly plumbing and control-flow enforcement, not a full architectural rewrite. The bad news is that until those gates are real, the system can lie about task completion.
