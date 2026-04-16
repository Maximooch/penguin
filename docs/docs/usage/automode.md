# Automode / RunMode

Penguin does support autonomous execution today, but this surface is still being cleaned up and audited.

Current public CLI truth:
- `--run <TASK_OR_PROJECT>` starts RunMode for a specific task/project target
- `--247` / `--continuous` runs continuous mode until manually stopped
- continuous mode can also be entered without an explicit task target

Important caveat:
- command ergonomics and loop ownership between `RunMode` and `Engine` are tracked as follow-up work
- this page is intentionally minimal until that audit lands, so we do not teach command semantics that may still change

For current command syntax, prefer:
- `docs/docs/usage/cli_commands.md`
- `context/tasks/todo.md` (follow-up PR map)
