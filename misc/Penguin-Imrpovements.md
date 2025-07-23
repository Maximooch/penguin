# Penguin Continuous Improvement Roadmap

_A living document. Last updated: 2025-06-27_

This roadmap converts the lessons learned from Claude Code and current CLI-UX best-practices [[link](https://evilmartians.com/chronicles/cli-ux-best-practices-3-patterns-for-improving-progress-displays)] into concrete, incremental milestones for the Penguin project.  The plan is deliberately iterative – each release tightens feedback loops and builds on the previous one.

---
## Guiding Principles

1. **Safety first** – permission-gated, least-privilege tool execution.
2. **Fast startup, rich context** – cache expensive computations and snapshot project state early.
3. **Delightful CLI UX** – colourful progress, spinners, quiet mode, clear errors.
4. **Observability** – track cost, latency, token usage and surface them to users.
5. **Continuous improvement** – treat this file as code; every PR should update status.

---
## Roadmap at a Glance

| Quarter | Release Codename | Theme | High-level Goals |
|---------|-----------------|-------|------------------|
| Q3 2025 | "Safety Net" | Safety & Permissions | granular permissions, read-only flag, BashTool hardening |
| Q4 2025 | "Seeing Eye" | Context & Snapshot | directory tree & git snapshot, memoisation layer, hidden ThinkTool |
| Q1 2026 | "Smooth Talk" | CLI UX | Rich/Textual (Python) TUI, progress widgets, cost tracker summary |
| Q2 2026 | "Autopilot" | Multi-step Engine | streamlined thought/tool/observation loop, event-bus refactor |
| Q3 2026 | "Polish & Ecosystem" | UI & Ecosystem Expansion | diff viewer, Gemini provider, Textual CLI polish, containerization, LSP, browser tool upgrades |

Dates are tentative; exact sprints live in the GitHub project board.

---
## Milestones & Tasks

### Phase 1 – **Safety Net** (target: June 27th 2025AD)

1. **Permission Layer MVP**
   - [ ] Add `needs_permissions()` to all existing tools (default `False`).
   - [ ] Create `ToolPermissionManager` storing allowed keys in `~/.penguin_project.yml`.
   - [ ] Implement BashTool command-prefix detection & injection guard.
   - [ ] Add CLI prompt (`penguin --grant`) for interactive approval.
2. **Read-only / Mutating Flag**
   - [ ] Extend `Tool` base class with `is_read_only()`.
   - [ ] Update permission logic to auto-allow read-only tools.
3. **Unit tests & docs**
   - [ ] 100 % coverage for permission edge-cases.
   - [ ] Update `docs/safety.md`.

### Phase 2 – **Seeing Eye** (target: June 27th 2025AD)

1. **Context Snapshot Service**
   - [ ] CLI sub-command `penguin snapshot` writes a tree view, git status, README into `conversation.context`.
   - [ ] Memoise expensive calls with `functools.lru_cache`.
2. **ThinkTool (Hidden Thoughts)**
   - [ ] Implement `ThinkTool` returning log-only content.
   - [ ] Hide from user transcript; surface under `--debug thoughts`.
3. **Startup Performance**
   - [ ] Convert FAISS indexing to lazy task with progress bar.
   - [ ] Provide `core.enable_fast_startup_globally()` CLI flag.

### Phase 3 – **Smooth Talk** (target: June 27th 2025AD)

1. **Rich/Textual-powered TUI Shell (Python)**
   - [ ] Replace raw `print()` with Rich components (colour, boxed errors).
   - [ ] Implement spinner, `X / Y` progress, overall bar.
   - [ ] `--quiet` & `--plain` modes for piping.
2. **Cost & Latency Tracker**
   - [ ] Hook into `APIClient` to aggregate token & $ cost per request.
   - [ ] On process exit print grey summary (see Claude cost-tracker).
   - [ ] Persist last-session stats to `project_config`.

### Phase 4 – **Autopilot** (target: June 27th 2025AD)

1. **Structured Agent Loop**
   - [ ] Enforce message order: _thought → action → observation → thought_.
   - [ ] Emit per-step events on the UI bus.
2. **Event-Bus Refactor**
   - [ ] Formalise `emit_ui_event` payload schema (TypeScript types & Python `TypedDict`).
   - [ ] Expose WebSocket endpoint for future VS Code plugin.
3. **Automatic Model Tiering**
   - [ ] Add heuristic in `Engine.run_single_turn` selecting cheap vs powerful model based on token budget.

### Phase 5 – **Polish & Ecosystem Expansion** (target: June 28th 2025AD)

1. **UI Simplification & Enhancement**
   - [ ] Offer a "classic" one-shot CLI mode (Rich + Typer) modelled after Claude Code for quick commands.
   - [ ] Continue refining the Textual TUI: theming, resizable panes, keyboard shortcuts, mouse support.
   - [ ] Integrate a Rich-powered inline **diff viewer** and Textual split-pane diff widget.
   - [ ] Improve diff-apply reliability (smarter patch context, fallback to 3-way merge).

2. **New Providers & Tooling**
   - [ ] Add a native **Gemini** API provider (direct, no OpenRouter) to leverage free tier tokens.
   - [ ] Harden and expand **Browser tools** (persist cookies, smarter selector search, download API).
   - [ ] Implement **git-worktree** awareness for multi-branch workflows.
   - [ ] First-class **container / sandbox execution** (Docker & Podman) for BashTool and notebook runs.

3. **Productivity & Workflow**
   - [ ] Land **multi-step message** parsing / display in CLI & Web UI.
   - [ ] Ship v2 of the **Process Manager** (pause, resume, priority queues, SIGINT handling).
   - [ ] Complete **MCP (Monitored Code Path)** integration for safer tool execution.
   - [ ] Release the **Language-Server Protocol (LSP) bridge** so editors can surface Penguin suggestions inline.
   - [ ] Improve prompting templates specifically for code-generation tasks (unit tests, refactors).

4. **Search & Context**
   - [ ] Replace current `web_search` with a pluggable multi-engine aggregator, caching, and source ranking.
   - [ ] Expose search results in a Textual modal with clickable links and preview.

5. **Link MVP Enhancements**
   - [ ] Deepen Link ↔ Core API: drag-and-drop task assignment, live task board, résumé tokens.
   - [ ] Embed diff viewer and agent status widgets in Link.

---
## Continuous Improvement Workflow

1. **SMART Goals** – Each checklist item above is a SMART goal: specific, measurable (unit test / CLI flag), achievable, relevant, time-bound [[link](https://blog.triaster.co.uk/blog/how-to-build-continuous-improvement-roadmap-practical-guide)].
2. **Ask-The-Crowd Board** – Mirror this markdown into the GitHub project board; every issue links back here.
3. **Retrospective** – At the end of each quarter update _Status_ column below.

| Task | Owner | Status |
|------|-------|--------|
| Permission Layer MVP | | ☐ |
| BashTool Guard | | ☐ |
| Context Snapshot | | ☐ |
| ThinkTool | | ☐ |
| CLI Ink Refactor | | ☐ |
| Cost Tracker | | ☐ |
| Agent Loop Refactor | | ☐ |

---
_Questions or suggestions? Open an issue with the **roadmap** label. Penguin thrives on small, continuous improvements._ 