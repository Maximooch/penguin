# background-agents Reference Review

Date: 2026-04-27

## Executive Take

`reference/background-agents` is a high-value reference for Penguin's next layer of maturity: durable background execution, sandbox lifecycle management, task spawning, automation triggers, and reliable event delivery.

Where `pi-mono` is most useful for sharpening Penguin's agent loop and runtime contracts, `background-agents` is more directly useful for Penguin's operating-system layer around agents: RunMode, project tasks, sub-agent execution, resumable sandboxes, artifacts, and automation.

The strategic lesson is simple: a serious coding agent is not just a chat loop. It needs a control plane, a data plane, lifecycle state machines, backpressure, recovery sweeps, idempotency, and artifact evidence. That is the stuff that keeps users from debugging ghosts at 2 a.m.

## What It Is

The system, branded in docs as Open-Inspect, is a cloud background coding-agent platform. Users send prompts, sessions execute remotely, and clients can disconnect/reconnect while the work continues.

The architecture is split into:

- **Clients**: web, Slack, and any HTTP/WebSocket client.
- **Control plane**: Cloudflare Workers + Durable Objects for session state, WebSocket fanout, auth, GitHub integration, sandbox orchestration, and automation scheduling.
- **Data plane**: remote sandboxes running a dev environment, OpenCode, and a bridge process that streams events back to the control plane.

Core session data includes messages, events, artifacts, participants, and sandbox state. Each session is treated as durable state rather than ephemeral chat output.

## High-Value Ideas For Penguin

### 1. Background Execution As A First-Class Mode

The central product idea is presence decoupling:

```text
User sends prompt -> session runs independently -> user checks results later
```

Penguin already has autonomous RunMode, task orchestration, sessions, and sub-agents. The missing leverage is making background execution feel like a native product surface rather than a long CLI response.

Recommendation for Penguin:

- Treat every autonomous run as a durable session/task with reconnectable status.
- Persist run state independently of any active client.
- Make TUI, web, CLI, and Python API clients projections of the same run state.
- Preserve non-terminal states like `waiting_input`, `running`, `stale`, `cancelled`, and `failed` without flattening them into fake success/failure.

### 2. Control Plane / Data Plane Separation

The repo's architecture cleanly separates orchestration from execution:

- Control plane manages state, routing, access, lifecycle, events, and scheduling.
- Data plane runs code in isolated sandboxes.

Penguin currently runs mostly as a local/runtime-oriented agent with web/TUI/API surfaces around it. As Penguin grows into cloud, team, or remote execution workflows, this separation becomes non-negotiable.

Recommendation for Penguin:

- Define a Penguin control-plane interface around sessions, tasks, events, artifacts, and lifecycle transitions.
- Treat local execution as one data-plane backend, not the only runtime shape.
- Keep sandbox/provider concerns behind an interface so local shell, Docker, Modal, Daytona, devcontainers, and future providers can fit the same lifecycle.

### 3. Explicit Sandbox Lifecycle State Machine

The shared types define a useful sandbox status vocabulary:

- `pending`
- `spawning`
- `connecting`
- `warming`
- `syncing`
- `ready`
- `running`
- `stale`
- `snapshotting`
- `stopped`
- `failed`

This is exactly the kind of lifecycle truth Penguin should expose instead of vague `running`/`done` blobs.

Recommendation for Penguin:

- Add or formalize an execution-environment lifecycle separate from task lifecycle.
- Do not conflate agent status, task status, sandbox status, and message status.
- Surface environment lifecycle in web/SSE/TUI so users know whether the agent is thinking, waiting for infra, syncing git, or actually executing.

Useful distinction:

```text
Task status:       created | active | waiting_input | completed | failed | cancelled
Agent status:      idle | thinking | tool_running | blocked | finished
Sandbox status:    pending | spawning | connecting | ready | running | stale | stopped | failed
Message status:    pending | processing | completed | failed
```

### 4. Pure Decision Functions For Lifecycle Logic

