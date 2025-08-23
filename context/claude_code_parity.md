## Claude Code parity checklist for Penguin

This document tracks gaps and actionable steps for Penguin to reach feature parity with Claude Code across CLI, settings/configuration, workspace, interactive mode, slash commands, hooks, memory, and status line.

References: [Claude Code overview](https://docs.anthropic.com/en/docs/claude-code), [Settings](https://docs.anthropic.com/en/docs/claude-code/settings), [Terminal configuration](https://docs.anthropic.com/en/docs/claude-code/terminal-config), [Memory](https://docs.anthropic.com/en/docs/claude-code/memory), [Status line](https://docs.anthropic.com/en/docs/claude-code/statusline), [CLI reference](https://docs.anthropic.com/en/docs/claude-code/cli-reference), [Interactive mode](https://docs.anthropic.com/en/docs/claude-code/interactive-mode), [Slash commands](https://docs.anthropic.com/en/docs/claude-code/slash-commands), [Hooks](https://docs.anthropic.com/en/docs/claude-code/hooks)

### 1) CLI fundamentals and execution modes
- Current
  - Penguin uses Typer-based CLIs: `cli.py` (legacy) and `cli_new.py` (new entry). New CLI supports: `--old-cli`, `--no-tui`, `-p/--prompt`, `--version`, `--workspace`, `--model`, project routing, perf/profile, and basic `delegate`, `project`, and `task` sub-commands.
  - TUI launches when run with no args; headless runs via `-p/--prompt` implemented; `continue/resume` and autonomous run are placeholders.
- Gaps vs Claude Code
  - Missing fully functional autonomous/continuous run with time limits and resumable sessions.
  - No consolidated `config` subcommand UX for listing/setting project vs global settings (stubs exist in legacy CLI).
  - No explicit non-interactive fast-paths for all workflows (some exist: `--no-tui`, `-p`).
- Actions
  - Implement `run_autonomous` and `run_continue_resume` in `cli_new.py` to parity with interactive and headless flows.
  - Expose `penguin config get|set|add|remove --global` compatible with YAML-based config and env precedence.
  - Ensure `--no-tui` pathway supports piping and composability similar to Unix pipelines.

### 2) Settings, configuration, and precedence
- Current
  - YAML config with precedence: `PENGUIN_CONFIG_PATH` > user config `~/.config/penguin/config.yml` (or Windows equivalent) > repo `penguin/config.yml` > package default. See `penguin/config.py` (load_config, get_workspace_root, env overrides, diagnostics toggles).
  - Env var overrides for model/temperature/tokens and workspace path `PENGUIN_WORKSPACE`.
- Gaps vs Claude Code
  - No hierarchical project-local `.penguin/settings.*` or `.claude/settings.json` equivalent with team vs local split and managed policy layer.
  - No JSON-based allow/ask/deny permission model for tools/files (Claude Code permissions in `settings.json`).
  - No `config ...` CLI UX parity for on-the-fly configuration edits.
- Actions
  - Add project-local config file resolution: `.penguin/config.yml` and `.penguin/settings.local.yml` (gitignored). Merge precedence: managed policy (future) > user > project > package.
  - Define a permission policy schema (allow/ask/deny for ops like Bash/Edit/Read/WebFetch) and enforce in tool executors.
  - Implement `penguin config list|get|set|add|remove [-g|--global]` to modify YAML safely.

### 3) Working directory and workspace semantics
- Current
  - Penguin has a dedicated workspace root via config/env; CLI runs from current working directory and passes `--workspace` optionally. Workspace subdirs (`conversations`, `memory_db`, `logs`) are created on startup.
- Gaps vs Claude Code
  - Need explicit policy: operate primarily in current directory for code edits and repo actions, while keeping Penguin scratchpad/memory in `WORKSPACE_PATH`.
  - No explicit allowlist/denylist for directories outside CWD.
- Actions
  - Document execution model: CWD for project operations; `WORKSPACE_PATH` for assistant state and memory.
  - Add configurable working directories allowlist in config (mirrors Claude Code `additionalDirectories`).

### 4) Interactive mode and TUI
- Current
  - Textual TUI exists with slash commands and autocomplete (`command_registry`, `shared_parser`, TUI widgets). New CLI launches TUI by default.
- Gaps vs Claude Code
  - No managed status line integration with model/context/budget info akin to Claude Code status line.
  - No standardized REPL slash-command UX parity (help exists, but coverage needs expansion; some stubs).
  - Incomplete continue/resume and autonomous in TUI-compatible flows.
- Actions
  - Add status line API and configuration (toggle, custom command output, minimal token/cost info). See Status line reference.
  - Complete command coverage and help texts, align with docs and add tests for parser and autocompletion.

### 5) Slash commands
- Current
  - Slash-command parser/registry present; TUI shows `/help`, `/run`, `/models`, etc. Tests exist for parsing and registry.
- Gaps vs Claude Code
  - No standardized list mirroring Claude Code’s full set and semantics.
  - No policy/permission prompts for sensitive commands.
- Actions
  - Align command set with Claude Code slash commands; add aliases; integrate permission checks (ask/deny) and redaction.

### 6) Hooks (pre/post tool execution)
- Current
  - No general-purpose hooks system exposed for pre/post execution, though plugin/action infrastructure exists.
- Gaps vs Claude Code
  - Missing configurable hooks (e.g., run formatter after edits, block edits in protected paths) and a stable schema.
- Actions
  - Introduce hook points around tool invocations (Edit/Write/Read/Bash/WebFetch) with config-driven commands.
  - Provide a minimal hook schema compatible with YAML settings.

### 7) Memory
- Current
  - Rich memory system (providers: file/sqlite/faiss/lance/milvus, indexing, caching, monitoring). Workspace-backed.
- Gaps vs Claude Code
  - No simple on/off and budget controls in CLI for “memory mode” like Claude Code’s memory settings page; no explicit privacy toggles.
- Actions
  - Add memory enable/disable per session and retention settings in config and CLI flags.
  - Provide `penguin memory` subcommands for inspect/clear/policy and provider selection.

### 8) Status line
- Current
  - Not present as a feature; TUI shows panels and messages.
- Gaps vs Claude Code
  - Configurable status line with dynamic content or command output.
- Actions
  - Implement status line component with config under `tui.status_line` (type: off|basic|command, command: string).

### 9) Tools and permissions
- Current
  - Tools exist (browser, plugins, etc.). No centralized permission model.
- Gaps vs Claude Code
  - No `allow/ask/deny` enforcement; no default safe mode.
- Actions
  - Add a permission engine and default safe settings that can be relaxed via config or per-session flags.

### 10) Global vs project configuration commands
- Current
  - Setup wizard writes user config; no full CLI parity for live edits.
- Actions
  - Implement `penguin config` subcommand parity (list/get/set/add/remove; `--global` vs project), reflecting YAML structure and environment.

### 11) Enterprise/managed settings (future)
- Gaps
  - No managed policy file precedence or enterprise-specific enforcement.
- Actions
  - Design a managed policy file location and precedence with enforced denials (read-only), inspired by Claude Code managed settings.

### 12) Terminal configuration and pipeline ergonomics
- Gaps
  - Need explicit guarantees for streaming, stdin/stdout discipline, `NO_COLOR`, and quiet/verbose modes for scripts.
- Actions
  - Harden `-p/--prompt -` stdin path, add `--quiet/--verbose` consistency, ensure JSON output for machine use across commands.

### 13) Documentation and tests
- Actions
  - Update `context/CLI.md` and add docs for settings, permissions, hooks, status line, and slash commands.
  - Add tests: config precedence, permission enforcement, hook execution, CLI JSON mode, TUI status line rendering.

---

Quick mapping of key Penguin components
- CLI: `penguin/cli/cli_new.py`, legacy in `penguin/cli/cli.py` and `old_cli.py`
- Config and workspace: `penguin/config.py`; workspace helpers in `penguin/workspace/workspace.py`
- TUI and slash commands: `penguin/cli/tui.py`, `penguin/cli/command_registry.py`, `penguin/cli/shared_parser.py`, `penguin/cli/commands.yml`
- Memory: `penguin/memory/*` (providers, indexing, caching)
- Plugins/actions: `penguin/utils/plugin_parser.py`, `penguin/plugins/*`

Notes on working directory vs workspace
- Operate on project files in the current directory to match Claude Code’s terminal-first model.
- Keep assistant state, memory, logs, and conversations in `WORKSPACE_PATH` (configurable), with clear separation and permission policies.


