    # Penguin → SCAR: The 80/20 Feature Parity Roadmap

**"Linux for AI Agents" — What It Takes to Get There**

Date: March 5, 2026

---

## Framing: What "Linux for AI Agents" Actually Means

Linux isn't a single application. It's a **kernel** (process scheduling, memory management, hardware abstraction) with a **userland** (systemd, coreutils, package managers) and an **ecosystem** (distros, desktop environments, cloud infrastructure).

The analogy maps directly:

| Linux Layer | SCAR Equivalent | Penguin Today | OpenClaw Today |
|---|---|---|---|
| **Kernel** | Agent runtime (reasoning loop, tool execution, state management) | ✅ Engine + ActionExecutor + ConversationManager | ✅ Pi Agent Core + embedded runner |
| **Process scheduler** | Multi-agent orchestration | ✅ MultiAgentCoordinator + MessageBus | ⚠️ LLM-mediated sessions_spawn |
| **Filesystem** | Persistent state / memory | ✅ SQLite ProjectManager + pluggable memory | ❌ File-based (JSONL + workspace .md) |
| **systemd** | Daemon / Gateway (always-on process manager) | ❌ Missing | ✅ Gateway on port 18789 |
| **Network stack** | Channel adapters (messaging, webhooks, APIs) | ⚠️ Web API + webhooks only | ✅ 20+ channels |
| **Package manager** | Skills / plugin marketplace | ⚠️ Tool registry exists, no marketplace | ✅ ClawHub + skill-creator |
| **/proc, sysfs** | Observability / dashboard | ⚠️ MessageBus telemetry exists, no UI | ✅ Control UI + WebSocket broadcast |
| **init scripts** | Workspace bootstrap (AGENTS.md, SOUL.md) | ❌ System prompts are config-level | ✅ Bootstrap files injected as context |
| **cron** | Scheduled / heartbeat execution | ❌ Missing | ✅ Full cron service + heartbeats |

**The 80/20 insight:** Penguin already has the better **kernel** (Engine, multi-agent, SQLite state, checkpoints, context window management). What's missing is the **userland** — the daemon, channels, scheduling, dashboard, and workspace conventions that make it an always-on runtime rather than a CLI tool you invoke.

---

## The Six Things That Matter (80% of value, 20% of effort)

### 1. Gateway / Daemon Process

**What OpenClaw has:** A single long-running Node.js process (Gateway) bound to port 18789 that:
- Accepts WebSocket RPC from CLI, UI, channel plugins, and device nodes
- Serves a Control UI SPA
- Dispatches inbound messages to agents
- Manages session lifecycle across restarts
- Hot-reloads config on file change

**What Penguin has:** FastAPI web server (`penguin-web`) with REST + WebSocket streaming. But it's an *application server*, not a *daemon*. No launchd/systemd integration, no background persistence, no multi-client coordination.

**The 20% effort build:**

```
penguin daemon start          # daemonize, bind to localhost:port
penguin daemon stop
penguin daemon status
penguin daemon logs --follow
```

