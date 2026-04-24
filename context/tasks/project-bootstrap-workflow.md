# Project Bootstrap Workflow

## Purpose

This file defines a proposed high-leverage workflow for getting from a project spec or Blueprint to executable project work with minimal command ceremony.

The goal is simple:

- make project startup powerful
- make it easy to go from spec to execution
- keep the workflow honest by preserving dependency validation, ITUV/runtime truth, and clarification handling

This is a product/workflow design document, not an implementation commit.

## Core Idea

The current lower-level project/task commands are useful, but they expose a lot of internal plumbing to the user.

A stronger default workflow would be:

1. create or initialize a project from a Blueprint/spec
2. sync/import tasks automatically
3. start project execution against the ready frontier
4. surface clarification and lifecycle truth as execution progresses

## Proposed Commands

### 1. Project Initialization

Preferred command:

```bash
penguin project init "name" --blueprint ./name-blueprint.md
```

Possible variants:

```bash
penguin project init "name"
penguin project init "name" --blueprint ./name-blueprint.md --description "..."
penguin project init "name" --blueprint ./name-blueprint.md --workspace ./my-project
```

### Why `init` Instead of `create`
`create` usually implies “make the container.”

`init` can honestly mean:

- create the project
- optionally attach workspace context
- optionally import/sync a Blueprint
- validate and prepare the project for execution

That is a better semantic fit.

## Proposed Behavior for `project init`

If `--blueprint` is provided, the command should:

1. create the project
2. parse the Blueprint
3. sync Blueprint items into project tasks
4. validate dependency graph / cycle safety
5. report:
   - created project ID
   - imported/updated task counts
   - validation issues if any
   - whether the project is ready to start

### Important Rule
If Blueprint sync or validation fails, `project init` must fail honestly.

It must **not** create a half-truth UX where the user believes the project is ready when the imported work graph is invalid.

## 2. Project Start

Preferred command:

```bash
penguin project start <project-id-or-name>
```

Possible variants:

```bash
penguin project start "name"
penguin project start <project_id> --continuous
penguin project start <project_id> --time-limit 30
penguin project start <project_id> --max-tasks 5
penguin project start <project_id> --no-continuous
```

## Proposed Behavior for `project start`

This command should:

1. resolve the target project deterministically
2. validate that the project exists
3. ensure the project has executable work
4. begin execution from the ready frontier
5. use the current project/runtime truth path
   - no side-door bypass
   - no fake direct completion
   - no skipping clarification handling
6. surface:
   - task selected
   - current phase/status
   - clarification-needed states
   - completion / pending-review outcomes

### Name vs ID Resolution

Name-based UX is attractive, but ambiguous names are a trap.

Recommended rule:
- exact ID match always wins
- exact unique name match is allowed
- ambiguous name match fails and asks the user to specify the project ID

That keeps the nice UX without turning project selection into roulette.


## Canonical Contract Summary

This section is the current recommended mental model for how Blueprint, project bootstrap, project execution, and ITUV ownership should fit together.

### Blueprint Ownership

The Blueprint is a **declarative work specification**.
It should define:
- project/task metadata
- dependencies / DAG shape
- acceptance criteria
- recipes for the USE gate
- ITUV defaults and timeboxes
- routing hints / skills / required tools where relevant

The Blueprint should **not** be treated as the live execution engine.
Its job is to describe the work graph, not to execute it.

### PM-System Ownership

Once a Blueprint is imported, the source of truth should become the **project/task management system**.
That runtime/project state should own:
- projects
- tasks / subtasks
- dependencies
- readiness / frontier selection
- task status
- task phase
- clarification state
- artifacts / evidence / validation outputs

In other words:
- Blueprint declares the intended work graph
- the PM system holds the live operational truth

### `project init` Contract

`project init` should:
- create the project shell
- parse/import Blueprint or spec input
- sync tasks and dependencies into the PM system
- validate import honesty
- fail/rollback on malformed, empty, or invalid imports

`project init` should **not** start execution.

Mental model:
> Prepare the work graph.

### `project start` Contract

`project start` should:
- resolve an **existing project**
- inspect the ready frontier from PM-system state
- execute against the real project/runtime truth path
- preserve clarification / waiting / time-limit / no-ready-work truth
- use the stored project/task graph rather than reparsing the Blueprint

