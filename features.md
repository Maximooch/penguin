# Coding Agent Feature Comparison

Docs checked: 2026-05-01.

This file compares Penguin with the external coding-agent systems requested:
Claude Code, OpenAI Codex, OpenCode, Pi, and Hermes Agent. Penguin is included
as the local baseline because this repo is trying to decide what feature bar and
product shape Penguin should target.

## Sources

- Penguin local docs: [README.md](README.md), [architecture.md](architecture.md),
  [docs/docs](docs/docs), and selected files under [context/](context).
- Claude Code: <https://code.claude.com/docs/en/overview>
- OpenAI Codex: <https://developers.openai.com/codex>
- OpenCode: <https://opencode.ai/docs/>
- Pi: <https://pi.dev/docs/latest>
- Hermes Agent: <https://hermes-agent.nousresearch.com/docs>

## Executive Snapshot

| Agent | Primary shape | Strongest documented differentiator | Closest Penguin relevance |
|---|---|---|---|
| Penguin | Open-source coding-agent runtime with CLI/TUI, web/API, Python API, Run Mode, projects/tasks, checkpoints, memory, and multi-agent orchestration | Durable stateful engineering workflows: sessions, checkpoints, context-window budgeting, task/project lifecycle, sub-agents, and shared runtime across interfaces | Baseline system. The main opportunity is making every surface expose the same truthful runtime state and evidence-backed completion semantics. |
| Claude Code | Commercial agentic coding tool across terminal, IDE, desktop, browser, mobile-adjacent remote control, Slack, CI, and SDK | Most complete product surface and team workflow story: multi-surface continuity, routines/scheduled work, Slack/CI, MCP, hooks, skills, custom agents, and Agent SDK | Target product breadth and workflow polish, especially recurring tasks, remote control, chat/CI integrations, and cross-surface continuity. |
| OpenAI Codex | OpenAI coding agent across app, CLI, IDE extension, web, integrations, and automation | Strong local/app workflow: parallel threads, worktrees, built-in Git, integrated terminal, cloud/local/worktree modes, subagents, skills, MCP, review mode, and app server | High-value reference for TUI/app ergonomics, sandbox/approval policy, worktree isolation, model capability gating, and subagent UX. |
| OpenCode | Open-source AI coding agent, terminal-first with desktop app, IDE extension, web/share, SDK/server, plugins, MCP, skills, and configurable agents | Clean terminal product and extensibility surface: Build/Plan primary agents, General/Explore subagents, strong tool permissions, TypeScript SDK, server API, custom tools/plugins | Already influences Penguin's TUI direction. Useful for config, permissions, agent modes, SDK/server contracts, and shareable sessions. |
| Pi | Minimal terminal coding harness intentionally kept small, extended through TypeScript extensions, skills, prompt templates, themes, packages, SDK, RPC, JSON event stream, and TUI components | Explicit small-core philosophy with rich extension/event/session contracts: session trees, compaction, message queueing, extensions, packages, and SDK | Best reference for event contracts, append-only sessions, compaction metadata, extension hooks, and disciplined boundaries. |
| Hermes Agent | Autonomous general agent from Nous Research, deployable beyond a laptop with messaging platforms, memory, skills, toolsets, terminal backends, scheduled automation, voice, MCP, and delegation | Self-improving long-running agent identity: closed learning loop, persistent memory, autonomous skill creation/improvement, many messaging surfaces, and remote/container/serverless execution | Reference for long-running remote agents, toolset gating, terminal backend abstraction, persistent memory UX, scheduled automations, and messaging delivery. |

## Feature Matrix

