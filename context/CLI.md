# CLI Argument Parsing Unification Plan

## Objective
Adopt a TUI‑first experience while keeping a powerful headless CLI. The new Typer‑based `cli.py` becomes a slim entrypoint that launches the TUI by default, or runs headless commands. The legacy Rich CLI is preserved as `old_cli.py` and can be invoked via `--old-cli`.

## Scope
- Single source of truth for in-app command names, parameters, and help (backed by `commands.yml` and `CommandRegistry`).
- Shared parsing/validation and usage generation for commands (slash commands and CLI-forwarded subcommands).
- Keep Typer for top-level process flags (`-p/--prompt`, `--model`, `--247`, `--workspace`, etc.).

Non-goals
- Replace Typer for process-level argument parsing.
- Change existing CLI flags or break current workflows.

## Artifacts
- `penguin/penguin/cli/cli.py` (NEW slim Typer CLI)
  - Defaults to TUI when no headless flags/subcommands are used
  - Global flags: `--old-cli`, `--no-tui`, `-p/--prompt`, `--output-format`, `--version`, `--project`
  - Existing globals preserved: `--continue/--resume`, `--run/--247`, `--time-limit`, `--description`, `--model/-m`, `--workspace/-w`, `--no-streaming`, `--fast-startup`
  - Log control: `--quiet`, `--verbose`, `--no-color`
  - Headless commands: `setup`, `delegate`, `project`, `task`, `perf-test`, `profile`
- `penguin/penguin/cli/old_cli.py` (legacy Rich CLI; unchanged)
- `penguin/penguin/cli/shared_parser.py` (DONE)
  - `parse/suggest/usage` using `CommandRegistry` for consistent parsing

## Integration Plan
1) TUI (already done)
- Autocomplete: use registry suggestions.
- Help: render from registry.
- Routing: parse via shared parser, then delegate to interface or TUI-local actions.

2) CLI (Typer, slim outer layer)
- If any headless flags/commands are present (`--old-cli`, `--no-tui`, `-p/--prompt`, `setup`, `delegate`, `project`, `task`, `perf-test`, `profile`) ⇒ run headless and exit
- Otherwise ⇒ run TUI by default (`penguin.cli.tui.TUI.run()`)
- `--old-cli` imports and runs legacy `old_cli.py`
- `--project <name>` routes delegate/project/task to named project; if omitted, tasks are independent

3) Command specs
- Continue using `commands.yml` as canonical.
- Support config layering (built-in → repo → user), hot-reload later.

## Key Behaviors
- **Global --project flag**: Routes tasks/delegate to specified project; independent if omitted
- **Exit codes**: Non-zero on errors; stable codes for automation
- **Output formats**: Text by default; `--output-format json` for stable automation
- **Context handling**: Accept local paths and URLs for delegate; paths attached, URLs stored as metadata
- **Security**: Confirm force deletes; validate paths; never log secrets
- **Performance**: Lazy imports; default fast_startup=True for one-shots
- **Signal handling**: Graceful SIGINT/SIGTERM handling with appropriate exit codes

## Error & UX
- On parse/validation error: show generated usage + nearest matches.
- Consistent errors across TUI and CLI.

## Testing
- Unit: parser (valid/missing/typed args), suggestions, usage generation.
- Golden: help text snapshots.
- E2E: a few CLI flows routed through shared executor.

## Phases
- Phase 1 (now)
  - Land slim `cli.py` with: global flags, prompt, setup, delegate, project/task, perf/profile, default‑to‑TUI
  - Keep `old_cli.py` frozen; wire `--old-cli`
- Phase 2
  - Migrate CLI subcommands to reuse `SharedParser` where it helps (normalization/usage)
  - Add dynamic completers and config layering for commands.yml (optional)
- Phase 3
  - Add background jobs/cancellation hooks for long headless runs; telemetry toggles

## Risks
- Duplication with Typer for some command trees; mitigate by forwarding to shared executor progressively.
- Performance of suggestions with large specs; mitigate via caching and prefix indexing.
- Plugin compatibility/versioning; add spec version and adapters.

## Open Questions
- Final location for user-level `commands.yml` (same dir as `config.yml`); merge order and precedence.
- Telemetry redaction policy for args.
- i18n strategy for usage/help.
