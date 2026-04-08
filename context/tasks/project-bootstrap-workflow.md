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

## Relationship to Other Files

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