| Capability | Penguin | Claude Code | OpenAI Codex | OpenCode | Pi | Hermes Agent |
|---|---|---|---|---|---|---|
| License / availability | Open source, PyPI package, AGPL-3.0 | Commercial Anthropic product; most surfaces need a Claude subscription or Console account | Commercial OpenAI product included in ChatGPT Plus/Pro/Business/Edu/Enterprise plans | Open source agent from Anomaly; install script, npm/Bun/pnpm/Yarn, Homebrew, Arch packages | MIT-licensed npm package | MIT-licensed Nous Research agent |
| Main interfaces | `penguin`/`ptui`, headless CLI, FastAPI REST/WebSocket/SSE, Python API, OpenCode-style TUI sidecar | Terminal, VS Code, JetBrains, desktop app, web/browser, iOS/web handoff, Slack, CI/CD, Agent SDK | Desktop app, CLI TUI, IDE extension, web, GitHub/Slack/Linear integrations, SDK/app server/MCP server/GitHub Action | Terminal TUI, desktop app, IDE extension, web/share, JS/TS SDK, server, plugins | Terminal TUI, print mode, RPC mode, JSON event stream mode, SDK, custom TUI components | CLI plus Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Mattermost, Email, SMS, DingTalk, Feishu, WeCom, BlueBubbles, Home Assistant, voice |
| Coding tools | File operations, diffs, shell/test execution, search, analysis, browser tools, custom tools | Reads codebase, edits files, runs commands, Git/PR workflows, CI review/triage | Reads/explains code, writes/reviews/debugs, runs commands, integrated terminal, Git diff/commit/push/PR, review command | Built-in bash, edit, write, read, grep, glob, apply_patch, LSP, todo, webfetch, websearch, question | Built-in read, bash, edit, write, grep, find, ls; shell command injection from editor | Broad registry: web, terminal/files, browser, media, orchestration, memory, automation, messaging, Home Assistant, MCP, RL |
| Planning / safe modes | Engine loop, Run Mode, stop conditions, clarification states, task lifecycle; persona/tool defaults in config | Plans, permission modes, hooks, custom commands, best-practice workflows | CLI shows plans before changes; app/CLI approval and sandbox controls; local review mode | Build primary agent has full tools; Plan primary agent is restricted and intended for analysis without modifications | No built-in plan mode or permission popups by design; users can implement via extensions | Clarify/todo/delegation tools, command approval, authorization, container isolation |
| Multi-agent / delegation | Multi-agent coordinator, per-agent `agent_id`, sub-agent spawn/delegate/pause/resume, shared or isolated context windows, personas, MessageBus | Multiple Claude Code agents, lead-agent coordination, custom agents through Agent SDK | Subagents enabled by default when explicitly requested; built-in `default`, `worker`, `explorer`; custom TOML agents; app/CLI visibility | Primary agents plus subagents; built-in Build/Plan and General/Explore; subagents can be invoked automatically or by `@` mention | Intentionally no built-in subagents; SDK can be used to build custom tools that spawn sub-agents | Delegates and parallelizes via isolated subagents; `delegate_task` and `execute_code` support multi-step/parallel work |
| Session persistence / branching | Persistent sessions, checkpoints, rollback, branching, transcript replay, conversation manager, snapshot manager | Auto memory and conversation history; desktop/web can run sessions side by side; remote control/teleport | Local transcripts, `codex resume`, app threads, worktrees, automations in background worktrees | Sessions, child sessions for subagents, `/undo`, `/redo`, `/share` | Auto-saved JSONL sessions with tree structure, `/tree`, `/fork`, `/clone`, `/resume`, HTML export/share | SQLite session storage with FTS5 search; memory and session recall across conversations |
| Context management | Category-based Context Window Manager with system/context/dialog/output/error budgets, multimodal trimming, usage reports, per-agent clamps | Context-window docs, CLAUDE.md, auto memory, MCP/tools context | Compaction, prompt caching, token counting docs; app/CLI project/thread boundaries | Hidden compaction, title, and summary agents; tools and MCP caveats for context bloat | Auto-compaction, branch summarization, structured summary entries, configurable reserve/keep tokens | Bounded memory injected at session start; session search for broader recall |
| Long-term memory | Declarative notes, summary notes, file-backed context, SQLite plus vector providers: FAISS, LanceDB, Chroma, file | CLAUDE.md instructions plus auto memory | Memories and Chronicle in Codex concepts; rules/AGENTS.md/skills for project context | Rules, AGENTS.md via `/init`, skills, sessions/share; no single memory system emphasized in intro docs | AGENTS.md/CLAUDE.md context files, skills, prompt templates, session trees; no broad built-in memory store by design | Strong memory focus: MEMORY.md, USER.md, agent-curated memory, FTS5 session search, optional Honcho user modeling |
| Extensibility | Tool registry/plugin manager, custom tools, event bus/message bus, model providers, planned Agent Skills support | MCP, CLAUDE.md, custom commands, hooks, skills, Agent SDK | MCP, AGENTS.md, hooks, rules, plugins, skills, custom agents, Codex SDK/app server/MCP server | MCP, custom tools, plugins, skills, rules, commands, themes, keybinds, LSP, SDK/server | TypeScript extensions, skills, prompt templates, themes, packages, SDK, RPC, JSON event stream | Plugins, MCP, open-standard skills, context files, SOUL.md, toolsets, messaging gateway |
| Provider/model support | Native/gateway adapters for OpenAI, Anthropic, OpenRouter, LiteLLM, Gemini, Ollama; runtime model switching | Claude subscription/Console; terminal and VS Code also support third-party providers | OpenAI models; current docs recommend GPT-5.5 when available for most Codex tasks | Any LLM provider through API keys; OpenCode Zen curated models | OAuth subscriptions and API-key providers: ChatGPT/Codex, Claude Pro/Max, Copilot, OpenAI, Anthropic, Gemini, OpenRouter, Bedrock, Azure, many others | Nous Portal, OpenRouter, OpenAI, or any compatible endpoint |
| Automation / background work | Run Mode, continuous tasks, project/task orchestration, SQLite-backed task execution, telemetry; background execution still maturing | Routines, desktop scheduled tasks, `/loop`, CI/CD, Slack-routed work, web long-running tasks | App automations, thread automations, GitHub Action, non-interactive mode, cloud/worktree/local modes | Shareable conversations, GitHub/GitLab docs, SDK/server for automation; less background-control-plane detail in intro docs | Print/RPC/JSON modes and packages; intentionally no background bash built in | Built-in cron, scheduled delivery to messaging platforms, serverless/remote backends |
| Execution environments / sandboxing | Local workspace today, web server, browser automation; architecture points toward data-plane abstraction but not fully productized | Local terminal/IDE/desktop plus web/cloud sessions; permission modes; MCP tools | Local, Git worktree, cloud environment, remote app server, Windows sandbox, subagent sandbox inheritance | Local project environment; permissions; MCP local/remote; server; LSP; custom tools can execute arbitrary code | Local terminal harness; external containers/tmux recommended for workflows needing isolation | Local, Docker, SSH, Singularity, Modal, Daytona, Vercel Sandbox; container hardening and persistent workspace options |
| Evidence / verification posture | Explicit local goal: evidence-backed completion, artifact evidence, ITUV workflow, Run Mode task truth, diagnostics | Can run tests, lint, CI, create PRs, review code | Built-in review, terminal validation, Git diff, comments on chunks, PR creation | Tool results, todos, plan/build modes, share links; validation depends on workflow | Strong session/event/extension contracts, but intentionally minimal product policy | Long-running autonomy, memory, session search, toolsets; research and RL trajectory export |

