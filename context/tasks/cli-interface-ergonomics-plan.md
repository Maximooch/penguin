# CLI Improvements and Interface Ergonomics Plan

## Purpose

This file scopes a **follow-up PR/branch** for CLI improvements and interface ergonomics.

It is intentionally separate from the RunMode / Project / ITUV core-systems work.
That branch is about truth, lifecycle integrity, validation, and surface verification.
This file is about improving how users access those systems once the core behavior is stable enough to trust.

## Why This Is Separate

The current branch should stay focused on:
- core task/project/runtime correctness
- ITUV and validation integrity
- public-surface verification
- docs/checklists that describe current truth

This later CLI/interface work should focus on:
- clearer command semantics
- better defaults
- lower-friction workflows
- ergonomic project/bootstrap flows
- reducing user confusion around workspace/project/root behavior

That separation matters because a branch that mixes state-machine correctness with CLI redesign becomes harder to review, harder to reason about, and easier to destabilize.

## Scope

### In Scope
- CLI command semantics and user-facing behavior
- project/workspace/root ergonomics
- high-level project bootstrap workflows
- command naming cleanup and discoverability
- better alignment between CLI, web, and library surfaces where it is primarily an interface concern

### Out of Scope
- core RunMode/ITUV state-machine changes unless a CLI fix is blocked on them
- deep architectural rewrite of the orchestration system
- broad TUI redesign
- speculative UX work without a concrete verification target

## Current Interface Pain Points

### 1. `project create --workspace` is misleading
Observed behavior today:
- CLI prints the current execution root correctly
- project creation still places project workspace under Penguin's managed workspace root
- `--workspace` is exposed as an option but not actually honored by the current implementation

Why this matters:
- it creates a surface-contract lie
- users reasonably expect project creation in the current repo or requested workspace
- it makes project location semantics feel arbitrary

### 2. Execution root vs project workspace is conceptually muddy
Current user-visible concepts include:
- execution root
- workspace path
- project workspace path
- managed Penguin workspace

These are not consistently explained through the CLI.

### 3. Lower-level project/task commands are useful but not the strongest product story
The current CLI exposes primitives, but the higher-leverage workflow is:
- initialize project from Blueprint/spec
- validate and sync work graph
- start execution truthfully

That workflow is more powerful and easier to understand than stitching many task commands together manually.

### 4. CLI help surface can still be improved
The correctness issues were fixed, but discoverability and flow are still only decent, not great.

### 5. Surface parity is still uneven in places
CLI, web/API, and `PenguinAPI` now align better on truth, but not yet on ergonomics or workflow shape.

## Design Principles

### 1. Honest Defaults
If a command does something surprising, it should not pretend otherwise.

### 2. Current Working Directory Should Matter When It Is Safe
If the user runs a project command inside a repo/worktree, the CLI should strongly prefer behavior that feels local and predictable.

### 3. Name High-Level Commands Around User Intent
Examples:
- `init` = create + prepare + optionally import Blueprint
- `start` = begin execution of the project frontier

### 4. Do Not Introduce Friendly Lies
No command should imply:
- validation happened when it did not
- execution is local when it is not
- a project is ready when import/graph validation failed

### 5. Preserve Core Runtime Truth
All ergonomic improvements must still preserve:
- ITUV/runtime semantics
- clarification handling
- dependency validation
- phase/status integrity
- review/approval semantics

## Recommended Workstreams

### Workstream 1: Clarify Project Location and Workspace Semantics

#### Goal
Make it obvious where a project lives and ensure command options actually do what they say.

#### Candidate fixes
- make `project create --workspace <PATH>` actually set the project workspace
- if that is not implemented immediately, remove or hide the option until it is real
- improve project create output so it distinguishes:
  - execution root
  - managed Penguin workspace
  - project workspace
- document the default project workspace policy explicitly

