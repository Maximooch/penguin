God bless us all! 

August 23rd 2025AD 102p

---

(August 25th 2025AD 842a. God bless us all!)

# Create the Penguin-TODO.md file with a comprehensive checklist

content = """# Penguin — TODO (Parity with Claude Code)

> Status legend: [ ] = not started · [~] = in progress · [x] = done  
> Priorities: P0 = must-have for parity · P1 = important · P2 = nice-to-have

## 1) UI/UX & IDE Integrations

- [ ] (P0) **VS Code extension (MVP)**
  - [ ] Chat panel docked in sidebar; connect to local `penguin-web` via WS/HTTP
  - [ ] Inline code actions: apply edits as IDE diffs, not plain text
  - [ ] Context injection: auto-share active file/selection; toggle include-open-editors
  - [ ] Command Palette: `Penguin: Fix Tests`, `Review Diff`, `Generate Commit`
  - [ ] Permission prompts for destructive ops (write, run, network)
  - [ ] Settings UI (model, tool allowlist, workspace root)
  - [ ] Telemetry **off by default**; explicit opt-in
  - [ ] Docs + example walkthrough (bug fix, refactor, PR prep)

- [ ] (P1) **JetBrains plugin** (IntelliJ/IDEA/WebStorm/PyCharm)
  - [ ] Same feature set as VS Code; reuse protocol layer

- [ ] (P1) **Terminal UX polish**
  - [ ] Vim-style inline editor for prompts (multiline compose; edit last msg)
  - [ ] Rich diff viewer (hunks, +/- highlights, jump-by-file)
  - [ ] Clickable file paths; open-in-editor integration
  - [ ] Customizable status bar (tokens, elapsed, model, tool state)
  - [ ] Keyboard shortcuts reference (`/help` overlay)

- [ ] (P0) **Web UI (alpha)**
  - [ ] Realtime chat, streaming tokens, tool traces timeline
  - [ ] File tree, code editor w/ diff apply, terminal panel
  - [ ] Session management, project switcher, auth (local-first)
  - [ ] Hotkeys + command palette; dark/light themes

---

## 2) SDK & API

- [ ] (P0) **Publish Python API client (pip)**
  - [ ] Autogenerate from OpenAPI; add ergonomic wrappers
  - [ ] Auth, retries, streaming; type hints
  - [ ] Examples: headless runs, CI usage, server callbacks

- [ ] (P1) **TypeScript client**
  - [ ] ESM/CJS builds; Node/Browser support; examples

- [ ] (P1) **Config layering & presets**
  - [ ] Model presets (Anthropic/OpenAI/local), safety levels, tool allowlists
  - [ ] Stable public API surface; semver policy & deprecation notes

- [ ] (P2) **GitHub Actions templates** (headless Penguin in CI)

---

## 3) Subagents (Modular Agents)

- [ ] (P0) **Spec & runtime**
  - [ ] YAML schema: `name`, `purpose`, `system_prompt`, `tools_allowed`, `budget`
  - [ ] Context isolation (separate history/memory); token & time budgets
  - [ ] Orchestrator: spawn, route, gather, cancel; telemetry

- [ ] (P0) **Built‑in subagents**
  - [ ] Code Reviewer (read-only tools, style/security checks)
  - [ ] Test Runner (execute tests, triage failures, retry loop)
  - [ ] Security Auditor (Semgrep/Bandit hooks; dependency scan)
  - [ ] Migrator (API/library/framework upgrades with plan/diff)

- [ ] (P1) **UX**
  - [ ] `/agents list|create|use` commands
  - [ ] Project‑level registry & config; IDE/Web UI integration

---

## 4) Tools & Plugin System

- [ ] (P0) **New core tools**
  - [ ] `diff.show(path|rev)`, `multiedit.apply([...])` (atomic multi-hunk edits)
  - [ ] `notebook.read/edit` (.ipynb support via nbformat; safe round‑trip)
  - [ ] `web.fetch(url)` (HTML/text fetch with size/host limits)
  - [ ] `changelog.write(entry)`; `doc.update(path, section, content)`
  - [ ] GitHub: `issue.read(#)`, `pr.create(title, body)` (token‑gated)

- [ ] (P0) **Permission & safety layer**
  - [ ] Per‑tool allowlist; interactive confirm/deny; `--assume-yes` for CI
  - [ ] Dry‑run mode (print planned actions/diffs only)
  - [ ] Audit log of tool invocations with args & outcomes

- [ ] (P1) **Plugin ecosystem**
  - [ ] Entry‑point API (`penguin.plugins`); lifecycle hooks
  - [ ] Scaffolding: `penguin plugin new`
  - [ ] Example plugins: Jira, Slack, Figma, Sentry, Browser‑automation
  - [ ] Community index (registry JSON) + version constraints

- [ ] (P2) **Integrations**
  - [ ] GitHub App (least‑privileged scopes); GitLab equivalent
  - [ ] Puppeteer/Playwright browser control (headless task flows)

---

## 5) Prompt Engineering & Modes

- [ ] (P0) **Project instructions file**
  - [ ] Auto‑load `PENGUIN.md` from repo root; merge into system context
  - [ ] Support includes: style guides, build steps, domain constraints

- [ ] (P0) **Output styles/modes**
  - [ ] `/mode default|explain|learn|terse|review`
  - [ ] Mode‑specific deltas (verbosity, pedagogy, formatting)

- [ ] (P1) **Reasoning controls**
  - [ ] `/reflect` or keyword triggers (“think hard”) → larger reasoning budget
  - [ ] Dynamic step‑limits & verification depth by task type

- [ ] (P1) **Prompt refactor**
  - [ ] Slim core rules; make advisor persona optional
  - [ ] Token budget guardrails; structured self‑checks

---

## 6) CLI Enhancements

- [ ] (P0) **Unified config commands**
  - [ ] `penguin config show|set|list` (maps to file/env; schema validation)
  - [ ] `/config` UI in TUI mirrors same settings

- [ ] (P1) **Help & discoverability**
  - [ ] Rich `/help` overlay with searchable commands & keybinds
  - [ ] Shell completion scripts; examples gallery (`penguin examples`)

- [ ] (P1) **Headless quality**
  - [ ] `--output-format json` parity across commands; stable fields
  - [ ] Meaningful exit codes; `--diff-output` (unified patch)

- [ ] (P2) **Convenience cmds**
  - [ ] `penguin fix <stacktrace>` → guided bugfix flow
  - [ ] `penguin review <diff|range>` → structured review
  - [ ] `penguin scaffold <template>` → boilerplate projects

---

## 7) Language & Execution Support

- [ ] (P0) **Notebook support**
  - [ ] Read/modify `.ipynb`; cell‑level diffs; safe metadata handling

- [ ] (P1) **Non‑Python sandboxes**
  - [ ] Node.js eval tool (vm2/isolated‑vm); capture output/errors
  - [ ] Java/Maven & Gradle runner; test report parsing
  - [ ] C/C++ compile‑run via Docker tool; resource quotas

- [ ] (P1) **Style enforcement**
  - [ ] Detect & honor linters/formatters (black, eslint, prettier, gofmt)
  - [ ] Auto‑run formatters post‑edit; fail fast on violations

- [ ] (P2) **Model selection heuristics**
  - [ ] Route by language/task if multiple providers available; user override

---

## 8) Git & Project Context Awareness

- [ ] (P0) **Initial project scan & index**
  - [ ] Fast file tree & key config discovery; cache summary
  - [ ] Optional semantic index (embeddings) with background updater
  - [ ] Watcher to refresh on FS changes

- [ ] (P0) **Commits & branches**
  - [ ] Auto‑commit flow (on approval): branch → commit (good message) → push
  - [ ] Commit message generator (uses task plan & diff)
  - [ ] PR body generator; link to issues; checklist of changes

- [ ] (P1) **VCS intelligence**
  - [ ] Utilities: blame, `git log -S`, `git diff --name-only` for impact scans
  - [ ] Use VCS data in answers (why/when lines changed)

- [ ] (P1) **Context summarization**
  - [ ] Periodic “work summary” notes; checkpoint/rollback; branch‑from‑checkpoint

---

## 9) Code Quality Loops

- [ ] (P0) **Test‑then‑fix loop by default**
  - [ ] After edits, auto‑run tests; triage failures; iterate up to N attempts
  - [ ] Stop criteria & clear user surfacing of remaining failures

- [ ] (P0) **Self‑review phase**
  - [ ] Lint/static analysis (flake8/mypy/eslint/semgrep); enforce thresholds
  - [ ] Security scan on touched files; dependency advisories

- [ ] (P1) **Docs & changelog**
  - [ ] Auto‑update CHANGELOG.md for P0/P1 tasks
  - [ ] Insert/refresh docstrings and README sections

- [ ] (P2) **/why & /explain**
  - [ ] Commands to summarize reasoning and changes since last step

---

## 10) Collaboration & Review

- [ ] (P1) **Review mode**
  - [ ] Input: diff or PR; Output: structured findings, risks, suggestions
  - [ ] (Opt) GitHub inline comments via API when token provided

- [ ] (P1) **Issue tracker integration**
  - [ ] Fetch issue by ID/URL; use as task spec
  - [ ] Post status/comment on completion (opt‑in)

- [ ] (P2) **Multi‑user workspaces**
  - [ ] Shared sessions; RBAC; secrets handling; audit logs

---

## 11) Memory, Retrieval & External Context

- [ ] (P1) **Vector memory stability**
  - [ ] FAISS/Milvus options; TTL/eviction policy; privacy controls
  - [ ] Background indexer for large repos; opt‑in

- [ ] (P1) **External context fetch**
  - [ ] `web.fetch` + content summarization; source citation in notes

- [ ] (P2) **Session snapshots**
  - [ ] Save/load condensed state; resumable tasks across restarts

---

## 12) Security & Privacy

- [ ] (P0) **Sandboxing & capabilities**
  - [ ] Per‑tool capability map; no network by default; allowlist domains
  - [ ] Resource limits (CPU/mem/fs); kill‑switch commands

- [ ] (P1) **Auditing**
  - [ ] Structured log of actions & decisions; export for review
  - [ ] Red‑team test suite; fuzz dangerous paths

---

## 13) Docs, Examples & Community

- [ ] (P0) **Quickstarts**
  - [ ] VS Code, Terminal, CI, Server mode step‑by‑step guides

- [ ] (P1) **Cookbook**
  - [ ] Bug fixing, refactors, migrations, release notes, PR hygiene

- [ ] (P1) **Contribution guide**
  - [ ] Plugin API docs, style guide, testing standards

---

## 14) Release Planning & Tracking

- [ ] (P0) **Roadmap w/ milestones**
  - [ ] v0.4: Web UI + subagents (MVP) + commit/PR flow
  - [ ] v0.5: Plugin ecosystem (MVP) + notebook & review mode
  - [ ] v0.6: IDE parity (VS Code/JetBrains) + broader sandboxes

- [ ] (P0) **Issue labels & tracking**
  - [ ] P0/P1/P2, Component (UI/CLI/Tools/Agents), Effort (S/M/L)
  - [ ] Weekly triage; public changelog
"""

path = "/mnt/data/Penguin-TODO.md"
with open(path, "w", encoding="utf-8") as f:
    f.write(content)

path