## Per-Agent Notes

### Penguin

Penguin is not just a terminal chat loop. The local docs define it as a
stateful, event-driven coding-agent runtime with multiple interfaces over the
same core:

- `PenguinCore` coordinates config, events, runtime state, and managers.
- `Engine` owns the reasoning and tool loop.
- `ConversationManager` owns sessions, context, checkpoints, and snapshots.
- `ProjectManager` and Run Mode provide task execution and continuous work.
- `ToolManager` and `ActionExecutor` provide the workspace automation surface.
- `ContextWindowManager` uses category-aware token budgets and multimodal
  trimming.
- Multi-agent routing uses `agent_id`, shared infrastructure, isolated runtime
  state, MessageBus events, and sub-agent delegation.

Current strategic bar from `context/tasks/penguin-capability-bar.md`: Penguin
should optimize for truthful lifecycle state, explicit evidence, resumability,
and verification rather than "looks finished" autonomy.

### Claude Code

Documented strengths:

- Available in terminal, VS Code, JetBrains, desktop app, web/browser, and
  Slack/CI-style integrations.
- Reads codebases, edits files, runs commands, creates commits/PRs, and
  automates repetitive development tasks.
- Supports MCP, project instructions/memory through `CLAUDE.md`, auto memory,
  custom commands, hooks, skills, and multi-agent/custom-agent workflows.
- Strong cross-surface continuity story: remote control, web/iOS tasks,
  `/desktop`, `--teleport`, routines, desktop scheduled tasks, and `/loop`.

What Penguin can learn:

- Treat recurring work, chat/CI integrations, and handoff across surfaces as
  first-class product flows.
