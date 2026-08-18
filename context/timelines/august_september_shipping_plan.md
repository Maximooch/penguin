# August–September Shipping Plan — Penguin

_Initial draft. Window: 2026-08-12 → 2026-09-12 (~4.5 weeks)._

This is the follow-on to `merged_april_shipping_timeline.md`. April built the
kernel and the capability surface (skills, MCP, image/browser, ITUV, project
truth, durable event ledger, TUI upstream, `/goal` + `/247`). August/September
should build the **userland** and close the two gaps `features.md` flags as
foundational: **execution isolation/worktrees** and the **always-on control
plane (daemon)**. It also adds the two product features that turn the `/goal`
substrate into long-running, budget-respecting autonomy: **24/7 mode** and a
**wallclock time budget** (`/time`).

---

## Planning Frame

**Window:** Aug 12 – Sep 12, 2026
**Cadence target:** one coherent theme per week, plus a hardening/closeout week
**Version target:** `0.10.x` → `1.0.0` (daemon is the 1.0 story)
**Launch pairing:** this window is the **pre-launch** build for the "Penguin is
an always-on runtime, not a CLI you invoke" positioning. Post-launch (Sep 12+)
is delivery/social and Link handshake on top of a persistent process.

---

## Executive Timeline

| Window | Theme | Primary Goal | Closes (features.md gap) |
|---|---|---|---|
| Aug 12–18 | Daemon / Gateway (Topology A) | `penguin daemon start/stop/status/logs` + launchd/systemd units | #4 durable control plane |
| Aug 19–25 | 24/7 + Time budget | durable goal loop + wallclock `/time` budget | /goal substrate → product |
| Aug 26–Sep 1 | CWM-v2 (cost/latency) | policy + cache-stable assembly + tool slimming | #8 structured compaction |
| Sep 2–8 | Execution isolation / worktrees | first-class run environments | #1 worktree lifecycle |
| Sep 9–12 | Hardening + closeout | reliability pass, API refresh, docs | cross-cutting |

Parallel/low-effort threads that can run alongside any week: dashboard v1
(observability on the existing event ledger), sub-agent v2 product UX, and the
skills packaging commands (`skill install/remove/create`).

---

## Detailed Plan

## Week 1 — Aug 12–18: Daemon / Gateway (the foundation)

**Why first:** every other "always-on" feature (24/7, cron, dashboard, Link
handshake) needs a persistent supervised process to attach to. This is the
single highest-leverage gap and the "systemd" of the SCAR story.

**Implement `Topology A` from `context/rationale/penguin-service-topology.md`:**
- `penguin daemon start|stop|status|logs --follow`
- Wrap the existing FastAPI app in a supervised process (PID + lockfile,
  single-instance guarantee)
- `launchd` LaunchAgent (`ai.penguin.gateway`) on macOS; `systemd --user`
  units on Linux
- local-only bind on `127.0.0.1:18789`, run as current user, no root
- one configured workspace for MVP

**Deliverables:** daemon CLI + unit templates + health/status endpoint + logs.
**Exit criteria:** `penguin daemon start` then `status` shows a healthy,
restartable process; survives crash; logs captured.

**Defer:** socket activation, multi-workspace, cross-process bus.

---

## Week 2 — Aug 19–25: 24/7 Mode + Wallclock Time Budget

**Why now:** `/goal` and `/247` already exist as session-scoped durable
objectives. What's missing is (a) a genuinely durable, bounded 24/7 loop and
(b) a **wallclock time budget** — the thing you described: "Hey Penguin, work on
this for 5 hours to optimize every bit of performance out of it."

**Current truth (verified):**
- `/goal` + `/247` implemented: `core_runtime/session_goal_store.py`,
  `session_goal_runtime.py`, `session_goal_facade.py`, `session_goals.py`
- `run_mode.py` has `time_limit`/`max_duration` in **minutes** for continuous
  mode — a wall-clock cap, but not a task-attached budget and not
  goal-scoped.

**Build:**
- **24/7 mode:** a durable goal loop that survives process restart (reloads
  active goal + progress from `session_goal_store` on daemon start), bounded by
  explicit limits — never an unbounded infinite loop. Expose lifecycle state
  (running/paused/cleared) through the daemon and TUI.
- **`/time <duration>` budget:** attach a wallclock budget (hours/minutes) to a
  goal or task. Penguin works autonomously and **self-optimizes within the
  budget** — iterating on performance/correctness until the wallclock is spent
  or the acceptance bar is met, whichever comes first. On budget exhaustion:
  emit an honest `time_budget_reached` status (reuse the existing
  `time_limit_reached` status pattern) with a summary of what was done and what
  remains.
- Reuse the durable event ledger so the loop's attempts are replayable and
  auditable.

**Exit criteria:** a `/goal` with `/time 5h` runs across a daemon restart,
spends the wallclock budget, and reports a truthful `time_budget_reached`
outcome with evidence; no infinite loop.

**Note:** this is the product differentiator — "budget-respecting autonomous
optimization" — and it's the natural consumer of the daemon from Week 1.

---

## Week 3 — Aug 26–Sep 1: CWM-v2 — cost/latency

**Why now:** the Modal/Kimi trace showed ~95k-token, ~$1.46 loops; CWM is
overfeeding the model. This is the highest measurable ROI lever.

