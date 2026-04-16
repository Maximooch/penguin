# CLI Refactor and Bootstrap Audit

## Purpose

This file defines the audit pass that should happen **before** deeper CLI ergonomics work,
project bootstrap workflow work, or any serious decomposition of `penguin/cli/cli.py`.

The goal is simple:
- understand the current CLI structure
- map the safest extraction seams
- identify the highest-leverage UX fixes
- sequence follow-up PRs without destabilizing working behavior

This is not a rewrite plan disguised as an audit.
It is the anti-chaos step that should happen before we start cutting up `cli.py`.

## Why This Audit Exists

The current CLI file is too large and too mixed in responsibility.

Observed state:
- `penguin/cli/cli.py` is ~4600 lines
- top-level callback, environment setup, root/workspace handling, project/task commands,
  runmode commands, formatting, and helper logic all live in one file
- project bootstrap improvements (`project init`, `project start`) will become harder and riskier
  if added directly into the current structure without a seam map first

This creates three risks:
1. **Behavioral drift** — new commands subtly break already-verified command paths
2. **Scope sprawl** — ergonomics fixes quietly turn into a giant CLI rewrite
3. **Review pain** — too many structural and semantic changes get mixed together

## Current Constraints

### Do Not Do First
- do not rewrite `cli.py` wholesale
- do not fold bootstrap workflow work into a broad refactor branch
- do not extract modules speculatively without tests
- do not change core RunMode / ITUV truth in the name of “nicer UX”

### Preserve
- current verified CLI surface truth
- current root/workspace normalization behavior
- active vs running wording corrections
- pending-review approval semantics
- clarification-related runtime truth

## Files To Audit

### Primary
- `penguin/cli/cli.py`
- `context/tasks/cli-interface-ergonomics-plan.md`
- `context/tasks/project-bootstrap-workflow.md`
- `context/tasks/cli-surface-audit.md`
- `context/tasks/todo.md`

### Secondary
- `penguin/run_mode.py`
- `penguin/engine.py`
- `penguin/project/manager.py`
- `penguin/web/routes.py`
- CLI-related tests under `tests/`

## Audit Findings

### Structural map
Current high-value landmarks in `penguin/cli/cli.py`:
- global Typer app setup around `cli.py:305`
- top-level callback / main entrypoint at `cli.py:831-980`
- global initialization helper at `cli.py:419-560`
- runmode dispatch helper at `cli.py:1234-1354`
- `project create` at `cli.py:2568-2606`
- `project list` at `cli.py:2609-2663`
- `task create` at `cli.py:2827-2868`
- `task list` at `cli.py:2871-2915`
- legacy/interactive `PenguinCLI` class at `cli.py:3096+`

### Current public-surface shape
- There is no dedicated runmode command group today.
- Runmode is exposed via top-level flags on `main_entry(...)`:
  - `--run`
  - `--247`
  - `--continuous`
- Project/task commands exist as Typer command groups, but bootstrap workflow commands do not yet exist.

### Confirmed pain points
#### 1. `project create --workspace` honesty gap is real
- `project create` exposes `--workspace` at `cli.py:2573-2575`
- implementation ignores it and relies on manager-controlled workspace behavior at `cli.py:2590-2593`
- this is a surface-contract lie, not just missing polish

#### 2. Execution root vs project workspace remains muddy
- top-level callback normalizes execution root/workspace before initialization
- project creation output prints only the resulting project workspace path
- users do not get a clear explanation of the difference between:
  - execution root
  - managed Penguin workspace
  - project workspace path

#### 3. Help/discoverability is still weaker than it should be
- runmode is hidden behind top-level flags instead of an obvious command group
- project/task commands exist, but the likely happy-path workflow is not obvious from the command surface

#### 4. Some command help text still carries stale semantics
- `task list` still advertises old status examples in its help text (`pending, running, completed, failed`) instead of the fuller current lifecycle vocabulary

#### 5. `project list` does N+1 task counting
- current implementation fetches task lists per project row to compute task counts
- this is not the highest-priority ergonomics problem, but it is a cleanup target once semantics are stable

## Known CLI Hotspots

From current inspection:
- `@app.callback(...)` / main entrypoint around `cli.py:831`
- `_handle_run_mode(...)` around `cli.py:1234`
- `project create` around `cli.py:2568`
- `project list` around `cli.py:2609`
- `task create` around `cli.py:2827`
- `task list` around `cli.py:2871`
- `PenguinCLI` class around `cli.py:3096`

These are likely seam candidates, but the audit should confirm what is actually safe.

## Audit Questions

### 1. Command Surface Questions
- What commands are truly public and actively supported today?
- Which documented commands are just design residue or compatibility scaffolding?
- Where are command semantics duplicated across top-level mode, project commands, and task commands?
- Which commands have hidden workspace/root assumptions?

### 2. Bootstrap Workflow Questions
- What should `penguin project init "name" --blueprint ./blueprint.md` actually do step-by-step?
- What should happen when Blueprint parse, sync, or diagnostics fail?
- How should project selection work for `project start <project-id|name>`?
- How should pending-review and clarification outcomes be surfaced in a high-level workflow command?

### 3. Decomposition Questions
- What helper logic can move safely without changing command behavior?
- Which rendering/printing logic is duplicated and worth extracting?
- Which parts of `cli.py` are tied to Typer decorators and should remain stable for now?
- Which environment/root/workspace helpers should be isolated first?

### 4. Testing Questions
- Which current tests already protect CLI behavior?
- What regression tests are missing for project creation location semantics?
- What tests are needed before extracting command helpers?
- What should be verified before adding bootstrap commands?

## Audit Deliverables