- Keep project instructions, memories, hooks, commands, and skills easy for a
  team to understand and version.
- Make multi-agent workflows visible and ergonomic, not just available through
  backend primitives.

### OpenAI Codex

Documented strengths:

- A unified product surface across app, CLI, IDE extension, web, GitHub, Slack,
  Linear, SDKs, and automation.
- Desktop app supports parallel threads, projects, Local/Worktree/Cloud modes,
  worktree isolation, built-in Git diff/comment/stage/revert/commit/push/PR,
  integrated terminal, automations, skills, and voice dictation.
- CLI supports interactive TUI, local transcripts/resume, remote app-server
  mode, model switching, image inputs, image generation, local code review, and
  subagents.
- Subagents are explicit: Codex only spawns them when asked, exposes them in
  app/CLI, inherits sandbox/approval policies, and provides built-in
  `default`, `worker`, and `explorer` roles plus custom TOML agents.
- MCP is supported in CLI and IDE extension with STDIO and streamable HTTP
  servers, OAuth/bearer auth, tool allow/deny controls, and project-scoped
  config.

What Penguin can learn:

- Worktrees are a practical isolation model for parallel coding tasks.
- Subagent controls should expose concurrency/depth limits, sandbox inheritance,
  custom roles, and UI visibility.
- Model capability metadata should gate request options such as reasoning,
  verbosity, speed tier, and parallel tool calls.
- Review mode is a distinct workflow, not just "ask the agent to review".

### OpenCode

Documented strengths:

- Open-source, terminal-first agent with desktop app and IDE extension.
- Strong configuration story: providers, rules, agents, tools, permissions,
  keybinds, commands, formatters, LSP, MCP, skills, and custom tools.
- Built-in tool list is explicit: bash, edit, write, read, grep, glob, LSP,
  apply_patch, skill, todo, webfetch, websearch, and question.
- Permission model can allow, deny, or ask per tool, including wildcard rules.
- Agent model is simple and useful: Build and Plan primary agents; General and
  Explore subagents; custom agents can define prompts, models, permissions,
  modes, and tool access.
- SDK provides a type-safe JS/TS client for controlling the OpenCode server and
  using generated OpenAPI types.

What Penguin can learn:

- Keep the agent-mode vocabulary small and concrete.
- Make permissions/tool access configurable at the same level users configure
  agents.
- Publish a clean programmatic server/SDK contract so alternate UIs do not
  reverse-engineer the TUI.

### Pi

Documented strengths:

- Minimal terminal harness with a deliberately small core.
- Rich editor and session UX: file references with `@`, image inputs, shell
  commands, message queueing, slash commands, session resume, trees, forks,
  clones, compaction, HTML export, and private gist sharing.
- Sessions are JSONL trees with branch navigation and summaries.
- Compaction is explicit and documented: automatic thresholding, configurable
  reserve/keep tokens, structured summary entries, branch summarization, and
  cumulative file tracking.
- Extensions are TypeScript modules that can register tools, commands,
  shortcuts, flags, custom UI, renderers, providers, lifecycle hooks, and
  tool-call interceptors.
- Skills implement the Agent Skills standard and can load skills from Pi,
  `.agents`, Claude Code, or Codex directories.
- SDK can embed Pi in other apps, automate pipelines, test behavior, and build
  custom tools that spawn sub-agents.
- Pi explicitly does not include built-in MCP, sub-agents, permission popups,
  plan mode, to-dos, or background bash; those are extension/package territory.

What Penguin can learn:

- The event/session boundary matters more than any one UI.
- An append-only session tree with structured compaction artifacts is a strong
  primitive for replay, branching, audit, and LLM-context projection.
- Extension hooks should wrap lifecycle, tool policy, UI, commands, session
  replacement, and compaction without making the kernel monolithic.

### Hermes Agent

Documented strengths:

- Autonomous agent intended to run beyond the laptop: VPS, GPU cluster,
  Docker/SSH/Singularity/Modal/Daytona/Vercel Sandbox, and messaging platforms.
- Strong "self-improving" narrative: agent-curated memory, periodic memory
  nudges, autonomous skill creation, skill self-improvement, FTS5 cross-session
  recall, and optional Honcho user modeling.