`project start` should be the **primary user-facing execution command** in the TUI.

Mental model:
> Run this existing project.

### `project run` Status

Current understanding after the audit:
- `project run` is historically broader and more ambiguous than `project start`
- the old CLI path appears to combine spec parsing, project creation, and a heavier orchestration/validation workflow
- that path is currently drifted enough that it should not be treated as the clean parity target for this PR

For this PR, `project run` should be treated as **legacy / deferred** unless and until it is repaired and redefined around a crisp cross-surface contract.

The current preferred product flow is:
1. `project init`
2. `project start`

### ITUV Ownership

ITUV should be understood as split across declaration and execution:
- Blueprint declares ITUV intent, defaults, recipes, and acceptance expectations
- the PM/runtime system enforces and records ITUV transitions in live execution

That means ITUV does **not** live only in the Blueprint.
It becomes meaningful when the project/task lifecycle is instantiated in the PM system and advanced through runtime execution.

### Recommended Product Flow

The cleanest user-facing story is:

1. author or choose a Blueprint/spec
2. run `project init`
3. inspect the created project/tasks if needed
4. run `project start`
5. observe clarification / waiting / review / completion truth from the runtime

This keeps import/bootstrap concerns separate from execution concerns and reduces command overlap.

### Implication for This PR

For the current PR, the highest-leverage target is:
- make `project init` excellent
- make `project start` excellent
- make web/API/TUI parity excellent around those two commands
- defer treating `project run` as a first-class user-facing command until its contract is repaired and made consistent

## Why This Workflow Matters

This workflow is compelling because it compresses a lot of power into a tiny command surface:

```bash
penguin project init "Auth Rewrite" --blueprint ./auth-rewrite.md
penguin project start "Auth Rewrite"
```

That is much closer to the real product story:

- take a spec
- create the work graph
- execute it truthfully
- surface blockers/clarifications
- move toward a verifiably finished result

This is far more compelling than forcing the user to manually stitch together every task command.

## Non-Negotiable Constraints

This workflow only works if it preserves system truth.

### Must Not Become a Side Door
The bootstrap workflow must not:
- bypass orchestration
- bypass validation
- bypass clarification handling
- bypass dependency validation
- bypass phase/status integrity

### Must Preserve Current Runtime Semantics
If a task would produce `waiting_input` in lower-level runtime execution, the bootstrap flow must preserve that outcome.

If a task would land in `pending_review`, the bootstrap flow must preserve that too.

A friendly command surface is good.  
A friendly lie is not.

## Must-Have Flags

### `project init`
Recommended initial flags:
- `--blueprint <PATH>`
- `--description <TEXT>`
- `--workspace <PATH>`

### `project start`
Recommended initial flags:
- `--continuous`
- `--time-limit <MIN>`
- `--max-tasks <N>`
- `--project-id <ID>` or equivalent explicit targeting if name resolution is ambiguous

## Nice-to-Have Later
Not required for the first version:

- `--dry-run`
  - show what would be imported or executed
- `--validate-only`
  - parse Blueprint and validate graph without starting
- `--resume`
  - resume project execution after interruption
- `--since <checkpoint>`
  - advanced restart/selection semantics
- `--watch`
  - live progress display mode

## Suggested Command Semantics

### `project init`
Return/report should include:
- project ID
- project name
- Blueprint path
- tasks created
- tasks updated
- dependency validation result
- ready-task count

### `project start`
Return/report should include:
- project ID
- selected execution mode
- first selected task
- whether execution completed, paused for clarification, or stopped
- summary of task outcomes

## Suggested Error Cases

### `project init`
Should fail clearly on:
- missing Blueprint file
- unsupported Blueprint parse shape
- invalid dependency graph
- duplicate/ambiguous import identifiers that cannot be resolved safely

### `project start`
Should fail clearly on:
- missing project
- ambiguous project name
- project with no tasks
- project with no ready tasks
- clarification-required state when running in a non-interactive context that cannot answer it

## Acceptance Criteria for a First Version

A first version of this workflow is good enough when:

