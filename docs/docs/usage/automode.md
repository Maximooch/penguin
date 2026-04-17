# Automode / RunMode

Penguin supports autonomous execution today through **RunMode**.

This surface is still under cleanup, but the current public contract is now explicit enough to document honestly.

## Current public CLI truth

- `--run <TASK_OR_PROJECT>` starts autonomous execution for a specific task/project target.
- `--247` / `--continuous` starts continuous RunMode.
- Continuous mode can also be entered **without** an explicit task target.
- `--time-limit <MIN>` currently means an **explicit CLI-supplied cap** on RunMode duration; it should not be read as proof that blueprint/task/project-defined timing fields are surfaced equivalently through this CLI.

## Two continuous-mode contracts exist today

### 1. Project-scoped continuous mode
When RunMode is operating in project scope, it works the **ready frontier** of project tasks.

Important behavior:
- it may stop honestly when no tasks are ready
- that is not a crash or silent failure
- this is the correct outcome when the current project work frontier is exhausted

### 2. Non-project continuous mode
When RunMode is used without project/task graph scope, it may continue **exploratorily** by determining next steps.

This mode is intentionally looser:
- it is useful when the user has a direction but not a strict task graph
- it should be understood as exploratory/autonomous continuation, not DAG-driven workflow execution
- the expectation is that Penguin documents its progress/decisions in journals/context artifacts where appropriate

## Clarification outcomes are non-terminal

RunMode does **not** always end in simple completion.

It can also surface:
- waiting for clarification / user input
- explicit time-limit stop
- honest idle/no-ready-work stop

That distinction matters. A clarification wait is not the same thing as successful completion.

## Time-limit truth

Current honest contract:
- CLI `--time-limit` is passed through to RunMode
- actual wall-clock enforcement exists in **continuous mode**
- blueprint/task/project timing fields exist elsewhere in Penguin, but are not yet unified into a single public RunMode time-limit contract

## Related docs

For command syntax and examples, see:
- `docs/docs/usage/cli_commands.md`

For current follow-up planning around RunMode command truth and loop ownership, see:
- `context/tasks/runmode-command-loop-audit.md`
- `context/tasks/runmode-command-truth-pr1-checklist.md`