`sandbox/lifecycle/decisions.ts` is one of the best pieces of the reference. It pulls lifecycle decisions into pure functions for:

- circuit breaker evaluation
- spawn/resume/restore decisions
- inactivity timeout
- heartbeat staleness
- connecting timeout
- proactive warming
- execution timeout

This is boring in the best possible way. Boring state machines are testable. Untestable lifecycle spaghetti becomes production archaeology.

Recommendation for Penguin:

- Move RunMode/task/sub-agent lifecycle policy into pure decision functions.
- Unit-test lifecycle decisions without requiring a model call, shell, database, or web server.
- Keep side effects in managers/executors; keep policy as deterministic input/output logic.

Candidate Penguin modules:

- `execution/lifecycle/decisions.py`
- `execution/lifecycle/manager.py`
- `execution/lifecycle/types.py`

### 5. Spawn / Resume / Restore Semantics

The spawn decision logic supports several important paths:

- spawn a fresh sandbox
- resume a persistent stopped/stale sandbox
- restore from snapshot
- skip if already spawning/connecting
- wait if recently spawned but not connected
- respect cooldowns and in-memory spawn locks

Penguin's sub-agent system already has spawn/delegate/wait/cancel primitives, but they are more agent-centric than environment-centric. `background-agents` shows the operational substrate those tools need if Penguin supports durable background execution.

Recommendation for Penguin:

- Separate `spawn_sub_agent` from `spawn_execution_environment`.
- Track spawn depth, parent session, spawn source, and inherited context explicitly.
- Use cooldown and circuit-breaker policy to avoid runaway failed spawns.
- Prefer restore/resume paths over fresh setup when a durable environment exists.

### 6. Reliable Bridge Event Delivery

The sandbox bridge is operationally interesting. It:

- sends heartbeats
- buffers events while disconnected
- marks critical events with ack IDs
- resends unacknowledged critical events after reconnect
- keeps prompt tasks alive across WebSocket disconnects
- cancels only appropriate background tasks when the socket closes

This matters because long-running agent work often fails at the seams: dropped sockets, partial streams, duplicate events, orphaned prompts, or lost terminal states.

Recommendation for Penguin:

- Make critical runtime events idempotent and ackable.
- Assign stable event IDs for terminal and artifact events.
- Buffer and replay events on reconnect for web/TUI clients.
- Make client disconnect unrelated to task cancellation unless explicitly requested.

Critical events should include at least:

- task started
- tool started/completed/failed
- clarification needed/answered
- artifact created
- execution completed/failed/cancelled
- snapshot saved/restored

### 7. Child Task Tooling

The sandbox runtime exposes simple agent-facing tools:

- `spawn-task`
- `get-task-status`
- `cancel-task`

The UX is intentionally small: spawn returns immediately with a task ID; status can list all child tasks or inspect one; cancellation is explicit.

Penguin already has richer sub-agent tools, but the simplicity is the lesson. Agent-facing delegation APIs should be hard to misuse.

Recommendation for Penguin:

- Keep sub-agent/task tools minimal and durable-id based.
- Require child prompts to be self-contained unless explicit context sharing is enabled.
- Return actionable status summaries, not giant logs.
- Include artifacts and recent events in detail views.
- Enforce spawn depth and concurrency limits visibly.

### 8. Automation Scheduler With Recovery And Backpressure

The automation scheduler is a useful reference for Penguin's project/task automation future. It includes:

- scheduled and event-triggered runs
- concurrency checks
- idempotency/dedup keys
- skipped-run records
- orphaned-starting-run recovery
- execution-timeout recovery
- auto-pause after repeated failures
- manual trigger path

This is exactly the discipline Penguin needs if it grows recurring tasks, webhook-triggered agents, GitHub/Linear/Sentry workflows, or persistent project recipes.

Recommendation for Penguin:

