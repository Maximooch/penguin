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

### Current TUI Bugfix Scope

This checklist covers the current `penguin-tui` bug where local/project commands can
accidentally create and navigate into a new session when submitted from home.

This is intentionally narrower than the broader bootstrap workflow UX.
The immediate fix is:
- parse command intent before session creation
- execute local/project commands without chat/session bootstrap
- preserve current chat behavior for real prompts

### Files

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
- [ ] Assert project commands route to the correct backend endpoints
- [x] Assert both dashed and spaced forms parse equivalently

### Explicit Non-Goals For This Patch
- [x] Do **not** require command-palette discoverability in the same bugfix commit
- [x] Do **not** redesign project feedback/UI beyond current minimal success/error reporting
- [x] Do **not** broaden this into a general TUI command-architecture rewrite

### Acceptance Criteria For This TUI Slice
- [x] From home, `/project init ...` does not create a session
- [x] From home, `/project start ...` does not create a session
- [x] From home, `/settings`, `/config`, `/thinking`, and `/tool_details` do not create a session

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
