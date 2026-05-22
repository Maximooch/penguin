# Core Refactor Phase 6: Project, Run, And Orchestration

## Objective

Repair and stabilize Penguin's project/run/orchestration tests with hermetic
boundaries, then use those tests to extract orchestration behavior out of
`PenguinCore` and legacy workflow glue.

The default suite should prove project and run state transitions without a real
repository, GitHub remote, provider credential, server process, Docker daemon,
or network connection.

## Scope

- RunMode and project workflow state transitions
- task creation, execution, pending review, completion, failure, cancellation
- fake git and fake GitHub boundaries
- runtime/provider fakes for project execution
- event bus behavior needed by project/run surfaces
- terminal ownership and pending-review semantics
- compatibility with existing public project/workflow APIs where reasonable

Do not make this phase a broad project manager rewrite. The goal is to create
trustworthy tests and extract orchestration behavior only where the contract is
clear.

## Boundary Model

Default tests should replace external systems with deterministic fakes:

- git: fake status, branch, diff, commit, and worktree responses
- GitHub: fake issue, PR, comment, and review responses
- runtime/provider: fake model outputs, tool calls, failures, and cancellations
- filesystem: temp project roots with explicit fixture files only
- event bus: in-memory capture of emitted events
- clock/IDs: deterministic values where ordering matters

If a test needs a real repo, network, or GitHub token, mark it opt-in and keep
it out of the default gate.

## ACBRA Flow

### Audit

- Inventory old Phase 1/project workflow tests and classify failures as stale
  expectations, real contract drift, or external dependency leakage.
- Map orchestration state machines across `penguin/project`,
  `penguin/orchestration`, `penguin/core.py`, and web/service callers.
- Identify tests that currently assume real git, gh, current working directory,
  global environment, or provider credentials.
- Record the public terminal state vocabulary and ownership rules.

### Characterize

Capture intended deterministic behavior:

- queued tasks become running only through the orchestration path
- running tasks can become pending review without being treated as completed
- pending-review terminal ownership is explicit
- completion, failure, and cancellation are mutually distinct
- retries do not reuse stale task/session state
- fake git/gh failures surface as structured orchestration errors
- project state survives reload through the expected storage boundary

### Build

Create focused state-machine and service tests before extraction.

Test groups:

- task lifecycle transitions
- pending-review ownership
- fake git boundary behavior
- fake GitHub boundary behavior
- run cancellation and failure paths
- event emission order and payload shape
- project/session isolation
- idempotent reload or resume behavior where supported

Prefer direct service or manager tests. Use in-process API clients only when
testing route integration, and keep routes thin.

### Refactor

Move orchestration decisions toward dedicated modules and services.

Likely targets:

- `penguin/orchestration/*` state and transition helpers
- `penguin/project/workflow_orchestrator.py`
- `penguin/web/services/*` for route-facing orchestration operations
- a future `penguin/core_runtime/run_runtime.py` only if `PenguinCore` still
  owns meaningful run/task decisions after service cleanup

`PenguinCore` should delegate project/run work and expose compatibility methods
without owning transition rules.

### Assault

Add edge-case coverage after the state machine is stable:

- transition attempts from every terminal state
- cancellation while a fake runtime is mid-stream
- GitHub failure after local task state changes
- duplicate task IDs or stale resume IDs
- project root changes between calls
- missing or corrupt project metadata
- randomized transition order where the state machine can support it

## Acceptance Criteria

- Default `pytest tests -q` remains deterministic and offline.
- Legacy project workflow tests are repaired, replaced, or explicitly marked
  opt-in when they depend on external systems.
- Git, GitHub, runtime, event, and filesystem boundaries are fakeable in tests.
- Pending-review terminal ownership is explicit in code and tests.
- Project/run transition rules do not live in `PenguinCore`.
- Routes remain thin; business logic lives in services/managers.

## Verification

Run targeted tests for each repaired cluster, then periodically run:

```bash
uv run --group dev pytest tests -q
python -m compileall penguin tests
git diff --check
```

Run targeted Ruff checks on new or meaningfully touched orchestration, project,
service, and test files.