- Add explicit automation-run records, not just generated tasks.
- Preserve skipped runs with reasons; do not silently ignore them.
- Use idempotency keys for webhook/event-triggered tasks.
- Add recovery sweeps for `starting` and `running` states.
- Auto-pause automations after repeated failures.

### 9. Artifacts As First-Class Evidence

The reference tracks artifacts like PRs, screenshots, previews, and branches. Status tools report artifacts directly.

Penguin already has artifact-evidence concepts in task records. This repo reinforces that artifacts should be part of the lifecycle contract, not a prose afterthought.

Recommendation for Penguin:

- Standardize artifact records across RunMode, project tasks, web routes, and Python API.
- Make final task completion require artifact evidence where applicable.
- Include branch/commit/test-output/PR/screenshot/log artifacts in task detail views.

### 10. Session Index vs Per-Session State

The architecture uses a shared index for lookup and per-session isolated state for high-volume events. The exact Cloudflare Durable Object implementation is not necessarily right for Penguin, but the split is sound.

Recommendation for Penguin:

- Keep a global/project-level index for sessions, tasks, automations, and artifacts.
- Keep high-volume event logs scoped per session/run.
- Build UI/API projections from those records rather than letting each surface invent state.

## Things Penguin Should Not Copy Blindly

### 1. Cloudflare/Modal Specificity

Cloudflare Durable Objects and Modal snapshots are implementation choices, not universal truths. Penguin should borrow the boundary design, not hardcode the platform assumptions.

Better abstraction:

```text
ControlPlaneStore
ExecutionProvider
EventStream
ArtifactStore
SecretProvider
GitProvider
```

### 2. OpenCode-Centric Runtime Coupling

The reference uses OpenCode as the agent running in the sandbox. Penguin already has its own core, model adapters, tool system, context manager, and multi-agent architecture. Use this repo for lifecycle and orchestration ideas, not as an argument to wrap everything around OpenCode semantics.

### 3. Infinite Concurrency Marketing

The docs mention effectively unlimited concurrency because the laptop is not the bottleneck. Real systems still need quotas, cost controls, rate limits, provider capacity limits, token budgets, repo locks, and abuse prevention.

Penguin should expose concurrency as a governed resource, not a vibes-based promise.

### 4. Security Surface Area

Background agents have a larger blast radius:

- repo credentials
- webhook payloads
- persistent sandboxes
- PR creation
- browser automation
- user/team access
- event injection
- secrets in automation context

The reference does include useful warnings, such as treating webhook payloads as untrusted data. Penguin should go further and make trust boundaries explicit in prompt construction and tool policy.

## Concrete Penguin Follow-Ups

1. Write `context/review/runtime-lifecycle-contract.md` defining task, agent, message, sandbox, and artifact lifecycle states.
2. Create pure lifecycle decision functions for RunMode and execution environments.
3. Add an execution-environment abstraction separate from the current local tool execution model.
4. Make event replay/ACK/idempotency part of Penguin's SSE/WebSocket runtime contract.
5. Add recovery sweeps for project tasks stuck in `starting`, `running`, or `waiting_input` beyond policy thresholds.
6. Add first-class automation-run records with skip/failure reasons and idempotency keys.
7. Review `spawn_sub_agent`, `delegate`, `wait_for_agents`, and `get_agent_status` against the simpler `spawn-task/get-task-status/cancel-task` UX.
8. Standardize artifact evidence across task DB, RunMode results, API responses, and TUI/web displays.
9. Define provider-neutral sandbox lifecycle states before adding any remote provider integration.
10. Add cost/concurrency budgets to background execution before users can accidentally mint a tiny cloud bill monster.

## Bottom Line

`background-agents` is a serious reference for turning Penguin from an intelligent coding runtime into a durable agent operations platform.

The highest-leverage takeaway is lifecycle discipline: separate task, agent, message, artifact, and sandbox state; make state transitions explicit; make event delivery reliable; make recovery automatic; and make every client consume the same truth.

Do not copy the cloud stack. Copy the contracts, the state machines, the recovery posture, and the paranoia. Especially the paranoia.