- a user can initialize a project from a Blueprint with one command
- the system reports what was imported honestly
- a user can start project execution with one command
- execution respects the existing orchestrated runtime truth
- clarification and non-terminal states are surfaced honestly
- ambiguous name resolution does not silently pick the wrong project

## April 21, 2026 E2E Findings

### What Was Verified
- `POST /api/v1/projects/init` succeeds for a valid Blueprint and reports imported task counts plus `ready_tasks`.
- `POST /api/v1/projects/init` fails with `400` and rolls back for at least some real lint-error cases:
  - dependency cycles
  - duplicate task IDs
- `POST /api/v1/projects/start` precondition failures work on the web surface:
  - unknown project identifier returns `404`
  - project with no tasks returns `400`

### What Broke or Drifted
- The documented `penguin-web --host ... --port ...` examples are currently misleading for local verification.
  - In practice, the server entrypoint reads `HOST` / `PORT` from env in `penguin/web/server.py`.
  - Passing `--port 8080` still bound the server to port `9000` during E2E verification.
- Blueprint validation is currently weaker than this workflow doc implies.
  - A Blueprint with missing acceptance criteria only produced a warning, not a rollback.
  - That behavior may be acceptable, but it means “invalid Blueprint” currently means “lint errors,” not “any lint issue.”
- The parse/import path is still too permissive.
  - An intentionally broken/minimal Blueprint returned `200` and created an effectively empty project instead of failing and rolling back.
  - That violates the intended “fail honestly” bootstrap contract.
- Full success-path `project start` E2E is not currently deterministic in a live environment.
  - The route does call the real RunMode path.
  - But successful execution depends on real model/runtime behavior, so the HTTP call can hang until client timeout without a controlled provider or test-mode runtime.

### Interpretation
- `project init` is partially honest today, but not fully.
- `project start` is honestly wired into real runtime truth, but it still lacks a deterministic verification story for success-path web E2E.
- The web server docs and runtime contract have drifted on host/port invocation behavior.

### Surgical Fix Targets
- Tighten Blueprint bootstrap failure semantics so malformed / effectively empty imports fail and roll back.
- Clarify and/or fix `penguin-web` host/port CLI behavior so docs match runtime truth.
- Add a deterministic `project start` verification path that does not depend on an uncontrolled live model run.

## File-Level Fix Checklist

### Web Server CLI / Docs Truth

#### `penguin/web/server.py`
- [ ] Make `penguin-web --host <HOST> --port <PORT>` actually work, or explicitly remove/avoid pretending those flags exist.
- [ ] Keep env-based `HOST` / `PORT` overrides working.
- [ ] Ensure startup banner prints the true bound host/port.

#### `docs/docs/usage/web_interface.md`
- [ ] Update startup examples so they match the real server invocation contract.
- [ ] If env vars remain the source of truth, document that explicitly instead of implying CLI arg parsing.

#### `AGENTS.md`
- [ ] Note that current docs treat `9000` as the primary Penguin web server port.
- [ ] Note that local verification on alternate ports should currently prefer env vars (`HOST` / `PORT`) unless/until CLI flag parsing is fixed.

### Project Bootstrap Failure Semantics

#### `penguin/web/services/projects.py`
- [ ] Treat malformed / effectively empty Blueprint imports as honest bootstrap failures with rollback.
- [ ] Preserve current rollback behavior for lint-error cases like duplicate task IDs and dependency cycles.
- [ ] Decide and document whether warning-only Blueprints are allowed to initialize projects or should fail under stricter bootstrap rules.
- [ ] Keep response payloads explicit about why initialization failed.

#### `penguin/project/blueprint_parser.py`
- [ ] Check whether malformed frontmatter / underspecified Blueprint shapes are being parsed too permissively.
- [ ] Tighten parser or diagnostics so clearly broken Blueprint files do not silently degrade into empty successful imports.

#### `tests/` web/bootstrap coverage
- [ ] Add regression tests for malformed Blueprint rollback.
- [ ] Add regression tests for empty/no-task Blueprint rollback if that is the intended contract.
- [ ] Keep duplicate-ID and dependency-cycle rollback coverage.

### Deterministic `project start` Verification

#### `penguin/web/services/projects.py`
- [ ] Preserve current real RunMode wiring for actual execution.
- [ ] Consider a controlled verification seam for tests so success-path web checks do not depend on a live provider call.

