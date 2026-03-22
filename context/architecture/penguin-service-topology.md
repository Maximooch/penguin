# Penguin Service Topology

## Purpose

Define a practical service topology for Penguin that uses **`launchd` on macOS** and **`systemd --user` on Linux** to supervise Penguin's runtime, timers, and triggers.

This document is intentionally biased toward:

- Darwin-first development
- single-user local deployment
- one main runtime process
- timer/path-driven workers instead of an internal init system

## Recommended Topology

### Topology A — Single Gateway + Timers (Recommended First)

```text
                           ┌──────────────────────────────┐
                           │ launchd / systemd --user     │
                           │  - start on login            │
                           │  - restart on crash          │
                           │  - timers / path triggers    │
                           │  - log capture               │
                           └──────────────┬───────────────┘
                                          │
                           supervises     │
                                          ▼
                     ┌────────────────────────────────────┐
                     │ Penguin Gateway Service            │
                     │ `penguin daemon run`               │
                     │                                    │
                     │ - FastAPI app                      │
                     │ - PenguinCore                      │
                     │ - ToolManager                      │
                     │ - RunMode / orchestration entry    │
                     │ - local API / WS / MCP             │
                     │ - health + status                  │
                     └──────────────┬─────────────────────┘
                                    │
                    local admin/API │
                                    ▼
        ┌──────────────────────┬──────────────────────┬──────────────────────┐
        │ Project Runner Job   │ Maintenance Job      │ Optional Trigger Job  │
        │ run-next-task        │ summarize/backup     │ repo/file/webhook     │
        │ timer-driven         │ timer-driven         │ path/event-driven     │
        └──────────────────────┴──────────────────────┴──────────────────────┘

Durable state lives in workspace storage:
- `projects.db`
- memory provider data
- checkpoints / branches
- workspace context files
```

This topology matches Penguin's current architecture best because `MessageBus` is in-process and the core runtime is easiest to reason about when it stays in one supervised process.

## Why This Topology First

### Good fit for current code

- `RunMode` already supports autonomous execution
- `ProjectManager` already provides durable task state
- `create_app()` already provides a reusable web runtime
- `ToolManager` already centralizes tool execution
- memory and checkpoints already provide continuity

### Avoids premature complexity

It avoids:

- writing a fake init system in Python
- distributed coordination before there is a cross-process bus
- multiple long-lived Penguin processes fighting over shared state
- turning "service management" into a six-month yak shave

## Service Inventory

### 1. Gateway Service

**Responsibility**
- host the main Penguin runtime

**Suggested command**
```text
penguin daemon run --host 127.0.0.1 --port 18789 --workspace <workspace>
```

**Runs continuously**
- yes

**What it owns**
- FastAPI app
- `PenguinCore`
- shared tool registry
- local API/WebSocket/MCP surfaces
- health/status/admin actions

**What it should not own yet**
- complex cron-like scheduling logic
- multi-process orchestration semantics
- internet-facing exposure by default

### 2. Project Runner Job

**Responsibility**
- run the next unblocked task in a bounded way

**Suggested command**
```text
penguin daemon run-next-task --workspace <workspace>
```

**Runs continuously**
- no

**Trigger**
- timer

**Recommended schedule**
- every 15 minutes to start
- later configurable by workspace or project

**Behavior**
- load project state
- select next runnable task
- execute a bounded unit of work
- update task status
- emit logs and exit

### 3. Maintenance Job

**Responsibility**
- keep memory and state healthy

**Suggested command**
```text
penguin maintenance run --workspace <workspace>
```

**Runs continuously**
- no

**Trigger**
- timer

**Recommended schedule**
- nightly or every 6-24 hours

**Behavior**
- summarize recent activity
- back up memory/checkpoints
- prune/compact stale state
- optionally rebuild indexes

### 4. Repo / File Trigger Job (Optional)

**Responsibility**
- react to local state changes

**Suggested command**
```text
penguin daemon handle-trigger --workspace <workspace> --source repo-watch
```

**Trigger**
- path change, queue directory, or webhook

**Good uses**
- repo changed
- task inbox file dropped
- diagnostics output changed
- generated spec document arrived

### 5. Optional Socket-Activated Surface (Later)

This is a later optimization, not a phase-one requirement.

Possible future forms:

- `systemd --user` socket activation for the local API
- `launchd` socket dictionary for on-demand startup
- on-demand webhook listener for low-idle machines

Useful later. Ignore for MVP.

## Platform-Specific Topology

## macOS — `launchd` (Recommended First)

### Use a `LaunchAgent`, not a `LaunchDaemon`

Reason:
- Penguin should run as the logged-in user
- it should have access to that user's workspace and environment
- root/system services are unnecessary and riskier

### Recommended labels

```text
ai.penguin.gateway
ai.penguin.project-runner
ai.penguin.maintenance
ai.penguin.repo-watch
```

### Suggested LaunchAgent responsibilities

#### `ai.penguin.gateway.plist`

- `RunAtLoad = true`
- `KeepAlive = true`
- `ProgramArguments = [".../penguin", "daemon", "run", "--host", "127.0.0.1", "--port", "18789", "--workspace", "<workspace>"]`
- `WorkingDirectory = <workspace or repo root>`
- `StandardOutPath = ~/.penguin/logs/gateway.log`
- `StandardErrorPath = ~/.penguin/logs/gateway.log`

#### `ai.penguin.project-runner.plist`

Use either:

- `StartInterval = 900` for every 15 minutes
- or `StartCalendarInterval` for fixed times

Program:
```text
penguin daemon run-next-task --workspace <workspace>
```

#### `ai.penguin.maintenance.plist`

