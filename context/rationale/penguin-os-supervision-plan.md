# Penguin OS Supervision Plan

## Purpose

Use the operating system's service manager to make Penguin reliable, persistent, and schedulable **without** rebuilding `systemd` inside Penguin.

This plan assumes:

- Penguin should become an **always-on local agent runtime**
- process supervision belongs to **`launchd` on macOS** and **`systemd --user` on Linux**
- Penguin should focus on **task execution, orchestration, memory, and project state**
- the first implementation should be **small, Darwin-friendly, and reversible**

## Executive Summary

Penguin already has most of the expensive pieces needed for long-running autonomy:

- autonomous execution via `penguin/run_mode.py`
- persistent project/task state via `penguin/project/manager.py`
- a reusable FastAPI app via `penguin/web/app.py`
- tool execution via `penguin/tools/tool_manager.py`
- memory providers and checkpointing
- an in-process routing primitive via `penguin/system/message_bus.py`

What Penguin is missing is not "a Python implementation of `systemd`". It is the **userland runtime shape**:

1. one foreground gateway process that can be supervised by the OS
2. a small daemon-oriented CLI surface
3. timer/path-triggered entrypoints for recurring or reactive work
4. a service topology that respects Penguin's current process boundaries

## Non-Goals

The following are explicitly out of scope for the first pass:

- reimplementing init-system features inside Penguin
- building a cross-process message bus before it is needed
- supporting system-wide root services as a default
- implementing a full job scheduler before basic timers are in place
- solving multi-workspace orchestration in the first milestone

## Current Leverage In The Codebase

### Already Useful

- `penguin/run_mode.py`
  - autonomous task execution
  - continuous mode
  - time limits
  - graceful shutdown hooks
  - event emission for UI/status updates

- `penguin/project/manager.py`
  - SQLite-backed persistent project/task state
  - dependency tracking and DAG scheduling primitives
  - resource constraints, task metadata, and lifecycle tracking

- `penguin/web/app.py`
  - reusable FastAPI app factory
  - singleton core creation
  - existing API/WebSocket/MCP extension points

- `penguin/tools/tool_manager.py`
  - centralized tool registry and lazy loading

- memory + checkpoints
  - durable context, retrieval, rollback, and branching already exist

### Architectural Constraint

- `penguin/system/message_bus.py` is **in-process**
- therefore the initial architecture should prefer:
  - **one main supervised Penguin runtime**
  - **timers and triggers that call into that runtime**
- it should avoid pretending multiple unrelated processes share a single in-memory bus

That constraint matters. Ignore it and the architecture gets fake fast.

## Design Principles

1. **OS owns process lifecycle**
   - start, stop, restart, crash recovery, logs, boot/login activation

2. **Penguin owns cognition and workflow**
   - decide what to do, execute tasks, track state, manage memory

3. **Single runtime first**
   - keep routing, core state, and tool inventory in one process until there is evidence to split

4. **Foreground service, supervised externally**
   - first daemon command should run in the foreground
   - backgrounding should be delegated to `launchd`/`systemd`

5. **Local-first security**
   - bind to `127.0.0.1`
   - run as the current user
   - no root requirement
   - constrain tools and budgets per task

6. **Per-workspace state remains durable**
   - projects, tasks, memories, and checkpoints survive restarts

## Proposed Runtime Shape

### Core Runtime

Introduce a daemon-oriented runtime concept with a command surface roughly like this:

```text
penguin daemon run
penguin daemon status
penguin daemon ping
penguin daemon run-next-task
penguin maintenance run
penguin service install
penguin service uninstall
```

These names are proposed, not yet implemented.

### Recommended First Runtime Mode

**One per-user Penguin gateway process**, supervised by the OS.

Responsibilities:

- start `create_app()` from `penguin/web/app.py`
- hold the reusable `PenguinCore`
- expose local API/WebSocket/MCP surfaces
- accept admin calls for health, status, and "run next task"
- centralize logging and lifecycle events

Suggested initial bind:

- `127.0.0.1`
- port `18789` for the daemon/gateway surface

Reason:
- keeps it off the public network by default
- avoids stepping on the current ad hoc port `8000` pattern
- aligns with the roadmap direction

## Recommended Capability Split

### What `launchd` / `systemd --user` should do

- keep Penguin running
- restart on crashes
- start it on login
- schedule recurring work
- watch paths or directories
- capture logs
- optionally provide socket activation later
- enforce basic runtime limits

### What Penguin should do

- select runnable project tasks
- execute tasks via Run Mode / orchestration
- checkpoint before risky work
- summarize and store memory
- expose status/admin endpoints
- run constrained tool workflows
- emit progress and telemetry

## Milestone Plan

### Milestone 0 — Normalize The Runtime Boundary

**Goal:** make Penguin runnable as a stable foreground service.

Deliverables:

- a daemon-style CLI command that runs **without auto-reload**
- explicit host/port/workspace arguments
- clean startup/shutdown behavior
- health/status endpoint
- predictable log output

Acceptance criteria:

- can run Penguin in the foreground from Terminal
- process exits cleanly on SIGINT/SIGTERM
- no development reload mode in service execution
- status can be queried locally

### Milestone 1 — Add OS Service Installation

