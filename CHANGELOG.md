Changelog
=========

(I should've started this at the beginning of Penguin, but I suppose better late than never..)

All notable changes to this project are documented in this file.

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