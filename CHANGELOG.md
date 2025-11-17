Changelog
=========

(I should've started this at the beginning of Penguin, but I suppose better late than never..)

All notable changes to this project are documented in this file.

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