**Goal:** let the OS supervise the gateway process.

Deliverables:

- `launchd` LaunchAgent install/uninstall support for macOS
- `systemd --user` service install/uninstall support for Linux
- generated unit/plist files stored in a predictable location
- documented environment variables and runtime paths

Acceptance criteria:

- `launchctl bootstrap` or `systemctl --user enable --now` starts the gateway
- service restarts after crash
- logs are readable from native OS tooling
- no root privileges required

### Milestone 2 — Add Scheduled Background Work

**Goal:** use timers instead of an internal scheduler for recurring jobs.

Initial scheduled jobs:

1. **Project runner**
   - find next unblocked task
   - execute it with bounded budgets and clear status updates

2. **Maintenance**
   - summarize recent sessions
   - back up memory/checkpoints
   - prune or compact stale state
   - optionally refresh indexes

Acceptance criteria:

- jobs run on schedule with OS timers
- failures are visible in logs
- jobs are idempotent enough to retry safely
- each job is bounded by time and workspace scope

### Milestone 3 — Add Reactive Triggers

**Goal:** let Penguin react to changes instead of only polling.

Examples:

- repo path changed
- inbox directory received a file
- webhook or local API event arrived
- diagnostics file crossed an alert threshold

Recommended implementation order:

- `launchd` `WatchPaths` / `QueueDirectories` on macOS
- `systemd` `.path` units on Linux
- later: webhook/socket activation for remote integrations

Acceptance criteria:

- repo or file changes can wake a bounded Penguin workflow
- duplicate triggers do not create runaway task storms
- trigger provenance is recorded in logs or task metadata

### Milestone 4 — Optional Multi-Instance Support

**Goal:** support more than one workspace/runtime when there is real demand.

This should wait until the single-runtime story is stable.

Possible future forms:

- one gateway per workspace
- one gateway with named workspace contexts
- systemd template units like `penguin-gateway@workspace.service`

Not first. Not until the boring parts work.

## Proposed Command Surface

These commands are intentionally small and boring:

### `penguin daemon run`

Runs Penguin in the foreground as a supervised service target.

Required behavior:

- no hot reload
- explicit host/port/workspace selection
- graceful shutdown
- machine-readable health/status available somewhere local

### `penguin daemon status`

Returns:

- PID if supervised or lockfile-backed
- port
- uptime
- configured workspace
- high-level health
- maybe current task / queue summary

### `penguin daemon run-next-task`

Purpose:

- fetch next runnable task from project state
- execute one bounded unit of work
- emit clear exit codes for timer-based supervision

This is likely the highest-value worker entrypoint.

### `penguin maintenance run`

Purpose:

- summarize recent conversation/task state
- persist durable notes/memory
- perform backup/cleanup/index maintenance
- remain safe to call from a timer

### `penguin service install`

Purpose:

- generate/install a LaunchAgent or `systemd --user` unit
- write environment and log path defaults
- print native follow-up commands if automatic install is not possible

## Data And Runtime Layout

Suggested runtime layout under the user's home directory:

```text
~/.penguin/
  runtime/
    penguin.pid
    penguin.sock            # optional later
    penguin.env             # generated or user-managed
  logs/
    gateway.log
    worker.log
  state/
    active-workspace.txt
  services/
    launchd/
    systemd-user/
```

Workspace-local durable state remains where Penguin already keeps it:

- `projects.db`
- memory storage
- checkpoints
- workspace context files

## Security And Reliability Guardrails

- run as the current user, not root
- bind to localhost by default
- keep remote exposure opt-in
- use task-level `allowed_tools` and budgets aggressively
- checkpoint before risky autonomous write-heavy flows
- prefer short timer-driven workers over infinite hidden loops
- keep admin surfaces local unless authentication is explicit

## Open Questions

These should be answered before implementation starts:

1. **Single global workspace or named workspaces?**
   - simplest first pass: one gateway, one configured workspace

2. **Should timers call the gateway API or invoke CLI workers directly?**
   - simplest first pass: CLI worker commands
   - cleaner long-term model: local admin endpoint on the gateway

3. **What is the canonical service port?**
   - suggested: `18789`
   - current ad hoc web server examples use `8000`

4. **Should the service expose the full web UI or just admin/API first?**
   - recommendation: admin/API first, UI second

5. **How much installation automation is worth it initially?**
   - recommendation: generate unit files first, automate install second

## Implementation Order Recommendation

If you want leverage instead of busywork, do this order:

1. `penguin daemon run`
2. local health/status endpoint
3. `launchd` LaunchAgent install path
4. `systemd --user` service parity
5. `penguin daemon run-next-task`
6. maintenance timer
7. repo/file trigger support
8. only then consider richer daemon UX

## Suggested First Success Metric

A strong first milestone is:

> "After login, Penguin starts automatically as a local user service, keeps its core warm, and every 15 minutes executes the next runnable project task for a configured workspace, with logs and restart safety handled by the OS."

That is already a meaningful platform shift.

## Recommendation

Start on macOS with:

- one **LaunchAgent**
- one **gateway process**
- one **project-runner timer**
- one **maintenance timer**

Then port the same topology to `systemd --user`.

That is the 80/20 path.