Use:
- `StartCalendarInterval` for nightly runs
- or a longer `StartInterval`

Program:
```text
penguin maintenance run --workspace <workspace>
```

#### `ai.penguin.repo-watch.plist` (optional)

Use:
- `WatchPaths`
- or `QueueDirectories`

Program:
```text
penguin daemon handle-trigger --workspace <workspace> --source repo-watch
```

### Native operator commands

```text
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.penguin.gateway.plist
launchctl kickstart -k gui/$(id -u)/ai.penguin.gateway
launchctl print gui/$(id -u)/ai.penguin.gateway
```

## Linux — `systemd --user`

### Use user services first

Reason:
- same trust model as macOS LaunchAgents
- no root requirement
- easier iteration
- clean timer/path/socket support

### Recommended units

```text
penguin-gateway.service
penguin-project-runner.service
penguin-project-runner.timer
penguin-maintenance.service
penguin-maintenance.timer
penguin-repo-watch.path
penguin-repo-watch.service
```

### Suggested unit roles

#### `penguin-gateway.service`

- `ExecStart=penguin daemon run --host 127.0.0.1 --port 18789 --workspace <workspace>`
- `Restart=on-failure`
- `WorkingDirectory=<workspace>`
- `EnvironmentFile=%h/.penguin/runtime/penguin.env`

#### `penguin-project-runner.service`

- one-shot task runner
- bounded execution
- clear exit code

#### `penguin-project-runner.timer`

- `OnBootSec=2min`
- `OnUnitActiveSec=15min`

#### `penguin-maintenance.service`

- one-shot maintenance task

#### `penguin-maintenance.timer`

- daily or twice-daily schedule

#### `penguin-repo-watch.path`

- watches repo or inbox paths
- triggers `penguin-repo-watch.service`

### Native operator commands

```text
systemctl --user daemon-reload
systemctl --user enable --now penguin-gateway.service
systemctl --user enable --now penguin-project-runner.timer
systemctl --user enable --now penguin-maintenance.timer
journalctl --user -u penguin-gateway.service -f
```

## Deployment Modes

### Mode 1 — Single Workspace Gateway (Recommended MVP)

One Penguin gateway process is bound to one configured workspace.

**Pros**
- simplest mental model
- easiest to debug
- matches current singleton/core assumptions better

**Cons**
- awkward if you want many active repos at once

### Mode 2 — Named Multi-Instance Services (Later)

Examples:

- `penguin-gateway@repo-a.service`
- `penguin-gateway@repo-b.service`

**Pros**
- clean workspace isolation
- good for heavy repo-specific agents

**Cons**
- more service files
- more CPU/RAM
- more complexity on macOS

### Mode 3 — One Gateway, Multiple Workspaces (Later)

One supervised runtime manages more than one workspace context.

**Pros**
- fewer processes
- centralized visibility

**Cons**
- more internal complexity
- more careful routing/state isolation required

Not for the first milestone.

## Use-Case Mapping

### Autonomous project foreman

**Topology**
- gateway + project runner timer

**Flow**
- timer fires
- Penguin loads project state
- finds next runnable task
- executes with Run Mode or orchestration
- updates status/checkpoint/memory

### Repo custodian

**Topology**
- gateway + repo watch trigger + optional maintenance timer

**Flow**
- file or git state changes
- Penguin reviews diffs and runs validations
- creates/updates tasks
- summarizes findings
- optionally applies small fixes

### Memory gardener

**Topology**
- gateway + maintenance timer

**Flow**
- summarize recent sessions
- back up memory/checkpoints
- compact or re-index state
- leave a morning summary for the user

### Local API / MCP appliance

**Topology**
- gateway only, optionally socket-activated later

**Flow**
- IDE or tool connects locally
- Penguin responds with a warm core and persistent state
- long-lived identity and memory become useful

### Incident / runbook bot

**Topology**
- gateway + path/webhook trigger + bounded worker

**Flow**
- alert/log/file arrives
- Penguin runs a constrained diagnosis task
- records findings and next steps
- optionally opens or updates project tasks

## Security And Reliability Policies

### Security defaults

- bind to `127.0.0.1`
- run as the current user
- do not require root
- keep remote access opt-in
- prefer explicit allowlists for autonomous tasks

### Reliability defaults

- one supervised gateway process
- timer-driven one-shot workers
- restart on failure
- structured logs where possible
- checkpoints before high-risk automated edits

### Resource policy ideas for Linux later

When using `systemd --user`, consider later:

- `MemoryMax=`
- `CPUQuota=`
- `ProtectSystem=`
- `PrivateTmp=`
- `NoNewPrivileges=true`

Good later. Not phase one.

## Suggested First Topology To Implement

If the goal is leverage instead of architecture fan fiction, start with exactly this:

1. `ai.penguin.gateway` LaunchAgent on macOS
2. `ai.penguin.project-runner` timer-like LaunchAgent every 15 minutes
3. `ai.penguin.maintenance` nightly LaunchAgent
4. local-only bind on `127.0.0.1:18789`
5. one configured workspace
6. no root
7. no cross-process bus fantasy

## Open Questions

1. Should worker jobs invoke CLI commands directly or call local admin endpoints?
2. What should the canonical workspace selection mechanism be?
3. Should the web UI be part of the first gateway or follow later?
4. Do you want one primary workspace or named service instances soon?
5. Which logs matter most: user-readable summaries, raw traces, or both?

## Recommendation

Implement **Topology A** first.

It is the cleanest match to Penguin's current code and the fastest path to real utility:

- OS handles uptime
- Penguin handles thinking
- timers handle recurrence
- workspace storage handles continuity

That is enough to make Penguin feel like a platform instead of a command.
