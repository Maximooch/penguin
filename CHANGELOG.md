Changelog
=========

(I should've started this at the beginning of Penguin, but I suppose better late than never..)

All notable changes to this project are documented in this file.

0.7.0 — 2026-04-27
------------------

Highlights
- **Native tool-call runtime hardening**: Completed the tool-call runtime architecture work through Phase 5.6, including provider transcript normalization, native tool-call ordering, and stricter tool-result handling.
- **Web/TUI security overhaul**: Hardened local auth bootstrap, protected HTTP/SSE/WebSocket paths, strengthened upload handling, and added webhook replay defenses.
- **Project bootstrap workflow**: Added project init/start commands, exposed project/task parity routes, expanded TUI project and task commands, and tightened session workspace scoping.
- **Run Mode reliability**: Thinned `Engine.run_task` into the unified iteration loop, preserved non-terminal task outcomes, surfaced blocked project frontiers, and hardened executor cleanup/status semantics.
- **OpenAI/Codex improvements**: Added `service_tier`/fast-mode support, improved OAuth-backed Codex latest-model access, and fixed OpenRouter/OpenAI tool-continuity regressions.
- **TUI polish**: Added Penguin TUI themes and defaulted the TUI to the Emperor theme.

Added
- Project bootstrap commands for init/start flows in CLI/TUI surfaces.
- Project and task API parity routes for web/API consumers.
- `/fast` mode command and deeper OpenAI/Codex service-tier request support.
- Penguin TUI theme support, including Emperor as the default theme.
- Deterministic tests for project start, TUI command routing, web hardening, provider contracts, native tool runtime IR, and Run Mode truth surfaces.

Changed
- Removed the old Ink-based CLI and retired unused desktop surface code.
- Normalized docs package management and refreshed frontend/docs dependencies within compatibility bounds.
- Refactored shared web auth helpers and local browser/TUI bootstrap flows around server-written session auth.
- Reworked native tool-call handling around a stricter runtime architecture and ordered TUI event delivery.

Fixed
- Web auth guards, local startup defaults, upload handling, and GitHub webhook replay validation.
- TUI local auth regressions by preferring server-written auth cache state over provisional environment tokens.
- Project executor cleanup paths, malformed status payload handling, duplicate project init behavior, and blocked run frontier visibility.
- Anthropic tool-result adjacency plus native tool-call transcript and TUI ordering regressions.
- Codex reasoning/completion leaks and ChatGPT-backed Codex latest-model access.

0.5.0 — 2026-01-28
-------------------

Highlights
- **Journal 247 Phase 1**: Session journaling system for persistent session tracking and recovery.
- **Permission Engine**: Configurable security framework with approval flows, audit logging, and agent-specific permissions.
- **Major CLI Refactoring**: Event-driven architecture with extracted manager classes (Display, Session, Streaming, Event).
- **Multi-Agent Parallelization**: Background agent execution, `delegate_explore_task`, and context window management.
- **Link Integration**: LLM proxy for unified billing and cost management.

Added
- Session journaling system (Journal 247) with automatic session persistence.
- Permission engine with configurable approval flows, audit logging, and read-only agent support.
- Streaming controls: `/cancel` command and ESC key for immediate cancellation.
- Checkpoint system: `/checkpoint`, `/checkpoints`, `/rollback <id>`, `/branch <id> [name]`.
- Context management: `/context add|list|write|edit|remove|note|clear`.
- Model selection: `/models`, `/model set <MODEL_ID>`, `/stream on|off`.
- Diagnostics: `/tokens`, `/tokens detail`, `/truncations [limit]`.
- Run Mode commands: `/run task "Name"`, `/run continuous ["Name"]`.
- `delegate_explore_task` for autonomous sub-agent codebase exploration.
- Link LLM proxy integration with WALLET_GUARD to prevent infinite loops.
- Lazy loading for environment variables and API keys (faster startup).
- Multi-location context file loading with flexible path resolution.

Changed
- CLI completely refactored to event-driven streaming architecture.
- Extracted manager classes: DisplayManager, SessionManager, StreamingManager, EventManager.
- Improved OpenRouterGateway stream handling to preserve whitespace-only segments.
- Standardized token limit naming convention across configuration.
- Dynamic context window management (models use max 85% of available context).
- Increased default `max_iterations` from 10 to 5000.
- WebSocket connection handling with improved state checks and error recovery.

Fixed
- WebSocket streaming stability and RuntimeError handling.
- Empty response loop prevention with forced context advance.
- `/image` command parsing for drag-and-drop and multiline paths.
- Prevented 🐧 Penguin emoji duplication during streaming.
- Tool reliability: multi-edit stability and code execution improvements.
- Context truncation handling in `_enhanced_write` method.
- Auto-continuation bug in conversation handling.
- Conversation saving and session management issues.

Experimental
- Ink CLI (TypeScript): Accumulator pattern, static rendering, extracted hooks.
- Image drag-and-drop support in TUI experiments.

0.4.0 — 2025-11-16
-------------------

Highlights
- Multi/sub‑agent runtime: per‑agent conversations, model configs, tool defaults, and optional context‑window clamps for sub‑agents.
- Interleaved reasoning: tool/action → reflect → resume loop with improved eventing and resilience.
- Event‑driven Python CLI: revised streaming pipeline, better tool result ordering, and richer in‑chat commands.
- Web API improvements: WebSocket streaming fixes and GitHub webhook integration groundwork.

Added
- In‑chat commands:
  - `/models`, `/model set <MODEL_ID>` for runtime model selection.
  - `/stream on|off` to toggle token streaming.
  - Checkpoints: `/checkpoint`, `/checkpoints`, `/rollback <id>`, `/branch <id> [name]`.
  - Diagnostics: `/tokens`, `/tokens detail`, `/truncations [limit]`.
  - Context helpers: `/context add|list|write|edit|remove|note|clear`.
- Run Mode commands in chat: `/run task "Name" [desc]`, `/run continuous ["Name" [desc]]`.
- Project/Task management commands exposed more prominently in CLI flows.
- Image support surfaced in the CLI UX (drag‑and‑drop behavior in TUI experiments).

Changed
- Python CLI refactor to an event‑driven streaming architecture; improved rendering and layout.
- Model/provider configuration flow and selection UI refreshed (interactive `/models`).
- Prompting improvements and adoption of OpenRouter Responses API where available.

Fixed
- Tools reliability: multi‑edit and code execution stability improvements.
- WebSocket streaming stability and Run Mode coordination issues.
- Numerous UI fixes (reasoning pane, code fences, duplicate message prevention, settings hotkeys).

Notes
- No breaking API changes expected for typical users. Some CLI command names/locations have been consolidated; run `/help` in chat or see the CLI docs for details.
- The TypeScript CLI is experimental and not included in the PyPI package.