### Deliverable 1: CLI Structure Map
A short file section or companion note that identifies:
- command groups
- helper clusters
- initialization flow
- root/workspace semantics flow
- output/rendering helper opportunities

### Deliverable 2: Extraction Seam Map
Explicitly classify seams as:
- **Safe now**
- **Safe with tests first**
- **Leave alone for now**

### Deliverable 3: Bootstrap Workflow Contract
Define the minimum user-visible contract for:
- `project init`
- `project start`

This should be honest about:
- project creation location
- Blueprint validation/sync failures
- deterministic selection rules
- clarification / pending-review outcomes

### Deliverable 4: PR Sequence
Recommend the smallest safe order of follow-up work.

## Extraction Seam Map

These are not commands from God. They are the current best classification from the audit.

### Safe now
- project/task output formatting helpers
- status/phase wording helpers
- project/workspace path display helpers
- project selection resolver helper(s)
- argument-to-runtime normalization helpers that do not alter init order

### Safe with tests first
- project command bodies behind stable Typer decorators
- task command bodies behind stable Typer decorators
- shared command error/reporting helpers
- project/task list rendering helpers
- lightweight command-discoverability/help-text cleanup

### Leave alone for now
- `_initialize_core_components_globally(...)`
- top-level callback/init ordering in `main_entry(...)`
- root/workspace environment normalization
- `_handle_run_mode(...)`
- `PenguinCLI` interactive shell / streaming display machinery
- command-group registration structure itself

## Exact Scope For PR 1: Workspace Semantics + Honesty Fixes

### Goal
Fix the highest-value CLI surface lies without starting the broader bootstrap or decomposition work yet.

### In scope
1. Resolve the `project create --workspace` honesty gap
   - either honor the option for real
   - or remove/hide it until supported
2. Clarify execution root vs project workspace behavior
   - improve wording/output so users can predict where a project lives
3. Improve project creation output
   - distinguish execution root, managed workspace root, and resulting project workspace when relevant
4. Tighten stale task/project help text where it conflicts with current truth
   - especially lifecycle/status wording
5. Add regression tests for:
   - project creation location semantics
   - `--workspace` behavior (or explicit non-support)
   - create/list/help output truth on workspace semantics

### Explicitly out of scope
- `project init`
- `project start`
- broader bootstrap workflow behavior
- major `cli.py` extraction
- runmode command redesign
- large-scale help overhaul beyond direct truth fixes

### Acceptance criteria
- `project create --workspace` is no longer misleading
- users can tell the difference between execution root and project workspace from command output
- help text no longer teaches stale task lifecycle/status examples
- existing verified CLI behavior remains intact
- new regression tests protect the workspace/location contract

### Suggested implementation strategy
- keep Typer decorators where they are
- patch behavior inside the existing project command implementations first
- extract only tiny display/helper functions if needed for testability or output reuse
- do not touch top-level init order unless a test proves it is necessary

## Bootstrap Workflow Contract (Pre-Implementation)

### `penguin project init "name" --blueprint ./blueprint.md`
Minimum honest contract:
1. create or allocate the project
2. resolve workspace semantics honestly
3. parse the Blueprint
4. run Blueprint diagnostics / validation
5. sync/import tasks only if validation is acceptable
6. report:
   - project id
   - project workspace
   - Blueprint sync result
   - diagnostics/errors/warnings

If Blueprint parse or validation fails, the command must say so plainly. It must not imply that the project graph is ready when it is not.

### `penguin project start <project-id|name>`
Minimum honest contract:
1. resolve the project deterministically
2. refuse ambiguous name matches unless the user disambiguates
3. route into orchestrated runtime truth, not shortcuts
4. surface non-terminal outcomes honestly, including:
   - `waiting_input`
   - `pending_review`
   - blocked/no-ready-task conditions

## Recommended Implementation Order

### PR 1: Workspace semantics + honesty fixes
- resolve `project create --workspace` gap
- clarify execution root vs project workspace
- improve create output
- tighten stale task/project help wording
- add regression tests

### PR 2: Help/discoverability cleanup
- improve help text and examples
- improve project/task workflow discoverability
- tighten errors for ambiguous selection

### PR 3: Bootstrap workflow MVP
- `project init`
- `project start`
- deterministic selection
- truthful reporting for Blueprint and runtime outcomes

### PR 4: Safe decomposition
- extract low-risk helpers
- reduce duplication in rendering and command support logic
- keep tests ahead of movement

### PR 5: RunMode/loop ergonomics follow-on
- audit `--run`, `--247`, and `--continuous` in depth
- revisit loop ownership boundaries between `RunMode` and `Engine`

## Acceptance Criteria

This audit is complete when:
- `cli.py` has a documented structure/seam map
- bootstrap workflow commands have a clear contract before implementation
- `project create --workspace` is identified in the right PR bucket, not left vague
- extraction work is sequenced by risk instead of by emotional desire to rewrite the file
- required regression tests are listed before decomposition work starts

## Relationship To Existing Plans

- `context/tasks/cli-interface-ergonomics-plan.md`
  - defines the user-facing ergonomics goals
- `context/tasks/project-bootstrap-workflow.md`
  - defines the intended bootstrap workflow direction
- `context/tasks/cli-surface-audit.md`
  - captures earlier correctness issues and CLI truth fixes
- `context/tasks/todo.md`
  - tracks the follow-up PR sequence

## Bottom Line

The CLI absolutely needs decomposition.

But the next smart move is not “rewrite the blob.”
The next smart move is:
- map it
- define the seams
- fix the highest-value user lies first
- add bootstrap workflow on top of honest semantics
- then decompose safely

That is how you make the CLI usable again without turning it into a fresh pile of rubble.