#### `tests/` web/project-start coverage
- [x] Add deterministic tests for successful `project start` request/response shape with mocked or controlled runtime execution.
- [ ] Keep precondition coverage for missing project and no-task project failures.

## File-Level Implementation Checklist

### Completed Bootstrap / Runtime Hardening

#### `penguin/web/server.py`
- [x] Make `penguin-web --host <HOST> --port <PORT>` actually work
- [x] Keep env-based `HOST` / `PORT` overrides working
- [x] Ensure startup path resolves a truthful bound host/port configuration

#### `penguin/web/services/projects.py`
- [x] Treat malformed / effectively empty Blueprint imports as honest bootstrap failures with rollback
- [x] Preserve rollback behavior for lint-error cases like duplicate task IDs and dependency cycles
- [x] Keep response payloads explicit about why initialization failed
- [x] Preserve current real RunMode wiring for actual `project start` execution

#### `penguin/project/blueprint_parser.py`
- [x] Tighten malformed frontmatter / underspecified Blueprint shape handling
- [x] Reject clearly broken Blueprint roots, task collections, and task entries instead of degrading into empty successful imports

#### `tests/` bootstrap/runtime coverage
- [x] Add regression tests for malformed Blueprint rollback
- [x] Add regression tests for empty/no-task Blueprint rollback
- [x] Add deterministic tests for successful `project start` request/response shape with mocked or controlled runtime execution

### Completed TUI Bugfix Slice

#### `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
- [x] Move Penguin local/project command detection ahead of session creation in `submit()`
- [x] Stop creating a session for local/project commands when no `props.sessionID` or `sdk.sessionID` exists
- [x] Stop session navigation for local/project commands executed from home
- [x] Keep current chat/session behavior unchanged for real prompts
- [x] Keep command-history append behavior only as an intentional command-path choice
- [x] Resolve command directory from current app/workspace state or existing session, not from a freshly created session
- [x] Support both dashed and spaced forms:
  - [x] `/project-init <name> [--blueprint <path>]`
  - [x] `/project-start <project-id-or-name>`
  - [x] `/project init <name> [--blueprint <path>]`
  - [x] `/project start <project-id-or-name>`

#### `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/` helper module(s)
- [x] Extract one small parser/helper as the single source of truth for Penguin local/project command syntax
- [x] Avoid duplicating command parsing logic between prompt execution paths
- [x] Keep helper scope tight: classify command intent and parsed args only

#### `penguin-tui/packages/opencode/test/cli/tui/`
- [x] Add parser/submit regression tests for Penguin local/project commands
- [x] Assert home-screen local/project commands do **not** require session bootstrap
- [x] Assert home-screen local/project commands do **not** trigger session navigation
- [x] Assert both dashed and spaced forms parse equivalently

### Remaining Work For A Full Bootstrap/TUI PR

This branch is no longer just a kernel/runtime hardening slice. If the PR is going to claim that project bootstrap works for users, the TUI surface has to expose and prove the feature honestly.

#### `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
- [ ] Add first-class command palette/discoverability entries for project bootstrap actions instead of relying on hidden slash-command knowledge alone
- [ ] Ensure project command execution emits user-visible success/failure feedback that is explicit enough to be believable in normal use
- [ ] Decide whether project-command success should also refresh relevant project/session state in-place, not just show a toast

#### `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/penguin-local-command.ts`
- [ ] Keep project command parsing as the single source of truth for both slash submission and any command-palette/project-action entrypoint
- [ ] Avoid introducing duplicated syntax rules between prompt submit flow and palette actions
- [ ] If palette actions prefill prompts instead of directly executing, document that as an intentional UX choice

#### `penguin-tui/packages/opencode/test/cli/tui/`
- [ ] Assert project commands route to the correct backend endpoints from the real submit path
- [ ] Assert both dashed and spaced forms route equivalently through the submit path
- [ ] Assert success/failure feedback is surfaced for project init/start command execution
- [ ] Keep no-session-bootstrap and no-navigation guarantees intact while adding discoverability coverage