#### Acceptance criteria
- user can predict where a created project will live
- `--workspace` is either honored or removed
- command output does not imply local project creation when using managed global workspace

### Workstream 2: Add High-Leverage Bootstrap Commands

#### Goal
Expose a better top-level project workflow.

#### Candidate commands
- `penguin project init "name" --blueprint ./blueprint.md`
- `penguin project start <project-id|name>`

This workstream should build on `context/tasks/project-bootstrap-workflow.md`.

#### Acceptance criteria
- project can be initialized from a Blueprint with one command
- import/validation failures are reported honestly
- project start uses orchestrated runtime truth, not shortcuts
- clarification and pending-review outcomes remain visible

### Workstream 3: Improve Command Discoverability and Help UX

#### Goal
Make the CLI easier to learn without reading internal docs.

#### Candidate improvements
- clearer grouping of project/task/workflow commands
- help text that reflects actual semantics and defaults
- examples for common workflows
- better errors for ambiguous project name selection

#### Acceptance criteria
- help output points users toward the likely happy path
- common mistakes produce actionable errors instead of generic failures

### Workstream 4: Reduce CLI Surface Duplication Safely

#### Goal
Reduce drift risk between Typer commands and interface handlers.

#### Candidate improvements
- shared rendering helpers
- shared project/task formatting logic
- shared status/phase wording helpers
- controlled extraction from `penguin/cli/cli.py`

#### Important constraint
This should be refactoring with tests, not a premature rewrite.

#### Acceptance criteria
- duplicated surface wording/formatting logic is reduced
- test coverage remains ahead of structural movement
- no user-visible regression in verified command behavior

### Workstream 5: Align CLI Workflow with Verified Surface Contracts

#### Goal
Use the verified CLI/web/runtime truth as the base contract for future command design.

#### Candidate focus areas
- project bootstrap workflow
- clarification-friendly project start flow
- consistent naming across CLI/web/API/library surfaces
- parity notes for `PenguinAPI`

## Priority Order

### Must Address Early
1. `project create --workspace` honesty gap
2. project workspace/location semantics
3. deterministic `project init` / `project start` command design

### Should Follow
4. help/discoverability improvements
5. safe CLI decomposition / shared helpers

### Nice Later
6. richer UX sugar and convenience flags
7. more advanced watch/resume flows

## Suggested PR Breakdown

### PR 1: Project workspace semantics
- honor or remove `--workspace`
- improve create output and docs
- add regression tests for project location behavior

### PR 2: Bootstrap workflow MVP
- `project init`
- `project start`
- honest import/validation/reporting

### PR 3: CLI ergonomics cleanup
- help text improvements
- ambiguity errors
- shared rendering/helpers

### PR 4: Optional deeper decomposition
- reduce `cli.py` size carefully
- extract safe shared modules

## Testing Strategy

This work should not rely on vibes.

Use:
- CLI scripted verification where possible
- focused regression tests for workspace/root semantics
- explicit project-create/init/start scenario tests
- cross-checks against `context/tasks/surface-verification-checklist.md`

Add new verification items for:
- project creation location semantics
- `--workspace` behavior
- `project init` success/failure paths
- `project start` deterministic selection and error behavior

## Relationship to Other Files

- `context/tasks/cli-surface-audit.md`
  - tracks earlier CLI correctness issues and decomposition seams
- `context/tasks/project-bootstrap-workflow.md`
  - defines the high-level target workflow for init/start
- `context/tasks/surface-verification-checklist.md`
  - records what public surfaces have actually been verified
- `context/tasks/runmode-project-ituv-checklist.md`
  - current branch scope and wrap-up criteria

## Bottom Line

The next CLI/interface PR should make Penguin easier to use **without** blurring the runtime truth that the current branch worked to restore.

That means:
- no hidden behavior
- no fake local-workspace assumptions
- no command options that lie
- no workflow sugar that bypasses orchestration truth

The best interface work makes the right thing easier, not fuzzier.