**Start `CWM-v2` phased (from `context/tasks/CWM-v2.md`):**
- Phase 0: instrumentation/guardrails (make context behavior visible)
- Phase 1: `ContextPolicy` + ceiling (speed/balanced/coherence)
- Phase 2: cache-stable context epochs (keep repeated prefix byte-stable)
- Phase 3: aggressive tool-output slimming before summarization

**Defer to later:** optical encoding, retrieval/Context Graph bridge.

**Exit criteria (Phases 0–3):** measurable input-token reduction on a
representative long session with no task-performance regression; cache-hit
stability visible in telemetry.

---

## Week 4 — Sep 2–8: Execution Isolation / Worktrees

**Why now:** `features.md` #1 gap — every comparator has isolated run
environments as a visible primitive; Penguin conflates run lifecycle with one
local workspace.

**Build:**
- Promote execution environment to first-class state
- `git worktree`-backed runs: agent works in an isolated checkout, changes land
  as a reviewable unit
- Terminal/execution boundary (start with local worktree; SSH/Docker as
  stretch)
- Wire worktree isolation into sub-agent runs

**Defer:** Docker/containerized agent execution (April's `1.0.0`) unless a
specific need forces it; keep it Docker-*first* when it does land.

**Exit criteria:** a run executes in an isolated worktree with a clean handoff;
sub-agents inherit isolation.

---

## Week 5 — Sep 9–12: Hardening + Closeout

**Reliability pass 2** (from `todo.md`): property-based + stateful transition
tests for TaskStatus/TaskPhase, clarification lifecycle invariants.
**PenguinAPI surface refresh** (deferred since April): audit method contracts,
clarification parity, docs/examples.
**Docs alignment:** README/architecture reflect daemon + 24/7 + time budget
truth.

---

## Parallel / Low-Effort Threads

These can ride alongside any week and don't need a dedicated slot:
- **Dashboard v1** — trace/waterfall view over the existing event ledger
  (`penguin-dashboard-observability-plan.md`). Observability is the #1 agent
  complaint.
- **Sub-agent v2 product UX** — named roles, child-session navigation, usage,
  cancellation (`sub-agents-v2.md`); backend primitives already exist.
- **Skills packaging** — `skill install/remove/create` + auto-discovery
  (discovery/activation exist; packaging doesn't).

---

## Launch Pairing (before / after)

**Before launch (this window):**
- Daemon (foundation)
- 24/7 + `/time` budget (the "works while you sleep" story)
- CWM-v2 cost reduction (so long-running autonomy is affordable)
- Worktree isolation (the trust story)

**After launch (Sep 12+):**
- **Cron / scheduled + heartbeat execution** — needs the daemon; this is the
  natural next userland layer
- **Link handshake** — agents as first-class workspace participants; needs a
  persistent process to attach to
- **Messaging / delivery layer** — build the *framework*, not 20 adapters
  (SCAR doc); deliberately post-launch
- **Dashboard full observability** — traces/waterfall/metrics/artifacts
- **Structured compaction** (CWM-v2 Phases 4–7) — summaries alongside trimming

---

## Explicitly Deferred (again)

- **Formal verification / TLA+** beyond minimal support (`penguin_tla.md`) —
  you've decided; revisit only for specific concurrency hotspots
- **OAK multi-agent model / episode primitive** (`1.0.2/1.0.3`) — not needed to
  hit this window's goals
- **Full containerized agent execution** — Docker-first only when worktree
  isolation proves insufficient
- **20+ channel adapters** — build the framework, not the adapters

---

## Critical Path

1. **Aug 12–18: Daemon** — everything always-on depends on it. Miss it and
   24/7, cron, and Link handshake all slide.
2. **Aug 19–25: 24/7 + `/time`** — the product differentiator; consumes the
   daemon.
3. **Aug 26–Sep 1: CWM-v2** — makes long-running autonomy affordable; without
   it, 24/7 burns money.
4. **Sep 2–8: Worktrees** — the isolation/trust story.

---

## Shared Risks

| Risk | Where it bites | Mitigation |
|---|---|---|
| Daemon scope creep (multi-workspace, sockets) | Week 1 | Ship single-workspace Topology A only |
| 24/7 loop runs away / burns cost | Week 2 | Hard wallclock budget + restart-safe goal store + no unbounded loop |
| CWM-v2 too ambitious | Week 3 | Land Phases 0–3 only; defer optical/retrieval |
| Worktree rabbit hole | Week 4 | Local worktree first; Docker/SSH as stretch |
| Launch slips | Whole window | Compress scope before borrowing from health buffer |

---

## What To Cut First If Reality Bites

**Cut first**
1. Docker/SSH execution backends
2. Skills marketplace
3. Dashboard beyond a minimal trace view
4. Structured compaction (CWM-v2 Phases 4+)

**Do not cut first**
1. Daemon (foundation)
2. 24/7 + `/time` budget (the product story)
3. Worktree isolation (the trust story)
4. CWM-v2 Phases 0–3 (cost — funds everything else)

---

## Bottom Line

April built the kernel. This window builds the userland and the two product
features that make Penguin feel like a platform:

- **Daemon** → Penguin is infrastructure, not a command.
- **24/7 + `/time`** → Penguin works while you sleep, bounded by an honest
  wallclock budget.
- **CWM-v2** → that long-running work is affordable.
- **Worktrees** → that work is isolated and reviewable.

Deliver the daemon and the time-budget loop and the launch story writes itself:
*"Tell Penguin how long to spend, and it optimizes until the clock runs out —
then tells you exactly what it did and what's left."*
