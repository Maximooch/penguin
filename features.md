# Coding Agent Feature Comparison

Docs and repositories checked: 2026-07-22.

This file compares Penguin with Claude Code, OpenAI Codex, OpenCode, Pi, and
Hermes Agent. Penguin is the local baseline. The purpose is to identify the
product bar Penguin should target, not to score products with a single winner.

Claims below distinguish built-in behavior from extensions and current Penguin
implementation from plans. These products change quickly; follow the linked
primary documentation before making a product decision from one row.

## Sources

- Penguin: [README](README.md), [architecture](architecture.md),
  [runtime events](docs/docs/system/runtime-events.md),
  [MCP](docs/docs/system/mcp.md), and
  [testing pyramid](context/tasks/testing-pyramid.md).
- Claude Code: [overview](https://code.claude.com/docs/en/overview),
  [desktop](https://code.claude.com/docs/en/desktop),
  [parallel agents](https://code.claude.com/docs/en/agents),
  [agent teams](https://code.claude.com/docs/en/agent-teams),
  [worktrees](https://code.claude.com/docs/en/worktrees), and
  [scheduled work](https://code.claude.com/docs/en/desktop-scheduled-tasks).
- OpenAI Codex: [overview](https://learn.chatgpt.com/docs),
  [CLI](https://learn.chatgpt.com/docs/codex/cli),
  [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
  [Goal mode](https://learn.chatgpt.com/docs/long-running-work),
  [worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees),
  [hooks](https://learn.chatgpt.com/docs/hooks), and
  [app server](https://learn.chatgpt.com/docs/app-server).
- OpenCode: [overview](https://opencode.ai/docs/),
  [agents](https://opencode.ai/docs/agents/),
  [permissions](https://opencode.ai/docs/permissions/),
  [skills](https://opencode.ai/docs/skills),
  [providers](https://opencode.ai/docs/providers), and
  [SDK](https://opencode.ai/docs/sdk/).
- Pi: [overview](https://pi.dev/docs/latest),
  [design principles](https://pi.dev/docs/latest/usage),
  [sessions](https://pi.dev/docs/latest/sessions),
  [compaction](https://pi.dev/docs/latest/compaction),
  [extensions](https://pi.dev/docs/latest/extensions),
  [providers](https://pi.dev/docs/latest/providers),
  [security](https://pi.dev/docs/latest/security), and the
  [Earendil Works move](https://pi.dev/news/2026/5/7/pi-has-a-new-home).
- Hermes Agent: [overview](https://hermes-agent.nousresearch.com/docs),
  [features](https://hermes-agent.nousresearch.com/docs/user-guide/features/overview/),
  [messaging](https://hermes-agent.nousresearch.com/docs/user-guide/messaging),
  [delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation),
  [memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/),
  [cron](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron),
  [checkpoints](https://hermes-agent.nousresearch.com/docs/user-guide/checkpoints-and-rollback),
  and [API server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/).

## What Changed Since The 2026-05-01 Snapshot

- Penguin reached `0.9.0` and added a canonical `RuntimeEvent` envelope, a
  SQLite-backed redacted event ledger with SSE reconnect/replay, OpenCode TUI
  compatibility improvements, per-run server logs, and durable session goals
  exposed through `/goal`, `/247`, web routes, and Run Mode. The repository also
  gained a bidirectional MCP surface, remote MCP transports, safer edit/tool
  execution, ordered batches/process foundations, browser-harness integration,
  and stronger provider lifecycle tests.
- Claude Code now documents worktree-backed parallel sessions and subagents,
  experimental agent teams with a shared task list and peer messaging, a richer
  desktop workspace, local scheduled tasks, cloud routines, and `/loop`.
- Codex now documents Goal mode across desktop, CLI, and IDE; scheduled tasks;
  plugins and deterministic hooks; Work mode; and a remote-capable app-server
  protocol in addition to its existing CLI, worktree, review, SDK, and MCP
  surfaces.
- OpenCode added the read-only Scout subagent for upstream dependency research.
  Its current docs describe Build/Plan plus General/Explore/Scout, fine-grained
  wildcard permissions, child-session navigation, on-demand skills, and 75+
  providers including local models.
- Pi moved to `earendil-works/pi` and the `@earendil-works` npm scope. It added
  clearer project-trust and containerization guidance plus direct llama.cpp
  router/model management while retaining its intentionally small built-in
  feature set.
- Hermes expanded beyond the earlier comparison with desktop and an
  OpenAI-compatible API server, opt-in filesystem checkpoints, background and
  nested delegation controls, external memory-provider plugins, durable message
  delivery, auditable cron executions, script-only cron jobs, and a much larger
  messaging-platform list.

The Link-managed inference and external-subscription routing visible in the
current Penguin working tree is still in development. It is noted here for
freshness but is not counted as a shipped Penguin capability in the matrix.

## Executive Snapshot

| Agent | Primary shape | Strongest documented differentiator | Closest Penguin relevance |
|---|---|---|---|
| Penguin | AGPL Python coding-agent runtime with TUI/CLI, web/API, Python embedding, Run Mode, projects/tasks, checkpoints, memory, MCP, browser tools, and multi-agent orchestration | Durable engineering state across interfaces: category-aware context budgeting, truthful task states, checkpoints, session goals, canonical runtime events, and replayable event history | Baseline. Penguin now has more of the runtime foundation than the old comparison credited; the gap has moved toward isolation, policies, skills, automation delivery, and product UX. |
| Claude Code | Commercial coding product across terminal, IDEs, desktop, web/cloud, Slack/CI, and Agent SDK | Broadest polished engineering workflow: parallel worktrees, subagents, experimental agent teams, desktop panes/preview/computer use, remote routines, hooks, skills, plugins, MCP, and cross-surface handoff | Reference for worktree lifecycle, permission UX, team-agent visibility, desktop workflow, and local-versus-cloud scheduling. |
| OpenAI Codex | OpenAI coding system across ChatGPT desktop/web, CLI, IDE, cloud, integrations, SDK, and app server | Unified local/hosted workflow with Goal mode, worktrees, scheduled tasks, subagents, built-in Git/review, hooks/plugins/skills, MCP, and a rich client protocol | Reference for goal UX, sandbox/approval policy, worktree isolation, model capability gating, Git/review UX, and embeddable protocol design. |
| OpenCode | MIT open-source coding agent with terminal, desktop, IDE, share/web, SDK/server, plugins, MCP, skills, and configurable agents | Small, legible agent and permission model over a polished terminal/server product; broad provider support and direct child-session inspection | Penguin already uses its TUI direction. Continue borrowing upstream-compatible UI contracts while keeping Penguin runtime semantics canonical. |
| Pi | MIT minimal terminal coding harness extended through TypeScript extensions, skills, packages, SDK, RPC, JSON events, and TUI components | Best small-core example: explicit JSONL session trees, compaction records, event contracts, hot-loadable extensions, packages, and an embeddable SDK | Reference for disciplined boundaries, structured compaction, project trust, extension hooks, and session/event formats. |
| Hermes Agent | MIT autonomous general agent spanning CLI/desktop, API, remote execution backends, messaging, memory, skills, cron, voice, MCP, and delegation | Long-running personal-agent product with a learning loop, platform-specific toolsets, broad delivery surfaces, durable automation records, and remote/container execution | Reference for execution-backend abstraction, delivery/recovery semantics, memory UX, platform-aware policies, and unattended operation. |

## Feature Matrix

| Capability | Penguin | Claude Code | OpenAI Codex | OpenCode | Pi | Hermes Agent |
|---|---|---|---|---|---|---|
| License / availability | AGPL-3.0-or-later; PyPI package; current project version `0.9.0` | Commercial Anthropic product; most surfaces require a Claude subscription or Console account | Commercial service; local Codex CLI/app-server components are Apache-2.0 open source | MIT open source; install script and major package managers | MIT open source; now `@earendil-works/pi-coding-agent` | MIT open source from Nous Research |
| Main interfaces | `penguin`/`ptui`, headless CLI, FastAPI REST/WebSocket/SSE, Python API, OpenCode-derived TUI sidecar, MCP host and server | Terminal, VS Code, JetBrains, desktop, web/cloud, Slack, CI/CD, Agent SDK; desktop includes terminal/editor/diff/preview/task/subagent panes | ChatGPT desktop and web, CLI TUI, IDE extension, cloud, GitHub/Slack/Linear, SDK, app server, MCP server, GitHub Action | Terminal TUI, desktop, IDE, web/share, JS/TS SDK, HTTP server, plugins | Terminal TUI, print, RPC, JSON event stream, SDK, custom TUI components | CLI, desktop, OpenAI-compatible API, browser chat, and 20+ messaging/home-automation adapters including Teams, LINE, QQ, ntfy, Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Email, and SMS |
| Coding tools | File read/write/diff, safe edit/apply-patch surfaces, shell/tests/search/analysis, ordered tool batches, background process foundation, browser automation, image artifacts, custom/MCP tools | Codebase reads/edits, shell, Git/PR, browser/computer use, CI review and triage | Reads/edits/runs/reviews/debugs; integrated terminal; Git diff/comment/stage/revert/commit/push/PR; image and browser capabilities by surface | Bash, edit/write/read, grep/glob/list, apply_patch, LSP, todo, web fetch/search, question, skill, custom and MCP tools | Four core tools by default (`read`, `bash`, `edit`, `write`); `grep`, `find`, and `ls` are available but not all enabled by default; extensions can add or replace tools | 60+ tools across terminal/files, web/browser, media, memory, skills, cron, clarification, code execution, delegation, home automation, messaging, and MCP |
| Planning / safe modes | Engine and Run Mode, task phases, stop/clarification states, permission engine, session goals, configurable limits; no polished first-class read-only Plan persona yet | Plan and permission modes, policy rules, hooks, custom agents, worktree isolation, sandbox/cloud controls | Plans and Goal mode, review workflow, permission profiles, approvals and sandbox controls, local/worktree/cloud modes | Build is full access; Plan asks before edits and bash by default rather than being strictly read-only; permissions allow/ask/deny per tool or pattern | No built-in plan mode, permission popups, or sandbox by design; project trust protects resource loading, while extensions/containers implement stronger policy | Todo/clarify/delegation, command approval and authorization, toolsets per platform, container backends, optional checkpoints |
| Multi-agent / delegation | Coordinator, `agent_id` routing, spawn/delegate/pause/resume, shared or isolated context, personas, MessageBus, Responses-style tool exposure | Subagents, background agents, agent view, worktree-isolated agents, and experimental teams with lead, shared tasks, mailboxes, dependencies, and peer messaging | Parallel subagents in Work mode and Codex; activity visible in desktop/CLI/IDE; custom agents and inherited policies | Build/Plan primary agents; General/Explore/Scout subagents; automatic or `@` invocation; child-session navigation; per-agent task permissions and step limits | No built-in subagents; official extension examples and the SDK can add them | Background `delegate_task`, parallel batches, separate terminal sessions, configurable concurrency/depth, opt-in orchestrator children, durable completion event routing |
| Sessions / goals / branching | Persistent sessions, checkpoints, rollback, branches, transcript replay, durable session goals with pause/resume/run/clear and optional token/time/iteration limits | Named/resumable sessions, auto memory, side-by-side desktop/web work, side chats, remote control/teleport, worktree sessions | Local transcripts/resume, app threads/projects, Goal mode with pause/resume/edit/clear, Local/Worktree/Cloud handoff, background worktrees | Parent/child sessions, undo/redo, share links, server-backed session APIs | Auto-saved JSONL trees with `/tree`, `/fork`, `/clone`, `/resume`, labels, branch summaries, HTML export/share | SQLite/FTS5 sessions, cross-session search, messaging session scopes, checkpoints and `/rollback` |
| Runtime events / replay | Versioned `penguin.runtime_event.v1` envelope; stable ids and scope/correlation metadata; redacted SQLite ledger; retention policy; SSE `Last-Event-ID` replay and explicit replay-gap events; OpenCode projection adapter | Hooks and SDK event streams; session/history surfaces; no comparable public append-only runtime ledger emphasized in overview docs | Rich streamed app-server events with approvals and conversation history; record/replay and hooks; local transcripts | Server event stream and SDK types; child sessions and share; internal hidden title/summary/compaction agents | Detailed agent/session event union over JSON and RPC; append-only JSONL entries; compaction/retry/queue/settled events | Durable delivery ledger for platform sends, cron execution database, stored background-delegation completion events, SQLite session state |
| Context management | Category-priority CWM with separate budgets, recency trimming, multimodal handling, scoped usage telemetry, and per-agent clamps; it trims and does not currently summarize/compact | Context management, `CLAUDE.md`, auto memory, skills, MCP context, subagent isolation | Compaction, prompt caching, token counting, project/thread boundaries, subagent isolation | Automatic hidden compaction plus title and summary agents; configurable small model | Explicit auto-compaction and branch summarization with structured entries, reserve/keep settings, custom compaction hooks, cumulative file tracking | Context compression, prompt caching, bounded memory injection, file/context references, session search |
| Long-term memory | Declarative and summary notes, file-backed context, SQLite plus FAISS/LanceDB/Chroma/file providers | `CLAUDE.md`, scoped auto memory, and persistent subagent memory | Memories, Chronicle, AGENTS.md, rules, skills, and project context | Rules/AGENTS.md, skills, sessions/share; no broad built-in memory store emphasized | Context files, skills, prompts, and session tree; intentionally no broad built-in memory service | Bounded agent-curated `MEMORY.md` and `USER.md`, FTS5 session search, plus one of eight optional external memory providers |
| Extensibility | Tool/plugin registries, custom tools, EventBus/MessageBus, model adapters, bidirectional MCP with local/remote transports, resources/prompts, runtime/control-plane tools; general Agent Skills remain planned | MCP, CLAUDE.md, commands, hooks, skills, plugins/marketplaces, custom agents, Agent SDK | MCP, AGENTS.md, rules, custom agents, skills, plugins, hooks, Codex SDK, app server, MCP server | MCP, plugins, custom tools, on-demand skills, agents, rules, commands, themes, keybinds, LSP, SDK/server | TypeScript extensions, Agent Skills, prompts, themes, packages, providers, SDK, RPC, JSON events, custom UI | Plugins, dynamic MCP toolsets, open-standard/self-created skills, context files, SOUL.md, toolsets, messaging gateway, OpenAI-compatible API |
| Provider / model support | OpenAI/Codex, Anthropic, OpenRouter, LiteLLM, Gemini and Ollama paths, runtime switching, model capability normalization, GPT-5.6 Codex reasoning support | Claude subscription/Console; terminal and VS Code also document third-party-provider support | OpenAI models through ChatGPT or API authentication; CLI currently presents GPT-5.6 Codex-family choices | AI SDK/Models.dev integration for 75+ providers, local models, custom OpenAI-compatible endpoints, Zen and Go catalogs | OAuth subscriptions for ChatGPT/Codex, Claude, Copilot, xAI and Radius; many API/cloud providers; custom endpoints; direct llama.cpp router management | Nous Portal, OpenRouter, OpenAI, and compatible endpoints; provider fallback/credential pools and broad portal catalog |
| Automation / background work | Run Mode, continuous tasks, SQLite projects/tasks, persisted MCP RunMode jobs, session goals, process runtime, durable event replay; session-goal run ownership and cancellation handles are still process-local | Cloud routines, desktop scheduled tasks, `/loop`, CI/GitHub triggers, Slack ingress, web long-running work, worktree options | Scheduled tasks in desktop/web, Goal mode, non-interactive CLI, GitHub Action, SDK, cloud/local/worktree execution | Headless `run`, server/SDK, GitHub/GitLab integrations and share; less of a built-in durable scheduler/control plane | Print/RPC/JSON/package automation; no built-in background bash | Full cron lifecycle, skill-backed jobs, script gates, no-agent watchdogs, delivery fan-out, execution history, `/background`, and terminal completion notifications |
| Execution environments / isolation | Local workspace/web server today; browser backends and MCP subprocesses; no first-class worktree/container/remote execution lifecycle | Local, automatic desktop worktrees, CLI/subagent worktrees, SSH and cloud environments; permissions and sandbox controls | Local, desktop worktree, cloud, remote app server, Windows sandbox; worktree UI is currently desktop-specific | Local project/worktree context, permissions, local/remote MCP and attachable server; custom tools run with host permissions | Local host permissions by default; project trust is not a sandbox; documented Gondolin, Docker, and OpenShell patterns | Local, Docker, SSH, Singularity, Modal, Daytona, and Vercel Sandbox backends with platform toolset controls |
| Evidence / reliability posture | Truthful terminal/non-terminal task states, clarification preservation, artifact evidence/recipes, ITUV MCP tools, runtime diagnostics, provider lifecycle/fault tests, replayable public events | Tests/lint/CI, review/PR workflows, hooks, task/subagent views, worktree isolation | Dedicated review workflow, terminal validation, Git diffs/comments, PR flow, hooks, Goal completion criteria | Tool results, todos, Plan/Build, shared sessions; workflow defines the proof bar | Excellent session/event/extension contracts and explicit security boundary; minimal opinionated completion policy | Checkpoints, session search, execution/delivery ledgers, approvals, memory scanning, cron history, RL trajectory export |

## Per-Agent Notes

### Penguin

Penguin's current strength is the runtime beneath the UI:

- `PenguinCore` is now a thinner compatibility/orchestration facade over focused
  `penguin.core_runtime` modules; `Engine` owns reasoning and tool execution.
- `ConversationManager`, `ProjectManager`, Run Mode, checkpoints, tasks, and the
  new session-goal runtime provide durable workflow state.
- The canonical runtime-event envelope and SQLite ledger provide normalized,
  redacted, reconnectable state for web/TUI consumers. This closes the previous
  comparison's top recommendation; the remaining work is coverage and product
  projection, not inventing the envelope.
- Penguin can both consume MCP servers and expose its own project, blueprint,
  Run Mode, ITUV, session, resource, and prompt surfaces over MCP. Remote
  Streamable HTTP and legacy SSE client transports are supported.
- The CWM's category-aware trimming is a real differentiator, but it should not
  be described as compaction: it does not create summary artifacts today.
- Recent reliability work includes safer edit contracts, ordered batches,
  process runtime foundations, native tool replay/adjacency handling,
  session-scoped usage, provider lifecycle coverage, and browser image artifact
  promotion.

The strategic bar remains truthful lifecycle state, explicit evidence,
resumability, and verification rather than autonomy that merely looks finished.

### Claude Code

Claude Code has the broadest documented team and desktop workflow:

- Desktop combines parallel worktree-isolated sessions with terminal, editor,
  diff, preview, task, subagent, computer-use, PR-monitoring, and Dispatch flows.
- CLI and custom subagents can also use worktrees. Experimental agent teams add
  a lead, independent contexts, a shared dependency-aware task list, and direct
  teammate messaging; their documented resumption/coordination limits matter.
- Scheduling is deliberately tiered: session-scoped `/loop`, local desktop
  tasks, and cloud routines with repositories, environments, connectors, API
  calls, and GitHub-event triggers.
- Skills, plugins, hooks, MCP, auto memory, `CLAUDE.md`, custom agents, and the
  Agent SDK form a coherent team-distribution story.

Penguin should copy the clarity of the isolation, scheduling, permissions, and
agent-visibility UX, not merely the number of surfaces.

### OpenAI Codex

Codex's product boundary is now wider than the old "app plus CLI" description:

- Goal mode is available across ChatGPT desktop, Codex CLI, and the IDE, with
  visible pause/resume/edit/clear controls and explicit completion criteria.
- Scheduled tasks run from web or desktop; local tasks can target the checkout
  or an isolated background worktree. Worktree creation/handoff itself is
  currently documented as a desktop feature.
- Current local releases expose subagent activity in desktop, CLI, and IDE and
  delegate when directly requested or when instructions/skills require it.
- Hooks are deterministic lifecycle scripts. Plugins package hooks and skills,
  while MCP, the SDK, app server, GitHub Action, and non-interactive mode cover
  progressively deeper integrations.
- The app server is especially relevant to Penguin: it is an explicit protocol
  for authentication, history, approvals, and streamed events, including a
  remote WebSocket TUI mode.

### OpenCode

OpenCode remains the cleanest direct TUI/server comparator:

- Build is the full-access primary agent. Plan asks for edits and bash by
  default; it is safer but not an absolute read-only boundary.
- General handles broad multi-step work, Explore handles read-only local code
  search, and the new Scout handles read-only external dependency research.
- Subagents create navigable child sessions. Agent configs can set prompts,
  models, modes, step limits, visibility, colors, and wildcard task/tool
  permissions.
- Skills load on demand from OpenCode, `.claude`, and `.agents` locations, and
  permissions can hide, deny, ask for, or allow individual skill patterns.
- Its typed SDK/server and 75+ provider catalog remain stronger public contracts
  than Penguin's current programmatic product story, even though Penguin's
  internal runtime semantics are now richer.

### Pi

Pi continues to make omission part of the design:

- It intentionally excludes built-in MCP, subagents, permission popups, Plan
  mode, todos, and background bash. Extensions/packages or external isolation
  are the prescribed solution.
- Sessions are append-only JSONL trees with branch, fork, clone, label,
  compaction, and branch-summary entries. JSON/RPC modes expose explicit queue,
  retry, compaction, tool, turn, and settled events.
- Extensions can intercept lifecycle/tool calls, replace compaction, register
  providers/tools/commands/UI, persist custom entries, and hot reload.
- Project trust only decides whether project resources may load; it is not a
  runtime sandbox. The docs explicitly recommend Gondolin, Docker, OpenShell,
  VMs, or containers for stronger boundaries.
- The Earendil move and direct llama.cpp model manager are notable operational
  changes, not a change to the small-core philosophy.

Pi is still the best comparator for structured compaction and a deliberately
small kernel, but Penguin should retain its own stronger durable task semantics.

### Hermes Agent

Hermes is less coding-specific and more complete as an always-on personal agent:

- Its messaging gateway spans more than 20 adapters and uses allowlists/pairing,
  per-platform capabilities/toolsets, session scopes, streaming activity, and a
  durable at-least-once delivery ledger.
- Cron supports create/update/pause/resume/run/remove, skills, toolset overrides,
  platform delivery, script gates, zero-token script-only jobs, and an execution
  database with honest terminal/unknown states.
- Delegation has background handles, persisted completion events, configurable
  concurrency and spawn depth, separate terminal sessions, and restricted leaf
  agents. Cron or background terminals are recommended when parent-turn
  durability matters.
- Memory is bounded and curated in `MEMORY.md`/`USER.md`, searchable through
  SQLite/FTS5, and extendable through one of eight external provider plugins.
- Opt-in shadow-git checkpoints, an OpenAI-compatible API, and multiple terminal
  backends round out a strong recovery and deployment story.

Hermes is the strongest reference here for delivery semantics and platform-aware
operation. Its breadth also shows why Penguin should keep coding reliability and
runtime truth as its center of gravity.

## Capability Gaps And Opportunities For Penguin

### Foundations That Are No Longer Gaps

- Canonical public runtime-event envelope with stable ids and normalized scope.
- Durable redacted event ledger with retention and reconnect/replay semantics.
- A real bidirectional MCP surface rather than only a future integration plan.
- Persisted session goals and TUI/API lifecycle controls.
- Stronger OpenCode-compatible TUI event/session/provider contracts.

### Highest-Leverage Remaining Gaps

1. **Execution-environment and worktree lifecycle**
   - Claude Code and Codex make isolated worktrees a visible product primitive;
     Hermes makes terminal backends explicit. Penguin still conflates much of
     the run lifecycle with one local workspace.

2. **Skills, plugins, and deterministic lifecycle hooks**
   - Every comparator now has an on-demand skill story. Penguin's MCP and tool
     registries are useful foundations, but the planned Agent Skills surface and
     policy hooks still need a coherent user-facing contract.

3. **Evidence-backed completion enforced by the runtime**
   - Penguin stores artifact evidence and preserves honest non-terminal states,
     but task type, acceptance criteria, tests, recipes, and verification
     evidence should determine when completion is allowed.

4. **Durable unattended control plane**
   - Event replay is durable, but session-goal ownership and some cancellation
     handles are process-local. Reconnectable runs need leases, recovery,
     cancellation semantics, delivery destinations, and auditable attempts.

5. **Unified policy and permission UX**
   - OpenCode's pattern permissions, Claude's policy/hooks, Codex profiles, Pi's
     explicit trust boundary, and Hermes toolsets all make risk visible. Penguin
     should expose comparable per-agent/per-tool/per-platform policy without
     scattering it across config and runtime code.

6. **Subagent product UX and isolation**
   - Backend primitives exist. Named roles, child-session navigation, live task
     visibility, concurrency/depth controls, worktree inheritance, cost/usage,
     cancellation, and review remain the user-facing gap.

7. **Messaging and automation delivery**
   - Claude and Hermes treat ingress, schedules, delivery, recovery, and history
     as one product. Penguin has web/API/MCP building blocks but no comparable
     platform delivery layer.

8. **Structured compaction alongside category trimming**
   - Penguin's CWM preserves priority and recency well. Pi demonstrates the
     complementary value of explicit summaries that record files, commands,
     errors, decisions, and abandoned branches for audit and resumption.

### Differentiators Penguin Can Own

- Python-first open runtime spanning TUI, CLI, web/API, MCP, and embedding.
- Category-aware context budgeting rather than only opaque summarization.
- Canonical runtime events plus durable replay as a shared UI/runtime boundary.
- Project/task/session-goal lifecycle with SQLite persistence and Run Mode.
- Checkpoints, rollback, branching, transcript replay, and explicit subagent ids.
- Bidirectional MCP exposing not just tools but project, Run Mode, ITUV, session,
  resource, and prompt surfaces.
- Reliability tests centered on provider faults, incomplete streams, native-tool
  adjacency, task truth, isolation, and retry/release behavior.
- A product identity centered on truthful completion and evidence rather than
  maximal autonomous breadth.

## Short Recommendations

1. Promote execution environments to first-class state and implement
   worktree-backed runs before adding more parallel-agent UI.
2. Extend the durable event foundation into a leased run/attempt control plane
   with restart recovery, cancellation, delivery, and audit history.
3. Ship Agent Skills with progressive disclosure and compatibility with
   `.agents/skills`, `.codex/skills`, and `.claude/skills` where practical; pair
   them with deterministic lifecycle/policy hooks.
4. Make task completion conditional on applicable tests, acceptance criteria,
   artifact evidence, and usage recipes.
5. Define one policy model for agents, tools, shell patterns, MCP tools, external
   directories, background work, and platform-specific toolsets.
6. Give subagents named roles, navigable child sessions, visible state and usage,
   concurrency/depth limits, cancellation, inherited policy, and worktree
   isolation.
7. Add structured compaction artifacts without replacing the CWM's
   category-priority trimming.
8. Build messaging/scheduled automation only after run leases and delivery
   semantics are durable enough to survive process restart.