Implementation:
- Wrap existing FastAPI server in a daemon process (Python `daemon` module or systemd user unit)
- Add a gateway layer that multiplexes: CLI connections, web UI, inbound webhooks, cron triggers
- WebSocket RPC protocol for CLI ↔ daemon communication (Penguin's EventBus/MessageBus already supports this pattern)
- Config hot-reload via filesystem watcher (watchdog library)
- PID file + lockfile for single-instance guarantee

**Effort estimate:** 1-2 weeks. The FastAPI server + WebSocket infrastructure already exists. Main work is daemonization, systemd/launchd unit generation, and the RPC multiplexer.

**Why it matters for SCAR:** Without a persistent daemon, Penguin is a tool you invoke. With one, it's infrastructure that runs. This is the single highest-leverage gap to close.

---

### 2. Channel Adapter Framework (Not 20 Channels — The Framework)

**What OpenClaw has:** 20+ channel monitors, each normalizing inbound messages into a common `InboundContext` format.

**What Penguin should NOT do:** Build 20 channel adapters. That's OpenClaw's moat and not worth competing on directly.

**What Penguin SHOULD do:** Build the **adapter interface** so channels can be plugged in, then ship 2-3 that matter:

```python
class ChannelAdapter(Protocol):
    """Base protocol for all channel adapters."""
    
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, message: OutboundMessage) -> SendResult: ...
    
    # Inbound messages are normalized and pushed to the daemon
    # via MessageBus.publish(channel_id, agent_id, message)

class WebhookAdapter(ChannelAdapter):
    """Generic webhook receiver — covers Slack, Discord, custom."""
    ...

class CLIAdapter(ChannelAdapter):
    """The existing CLI, now as a channel adapter."""
    ...
```

**Ship these three first:**
1. **CLI** (reframe existing CLI as a channel adapter connecting to the daemon)
2. **Webhook** (generic inbound webhook that covers Slack/Discord/custom integrations)
3. **MCP** (Model Context Protocol server — this is where the ecosystem is heading, and Google's `gws` CLI already supports it)

**Effort estimate:** 2-3 weeks for the framework + CLI adapter + webhook adapter. MCP adds another week.

**Why it matters for SCAR:** The channel framework is the "network stack" of the agent OS. You don't need 20 drivers at launch — you need the interface so the ecosystem can build them.

---

### 3. Cron / Heartbeat / Scheduled Execution

**What OpenClaw has:** Full CronService with:
- Cron expressions + stagger offsets to avoid thundering herd
- Isolated agent sessions per cron job
- Heartbeat polls (periodic agent check-ins)
- Delivery routing (channel, webhook, session)
- Run logs (per-job JSONL, auto-pruned)

**What Penguin has:** Nothing for scheduled execution. The Engine has `run_task()` for autonomous multi-step execution, but no scheduler.

**The 20% effort build:**

```python
class SchedulerService:
    """Lightweight cron + heartbeat for the Penguin daemon."""
    
    async def add_job(self, job: ScheduledJob) -> str: ...
    async def remove_job(self, job_id: str) -> None: ...
    async def list_jobs(self) -> List[ScheduledJob]: ...
    
    # Jobs are stored in SQLite (reuse ProjectManager's DB)
    # Execution creates an isolated Engine session
    # Results route through MessageBus

@dataclass
class ScheduledJob:
    id: str
    cron_expression: str        # or interval_seconds for heartbeats
    agent_id: str
    prompt: str                 # what to tell the agent
    delivery: DeliveryConfig    # where to send results
    timeout_seconds: int = 600
```

**Effort estimate:** 1-2 weeks. Use APScheduler or a minimal cron parser. The hard part (isolated agent sessions, result delivery) maps to existing Engine + MessageBus infrastructure.

**Why it matters for SCAR:** Cron/heartbeat is what turns an agent from "responds when asked" to "monitors, alerts, and acts autonomously." Atlas's entire heartbeat loop (inbox scan, calendar conflict detection, memory maintenance) is only possible because OpenClaw has this.

---

### 4. Workspace Bootstrap Convention (AGENTS.md / SOUL.md Equivalent)

**What OpenClaw has:** A workspace directory convention where bootstrap files are injected into the system prompt:
- `AGENTS.md` — operational instructions, memory rules, safety constraints
- `SOUL.md` — identity, principles, policies
- `TOOLS.md` — local environment notes
- `MEMORY.md` — dynamic session context
- `USER.md` — user profile

This is the "persona layer" that makes an OpenClaw agent feel like a specific assistant rather than a generic LLM.

**What Penguin has:** System prompts via `config.yml` and `Engine.system_prompt`. Agent persona configuration exists (`7.6-agent-persona-configuration` in DeepWiki). But there's no standardized workspace directory convention.

**The 20% effort build:**

Define a `.penguin/workspace/` convention:
```
.penguin/workspace/
├── SYSTEM.md          # Core identity and operational rules (≈ SOUL.md)
├── CONTEXT.md         # User/project context (≈ PROFILE.md + USER.md)
├── TOOLS.md           # Environment-specific tool notes
├── MEMORY.md          # Dynamic session memory
└── agents/
    ├── planner.md     # Planner persona overrides
    ├── implementer.md # Implementer persona overrides
    └── qa.md          # QA persona overrides
```

Implementation:
- On Engine startup, scan workspace directory and inject contents into system prompt
- Per-agent persona files override defaults for that agent_id
- `MEMORY.md` loads only for main sessions (same security pattern as Atlas)
- Hot-reload on file change (same watcher as config hot-reload)

**Effort estimate:** 3-5 days. Mostly convention + documentation + a file loader that feeds into existing system prompt assembly.

**Why it matters for SCAR:** This is the "distro" layer. Different workspace configurations create different agent personalities and capabilities. An OpenClaw user migrating to Penguin should be able to drop their SOUL.md equivalent into the workspace and get the same behavior with better infrastructure underneath.

---

### 5. Dashboard / Control UI

**What OpenClaw has:** Control UI SPA served directly from the Gateway — shows agents, sessions, cron jobs, channel status, and real-time agent activity via WebSocket.

**What Penguin has:** FastAPI web server with REST + WebSocket endpoints. The infrastructure for a dashboard exists (MessageBus telemetry, EventBus UI events), but there's no actual dashboard UI.

**The 20% effort build:**

Don't build a custom dashboard from scratch. Ship a minimal web UI that exposes:
1. **Agent status** — which agents are registered, their current state, last activity
2. **Session list** — active sessions, transcript viewer
3. **Task board** — ProjectManager tasks with status (maps to kanban)
4. **Telemetry stream** — real-time MessageBus events (token usage, tool calls, errors)
5. **Config editor** — edit `config.yml` through the UI

**Technology choice:** Single React/Preact page that connects via WebSocket to the daemon. Keep it simple — a single `.html` file with inline JS is fine for v1 (this is what OpenClaw's Control UI started as).

**Effort estimate:** 2-3 weeks for a functional v1. The data is already available via MessageBus/EventBus — the work is building the UI layer.

**Why it matters for SCAR:** Observability is the #1 complaint about agent systems. "What is my agent doing right now?" needs to be answerable from a browser, not by reading JSONL files.

---

### 6. Skills / Plugin Framework Formalization

**What OpenClaw has:** ClawHub marketplace, `SKILL.md` files with frontmatter metadata, `openclaw skills install/update/publish`, skill-creator tool, and 100+ community skills.

**What Penguin has:** ToolManager with declarative/dynamic tool registration. `register_tool()` exists. But no packaging convention, no discovery, no marketplace.

**The 20% effort build:**

Define a skill package format:
```
penguin-skill-example/
├── SKILL.md              # Description, capabilities, requirements
├── skill.yml             # Metadata (name, version, author, tools provided)
├── tools/
│   └── my_tool.py        # Tool implementations
└── requirements.txt      # Python dependencies (if any)
```

CLI surface:
```
penguin skill install <path-or-url>
penguin skill list
penguin skill remove <name>
penguin skill create <name>      # scaffold
```

Implementation:
- Skills are Python packages that register tools via a `register(tool_manager)` entry point
- `skill.yml` declares metadata for discovery
- Installation copies to `.penguin/skills/` and auto-registers on daemon startup
- No marketplace needed yet — GitHub repos + `pip install` is sufficient for v1

**Effort estimate:** 1-2 weeks. The ToolManager plugin architecture exists. Main work is the packaging convention, CLI commands, and auto-discovery on startup.

**Why it matters for SCAR:** This is the "package manager" of the agent OS. OpenClaw's skill ecosystem is a significant moat — Penguin doesn't need to match it at launch, but needs the framework so the ecosystem can grow.

---

## What to Deliberately Skip (The Other 80% of Effort)

These are things OpenClaw has that Penguin should NOT build in the 20% effort phase:

| Feature | OpenClaw | Why Skip |
|---|---|---|
| 20+ channel adapters | WhatsApp, Telegram, Signal, iMessage, etc. | Build the framework, not the adapters. Community can contribute. |
| Native device nodes | iOS, macOS, Android companion apps | Not relevant to SCAR positioning. |
| Voice wake / TTS | ElevenLabs integration, always-on speech | Nice-to-have, not core to agent runtime. |
| Canvas / A2UI | Agent-driven visual workspace | Interesting but tangential to core value. |
| Moltbook integration | AI-to-AI social network | Meme-tier, not strategic. |
| Pairing / device security | DM pairing codes, node keypairs | Only matters with multi-channel. Build when needed. |
| Live Canvas | Push/reset/eval/snapshot visual workspace | Future Link feature, not Penguin core. |

---

## Implementation Sequence

Ordered by dependency chain and leverage:

```
Phase 1: Foundation (Weeks 1-4)
├── 1a. Gateway/Daemon (Week 1-2)
│   └── Daemonize FastAPI, systemd/launchd units, PID management
├── 1b. Workspace Convention (Week 2-3)
│   └── .penguin/workspace/ directory, file loader, hot-reload
└── 1c. CLI-as-Channel (Week 3-4)
    └── Refactor CLI to connect to daemon via WebSocket RPC

Phase 2: Autonomy (Weeks 5-8)
├── 2a. Cron/Heartbeat Service (Week 5-6)
│   └── APScheduler + SQLite job store + MessageBus delivery
├── 2b. Channel Adapter Framework (Week 6-7)
│   └── Protocol definition + webhook adapter
└── 2c. Skill Package Format (Week 7-8)
    └── Convention, CLI commands, auto-discovery

Phase 3: Observability (Weeks 9-12)
├── 3a. Dashboard v1 (Week 9-11)
│   └── Single-page UI: agents, sessions, tasks, telemetry
├── 3b. MCP Server (Week 11-12)
│   └── Expose Penguin tools via Model Context Protocol
└── 3c. Documentation + Migration Guide (Week 12)
    └── "From OpenClaw to Penguin" guide
```

**Total: ~12 weeks of focused work to reach 80% feature parity on what matters.**

---

## The Business Model Layer

"Linux for AI Agents" needs a Red Hat, not just a kernel.

| Revenue Layer | Description | Timing |
|---|---|---|
| **Penguin (OSS, AGPL)** | The agent runtime kernel. Free forever. | Now |
| **Emperor Penguin Channels** | Managed Penguin instances with dedicated compute, guaranteed uptime, premium models | After daemon + channels ship |
| **Link (OSS core + paid features)** | Collaboration platform where agents + humans work together | Parallel development |
| **Penguin Enterprise** | SSO, audit logs, compliance, SLAs, dedicated support | When you have paying customers |
| **Skill Marketplace** | Revenue share on premium skills (30/70 split) | After skill ecosystem matures |

The key insight from OpenClaw's trajectory: **Steinberger left for OpenAI, and the project's governance is now uncertain.** This creates a window for a well-governed, well-architected alternative with a clear business model behind it.

---

## How This Maps to the "Scalable Cognitive Architecture Runtime" Vision

```
SCAR Layer Stack (bottom-up):

┌─────────────────────────────────────────────┐
│ Applications (Link, Emperor Penguin, custom) │ ← Revenue
├─────────────────────────────────────────────┤
│ Ecosystem (skills, channel adapters, MCP)    │ ← Community
├─────────────────────────────────────────────┤
│ Userland (daemon, cron, dashboard, workspace)│ ← Phase 1-3 above
├─────────────────────────────────────────────┤
│ Kernel (Engine, multi-agent, SQLite, memory) │ ← Penguin today
└─────────────────────────────────────────────┘
```

Penguin today is a solid kernel. The 80/20 roadmap above builds the userland. Link is the first application. Emperor Penguin channels are the first revenue stream. The skill marketplace is the flywheel.

The photonic MoE / RLVR research you're exploring (narrow-domain reasoning specialists as hot-swappable modules) maps to the kernel layer — these become specialized agent personas that the Engine can route to based on task type. That's a 12-24 month differentiator that no one else is building.

---

## Concrete First Commit

If you were starting tomorrow, the single highest-leverage first commit is:

```
penguin daemon start
```

Everything else (channels, cron, dashboard, skills) depends on having a persistent process to attach to. The daemon is the foundation.

Second commit: workspace convention (`.penguin/workspace/SYSTEM.md`). This is zero-dependency, pure convention, and immediately makes Penguin feel like a configurable agent runtime rather than a CLI tool.

Third commit: cron service. This is what turns "responds when asked" into "works while you sleep."

After those three, you have a credible "Scalable Cognitive Architecture Runtime" that can be pitched to the OpenClaw community as "same agent superpowers, better architecture underneath."