#### `docs/docs/usage/web_interface.md`
- [ ] Reconcile docs with the now-fixed `penguin-web --host/--port` CLI behavior
- [ ] Keep the `9000` default/runtime-port guidance explicit while making alternate-port testing guidance honest

#### `AGENTS.md`
- [ ] Reconcile the temporary “prefer env vars because CLI flags are inaccurate” note with the now-fixed server behavior
- [ ] Keep the warning that `9000` is Penguin's primary/default runtime port and should not be casually hijacked for ad hoc verification

#### Merged-Branch Verification
- [ ] Re-run the relevant TUI tests on the merged `project-bootstrap-workflow` branch
- [ ] Re-run `bun run typecheck` for `penguin-tui`
- [ ] Re-run targeted Python/web/bootstrap tests on the merged branch:
  - [ ] `pytest tests/test_web_server.py -q`
  - [ ] `pytest tests/test_blueprint_linter.py -q`
  - [ ] `pytest tests/api/test_web_routes_task_shapes.py -q`

### Next Phase: Full Web/API + TUI Parity Checklist

This is the remaining implementation map for a **full feature/system overhaul PR**.
The order matters. Backend parity comes before TUI parity, because the TUI cannot honestly expose commands that the web/API does not support.

#### Step 1A — Project Web/API Parity

##### `penguin/web/routes.py`
- [ ] Add a real web route for project create.
- [ ] Add a real web route for project delete.
- [ ] Add a real web route for project run.
- [ ] Keep existing project routes (`list`, `get`, `init`, `start`) aligned with the same request/response conventions.
- [ ] Ensure route naming and HTTP verbs are honest and resource-shaped where practical.

##### `penguin/web/services/projects.py`
- [ ] Extract or add service functions for project create/delete/run so route handlers stay thin.
- [ ] Keep project start on the real RunMode truth path.
- [ ] Make delete semantics explicit and safe.
- [ ] Make run semantics explicit instead of letting them remain fuzzy CLI-only behavior.
- [ ] Normalize success/error payload shape across create/init/start/run/delete.

##### project request/response schema location(s)
- [ ] Add or update request models for project create/delete/run.
- [ ] Keep response payloads explicit enough for TUI feedback.
- [ ] Avoid creating route-only ad hoc payloads that drift from service truth.

#### Step 1B — Task Web/API Parity

##### `penguin/web/routes.py`
- [ ] Add honest task routes for create/list/start/complete/delete if they are missing or incomplete.
- [ ] Keep task routes aligned with current task lifecycle truth (`status`, `phase`, review state, clarification where relevant).
- [ ] Prefer resource-shaped route conventions over scattered RPC-style naming where practical.

##### `penguin/web/services/tasks.py` or `penguin/web/services/projects.py`
- [ ] Put task business logic in services, not route bodies.
- [ ] Keep task start/complete semantics aligned with current project/task lifecycle rules.
- [ ] Ensure delete behavior is explicit and tested.
- [ ] Keep payload shapes consistent with the project/task APIs already exposed elsewhere.

##### task request/response schema location(s)
- [ ] Add or update request models for task create/start/complete/delete.
- [ ] Ensure list responses expose enough task truth for the TUI to render believable feedback.

#### Step 2 — Audit and Define `project run` vs `project start`

**Clarified framing:**
- The goal is **not** to make web/API or TUI intentionally weaker than the CLI.
- The goal is to achieve **true parity** across CLI, web/API, TUI, and Link where practical.
- `project start` is already a relatively clear contract: run an **existing project** through the current RunMode/project execution truth path.
- `project run` is the confusing one. The open question is **not** whether web/API should get it; web/API should. The question is whether `project run` should mean the **same thing everywhere**, and if so, what that thing exactly is.
- The current risk is semantic drift:
  - CLI `project run` still looks like a heavier orchestration/workflow macro involving spec parsing, task-by-task orchestration, validation, and PR creation.
  - The new web route currently behaves more like **spec/bootstrap + start**.
- That mismatch is not acceptable long-term if parity is the goal.

##### `penguin/cli/cli.py`
- [ ] Audit the exact current behavior of `project run` versus `project start`.
- [ ] Confirm whether `run` is currently a broader project/workflow macro while `start` is the RunMode execution path.
- [ ] Identify stale assumptions or overlapping semantics that would make the web/TUI/Link surface confusing.