- Large built-in tool registry: web search/extract, terminal/files, browser
  automation, multimodal media, planning/clarification/code execution,
  delegation, memory/session search, cron, messaging, Home Assistant, MCP, and
  RL tools.
- Toolsets can be enabled/disabled per platform, with presets for CLI,
  messaging surfaces, and dynamic MCP toolsets.
- Persistent memory is bounded and visible: MEMORY.md and USER.md are injected
  at session start, with capacity limits, duplicate prevention, and security
  scanning.
- Built-in cron and delivery to messaging platforms support scheduled
  automations.
- Voice mode is available in CLI and messaging/Discord voice contexts.

What Penguin can learn:

- Separate execution backend lifecycle from agent/task lifecycle.
- Make toolsets platform-aware so a Telegram agent, CLI agent, and web agent do
  not automatically share the same risk profile.
- Persistent memory UX should show capacity, scope, and update semantics.
- Scheduled automations need delivery surfaces and recovery semantics, not just
  "run this later" prompts.

## Capability Gaps And Opportunities For Penguin

### Highest-Leverage Product Gaps

1. **Canonical runtime event contract**
   - Pi and background-agent context both point at the same lesson: every
     surface should project one event stream with stable ids, lifecycle phases,
     agent ids, task ids, tool ids, timestamps, and replay semantics.

2. **Evidence-backed completion as product behavior**
   - Penguin's local capability bar is stronger than most public docs, but the
     runtime must enforce it: implementation evidence, test evidence, usage
     evidence, artifact records, and honest task states.

3. **Background execution control plane**
   - Claude Code, Codex, and Hermes all frame long-running/off-device work as a
     user-facing feature. Penguin has Run Mode and tasks; the next step is a
     durable reconnectable run/session control plane.

4. **Worktree/sandbox lifecycle**
   - Codex makes worktrees central for parallel local isolation. Hermes makes
     terminal backends explicit. Penguin should define execution-environment
     state independently from agent/task state.

5. **Extension and skill system**
   - Pi, Claude Code, Codex, OpenCode, and Hermes all converge on skills,
     custom tools, and lifecycle hooks. Penguin's Agent Skills plan should be
     implemented around progressive disclosure and tool/policy hooks, not just
     extra prompt files.

6. **Sub-agent UX**
   - Penguin has backend primitives. Codex/OpenCode show the need for small,
     named roles, explicit invocation, visibility, concurrency/depth controls,
     and inherited sandbox/approval semantics.

7. **Messaging and automation surfaces**
   - Claude Code and Hermes show a broader product frontier: Slack/Telegram/etc.
     as first-class task ingress and delivery channels. Penguin's web/API layer
     can support this if runtime state is durable and events are replayable.

### Differentiators Penguin Already Has Or Can Own

- A Python-first open runtime with CLI, TUI, web/API, and embedding APIs.
- Category-aware context budgeting rather than opaque compaction only.
- Project/task lifecycle with SQLite persistence and Run Mode.
- Explicit multi-agent routing and MessageBus concepts.
- Checkpoints, rollback, branching, and transcript replay.
- A stated reliability bar centered on truthful lifecycle state and explicit
  evidence.
- Potential to make formal verification normal for orchestration/state-machine
  work where it is worth the cost.

## Short Recommendations

1. Define one canonical `RuntimeEvent` envelope and adapt CLI, TUI, web/SSE,
   REST, and Python API to it.
2. Convert sessions/tasks/runs toward an append-only ledger with projections for
   UI, model context, audit, and task state.
3. Add structured compaction artifacts for files read/modified, commands run,
   tests, errors, decisions, and acceptance evidence.
4. Promote execution environments to first-class state:
   `pending`, `spawning`, `ready`, `running`, `stale`, `snapshotting`,
   `stopped`, `failed`.
5. Implement Agent Skills with progressive disclosure and compatibility with
   `.agents/skills`, `.codex/skills`, and `.claude/skills` where practical.
6. Add per-tool execution policy metadata:
   `read_parallel_safe`, `mutation_exclusive`, `requires_confirmation`,
   `cancel_safe`, `streaming_result`, and `terminal_tool`.
7. Make Run Mode completion require evidence where the task type has acceptance
   criteria, tests, artifacts, or usage recipes.
8. Treat worktrees as the default local isolation primitive for parallel coding
   tasks once project/root semantics are stable.
