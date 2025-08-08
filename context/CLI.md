# CLI Argument Parsing Unification Plan

## Objective
Create a thin, shared parser so both the shell CLI (`cli.py` via Typer) and the TUI use the same command specs, without removing Typer as the outer shell for process arguments and environment flags.

## Scope
- Single source of truth for in-app command names, parameters, and help (backed by `commands.yml` and `CommandRegistry`).
- Shared parsing/validation and usage generation for commands (slash commands and CLI-forwarded subcommands).
- Keep Typer for top-level process flags (`-p/--prompt`, `--model`, `--247`, `--workspace`, etc.).

Non-goals
- Replace Typer for process-level argument parsing.
- Change existing CLI flags or break current workflows.

## Artifacts (proposed)
- `penguin/penguin/cli/shared_parser.py`
  - `parse(command_str: str) -> ParsedCommand` (name, args, errors)
  - `format_usage(command_name: str) -> str`
  - `suggest(partial: str) -> list[str]`
  - Thin façade over `CommandRegistry` with stricter validation and usage text.
- `penguin/penguin/cli/shared_executor.py` (optional)
  - `execute(parsed: ParsedCommand, interface: PenguinInterface, callbacks=...)` → Dict
  - Bridges registry handlers to interface methods or TUI-local actions.

## Integration Plan
1) TUI (already done)
- Autocomplete: use registry suggestions.
- Help: render from registry.
- Routing: parse via shared parser, then delegate to interface or TUI-local actions.

2) CLI (Typer stays)
- Typer continues to parse process flags and known subcommands.
- For slash-like or registry-backed commands, Typer forwards the remaining string to `shared_parser.parse()` then executes via `shared_executor`.
- Gradually migrate Typer subcommands to call the shared executor (keeping flags where useful for UX).

3) Command specs
- Continue using `commands.yml` as canonical.
- Support config layering (built-in → repo → user), hot-reload later.

## Error & UX
- On parse/validation error: show generated usage + nearest matches.
- Consistent errors across TUI and CLI.

## Testing
- Unit: parser (valid/missing/typed args), suggestions, usage generation.
- Golden: help text snapshots.
- E2E: a few CLI flows routed through shared executor.

## Phases
- Phase 1
  - Implement `shared_parser.parse/suggest/usage` using `CommandRegistry`.
  - Add validation (required args, basic type coercion).
- Phase 2
  - Introduce `shared_executor` and wire TUI (done) + optional CLI pathways.
  - Unify error messages in both UIs.
- Phase 3
  - Config layering and optional hot-reload for `commands.yml`.
  - Dynamic value completers (models, conversations) with caching.
- Phase 4
  - Cancellation hooks, background jobs, telemetry hooks.

## Risks
- Duplication with Typer for some command trees; mitigate by forwarding to shared executor progressively.
- Performance of suggestions with large specs; mitigate via caching and prefix indexing.
- Plugin compatibility/versioning; add spec version and adapters.

## Open Questions
- Final location for user-level `commands.yml` (same dir as `config.yml`); merge order and precedence.
- Telemetry redaction policy for args.
- i18n strategy for usage/help.