##### `penguin/project/` runtime/orchestration files
- [ ] Trace which subsystems each command actually hits (`RunMode`, workflow orchestrator, spec parser, validation, task executor, git/PR path).
- [ ] Decide what the authoritative cross-surface contract should be for `project run`.
- [ ] If parity is the goal, either:
  - [ ] lift the web/API `project run` surface up to the real CLI/kernel behavior, or
  - [ ] intentionally simplify/redefine CLI `project run` so all surfaces converge on the same truth.
- [ ] Record the distinction and decision in this doc once confirmed.

##### Product / Surface Constraint
- [x] Keep `project start` as the primary user-facing execution UX in the TUI.
- [x] Keep `project run` out of the TUI for this PR while its cross-surface contract remains legacy/deferred.
- [x] Add provisional comments around the web/API `project run` route so it is not mistaken for the preferred TUI/product path.
- [ ] Do **not** ship two verbs with fuzzy overlap across surfaces. If both verbs exist, users and APIs must be able to rely on a crisp distinction.

#### Step 3 — Expand the TUI Surface to Match the Real Backend

##### `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
- [x] Add discoverable project commands for the backend-supported project surface, excluding deferred `project run`.
- [x] Keep `project start` as the primary user-facing execution UX.
- [x] Add discoverable task commands once task web/API parity exists.
- [x] Keep prefill-vs-direct-execution behavior intentional and consistent with upstream OpenCode patterns.
- [x] Ensure success/failure feedback is explicit enough to be believable for users.

##### `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/penguin-local-command.ts`
- [x] Extend the parser to cover all backend-supported project commands, excluding deferred `project run`.
- [x] Extend the parser to cover all backend-supported task commands.
- [x] Keep this file the single source of truth for slash command parsing and aliases.
- [x] Avoid drift between command palette entries and submit-path parsing.

#### Step 4 — Strong Backend + TUI Tests

##### `tests/api/`
- [ ] Add route/service coverage for project create/delete/run.
- [ ] Add route/service coverage for task create/list/start/complete/delete.
- [ ] Add deterministic tests for any non-trivial RunMode-backed project/task operation.
- [ ] Keep error/precondition coverage honest, especially for ambiguous identifiers and missing resources.

##### `penguin-tui/packages/opencode/test/cli/tui/`
- [ ] Add submit-path tests proving each exposed project command hits the correct backend endpoint.
- [ ] Add submit-path tests proving each exposed task command hits the correct backend endpoint.
- [ ] Keep no-session-bootstrap and no-navigation guarantees for local/project/task commands from home.
- [ ] Assert visible success/failure feedback for command execution.
- [ ] Keep both dashed and spaced aliases covered where supported.

#### Step 5 — Final Docs / Branch Verification / PR Readiness

##### `docs/docs/usage/web_interface.md`
- [ ] Reconcile the docs with the final web/API project/task command surface.
- [ ] Keep the `9000` default/runtime-port guidance explicit.

##### `AGENTS.md`
- [ ] Reconcile temporary notes with the now-fixed server CLI behavior.
- [ ] Keep the warning about not casually hijacking `9000` for ad hoc testing.

##### merged branch verification
- [ ] Re-run the relevant TUI tests on the merged `project-bootstrap-workflow` branch.
- [ ] Re-run `bun run typecheck` for `penguin-tui`.
- [ ] Re-run targeted Python/web/bootstrap/project/task tests on the merged branch.
- [ ] Open the PR only after the exposed TUI commands correspond to real backend support.

- `context/tasks/cli-surface-audit.md`
  - CLI surface drift and immediate correctness fixes
- `context/tasks/runtime-surface-audit-checklist.md`
  - broader surface-audit framing
- `context/tasks/surface-verification-checklist.md`
  - verification checklist for proving surfaces actually work
- `context/tasks/penguin-capability-bar.md`
  - higher-level quality bar for what “done” should mean

## Bottom Line

The point of `project init` + `project start` is not to hide complexity for its own sake.

The point is to expose the **right** complexity:

- specs become work graphs
- work graphs become executable projects
- execution remains truthful
- verification remains first-class

That is a much stronger workflow than a bag of disconnected commands.
