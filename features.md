# Penguin Capabilities Overview

## Available Today

### Core Orchestration
- Multi-agent runtime with planner/implementer/QA personas, lite agents, and
  per-agent state tracked through `agent_id` routing.
- Sub-agent delegation with shared context, inherited tool access, scoped token
  budgets, streaming progress events, and checkpoint adoption/rollback.
- Engine-driven reasoning loop supporting Run Mode, configurable iterations,
  and pluggable stop conditions (token budget, wall clock, external callbacks).
- Central MessageBus with channel semantics so CLI/TUI, web, and dashboards can
  subscribe to agent-specific or system-wide events with metadata preserved.

### Conversation & Memory Systems
- ConversationManager combining session persistence, auto-save, context file
  loading, checkpoint manager, and snapshot manager for branch/restore flows.
- Persistent conversation history with shared memory across agents while
  protecting per-agent runtime variables.
- ContextWindowManager with category-based token budgets, dynamic
  redistribution, multimodal image trimming, and live usage reporting.
- Declarative memory notes, summary notes, and retrieval-backed recall layered
  on SQLite plus pluggable vector providers (FAISS, LanceDB, Chroma, others).

### Development Tools & Workspace Automation
- Workspace-aware toolchain that honours project/workspace roots for file
  creation, editing, diffs, pattern-based edits, renames, and file mapping.
- LLM-driven development workflows for project scaffolding, code/document/test
  generation, refactoring, and debugging assistance.
- Code quality and analysis tooling: AST analyzer, dependency mapper,
  lint_python, enhanced_diff/apply_diff, and notebook-based execution for
  running tests or snippets.
- Search and research utilities including grep/workspace search, declarative
  memory search, Perplexity integration, and web search helpers.
- Browser automation via headless navigator plus PyDoll interaction/screenshot
  tools for scripted browsing and capture workflows.
- Repository automation helpers that scaffold improvement/feature/bugfix PRs,
  manage branches, check repo status, and perform commit/push sequences.
- Tool/action execution pipeline with 15+ extensible tools managed through
  ToolManager and ActionExecutor, supporting custom tool registration.

### Project & Task Management
- SQLite-backed ProjectManager with ACID transactions, event bus integration,
  dependency graphs, resource budgets, execution history, and dual sync/async
  APIs.
- CLI, Python, and web surfaces for creating projects, nesting tasks, tracking
  status, recording execution results, and tagging or budgeting workstreams.
- Integrated task execution through Run Mode so long-running objectives can be
  orchestrated autonomously with progress reporting.

### Interfaces & Integrations
- Rich CLI with interactive TUI, configuration wizard, context root controls,
  and 20+ project/task/memory commands.
- Async Python client (`PenguinClient`) offering streaming chat, checkpoint
  workflows, model switching, multi-agent routing, and task automation.
- FastAPI-based web server with REST + WebSocket streaming endpoints for chat,
  tasks, telemetry, conversations, and health, plus a reusable `PenguinAPI`
  class for embedding.
- Dashboard hooks and telemetry endpoints powering the bundled analytics UI
  and external monitoring integrations.

### Model & Provider Support
- Native and gateway adapters covering OpenAI, Anthropic, OpenRouter, LiteLLM
  providers (Azure, Bedrock, Deepseek, Ollama, etc.) with automatic fallbacks.
- Runtime model and provider switching with layered configuration resolution,
  capability detection, and multimodal (vision/image) support.
- Provider-aware token counting, usage reporting, and budget enforcement made
  available to the engine, CLI, and telemetry dashboards.

### Performance, Diagnostics & Governance
- Fast-startup path with lazy tool loading, deferred memory indexing, and
  background workers to shrink cold-start latency.
- Structured diagnostics including startup profiling, operation timing,
  resource snapshots, and error tracking surfaced through CLI and APIs.
- Telemetry collector aggregating message, agent, task, and token metrics with
  HTTP endpoints for dashboards and alerting.
- Configurable logging, retry policies, and graceful error recovery throughout
  the core, API, and tool subsystems.

### Data & Context Ingestion
- Baseline PDF/text extraction pipeline, context file loader, and workspace
  cataloguing so agents can ground responses in project materials.
- Memory indexing pipeline with background tasks, semantic search, and
  declarative knowledge capture tied into the conversation flow.

### Extensibility & Configuration
- Tool plugin architecture (ToolRegistry, PluginToolManager) for declarative or
  dynamic tool registration without core changes.
- Comprehensive configuration via `config.yml`, environment variables, and CLI
  helpers, including project/workspace root selection and model defaults.
- Event bus + MessageBus extension points so custom services can subscribe to
  agent lifecycle events, tool calls, and telemetry streams.

## In Flight / Near Term
- Robust PDF ingestion powered by pdfminer/PyMuPDF with improved kerning and
  artifact cleanup.
- Web search and browser tooling refresh to improve snippet fidelity, filtering,
  and deterministic scraping flows.
- Delegation UX polish across CLI/Web: lifecycle events surfaced in UI, richer
  threading, and helper commands for sub-agent orchestration.
- Planner/Implementer/QA spec alignment plus scenario templates for repeatable
  multi-agent workflows.
- Lite agent catalogue (reader, summariser, search helper) with ergonomic
  factory APIs for spawning scoped assistants.

## Longer-Horizon / Planned
- Expanded TUI & web UI with agent roster views, persona switching, and
  per-agent transcript management.
- OpenRouter filtering, routing policies, and gateway resilience work for
  enterprise deployments.
- Comprehensive system documentation covering delegation patterns,
  troubleshooting, and best practices for large teams.
- Delegation analytics suite featuring hierarchical views, per-agent token
  accounting, and dashboard visualisations.
