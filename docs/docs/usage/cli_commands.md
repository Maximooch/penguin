# Penguin CLI – Command Reference (v0.6.x)

Penguin now exposes multiple terminal entrypoints on top of the same runtime:

- `penguin` — default launcher for the interactive TUI
- `ptui` / `penguin-tui` — explicit aliases for the same TUI runtime
- `penguin-cli` — headless/scriptable CLI for prompts, config, projects, and automation

This page documents the currently implemented command surface and calls out where older docs were too optimistic.

---

## Getting help
```bash
# Default launcher help
penguin --help

# Headless CLI help
penguin-cli --help

# Help for a specific sub-command
penguin-cli project --help
penguin-cli project task --help
penguin-cli config --help
```

---

## Quick start
### 1. Interactive chat (default TUI)
```bash
# Start an interactive chat session
penguin

# Equivalent explicit TUI aliases
ptui
penguin-tui
```

### 2. One-off prompts (non-interactive)
```bash
# Ask a single question (prints assistant reply and exits)
penguin-cli -p "Explain async/await in Python"

# Read the prompt from stdin (use "-" as the placeholder)
echo "Give me a limerick about penguins" | penguin-cli -p -
```

The following global flags can be combined with either interactive or non-interactive mode:

| Flag | Description |
|------|-------------|
| `--model/-m <MODEL_ID>` | Override the model configured in *penguin.yml* |
| `--workspace/-w <PATH>` | Use a different workspace directory |
| `--no-streaming`        | Disable token-by-token streaming output |
| `--fast-startup`        | Skip memory indexing for faster launch |
| `--continue/-c`         | Continue the most recent conversation in interactive mode |
| `--resume <SESSION_ID>` | Resume a specific saved conversation |
| `--run <TASK_NAME>`     | Start autonomous execution for a specific task/project target |
| `--247 / --continuous`  | Run continuously (24/7 mode); project-scoped runs work the ready frontier, while non-project runs may continue exploratorily |
| `--time-limit <MIN>`    | Set an explicit CLI-supplied cap on RunMode duration |
| `--version/-V`          | Print Penguin version and exit |

---

## Sub-commands (Typer / headless CLI)

Most sub-commands are exposed through `penguin-cli`. If you are scripting Penguin, use that binary instead of assuming the interactive TUI launcher will behave like a classic CLI.

### `project`
Project management helpers (backed by `ProjectManager`).

| Command | Summary |
|---------|---------|
| `penguin-cli project create <NAME> [--description/-d TEXT]` | Create a new project using Penguin's managed default workspace |
| `penguin-cli project create <NAME> --workspace /exact/path` | Create a new project using the exact workspace path you provide |
| `penguin-cli project list` | List existing projects |
| `penguin-cli project delete <PROJECT_ID> [--force/-f]` | Delete a project |

Workspace semantics for project creation:
- `--workspace` uses the **exact provided path**. Penguin does not silently create a child directory under that path.
- When `--workspace` is omitted, Penguin uses its managed default workspace path.
- Project creation output distinguishes:
  - `Workspace (explicit): ...`
  - `Workspace (default): ...`
  - `Execution root: ...`

Tasks are namespaced under a project:

| Command | Summary |
|---------|---------|
| `penguin-cli project task create <PROJECT_ID> <TITLE>` | Create a task |
| `penguin-cli project task list [<PROJECT_ID>] [--status/-s STATUS]` | List tasks (optionally filtered) |
| `penguin-cli project task start <TASK_ID>` | Move task into the **active** state |
| `penguin-cli project task complete <TASK_ID>` | Approve a task that is **pending review** and mark it completed |
| `penguin-cli project task delete <TASK_ID> [--force/-f]` | Delete task |

Status filters are case-insensitive and use the current task lifecycle values: `active`, `running`, `pending_review`, `completed`, `failed`, `blocked`, and `cancelled`.

### `config`
Manage the Penguin configuration file and first-run setup wizard.

| Command | What it does |
|---------|--------------|
| `penguin-cli config setup`        | Run (or re-run) the interactive setup wizard |
| `penguin-cli config edit`         | Open the config file in your default editor |
| `penguin-cli config check`        | Validate that required keys are present |
| `penguin-cli config test-routing` | Debug provider/model routing logic |
| `penguin-cli config debug`        | Print an extended diagnostic report |

### Developer utilities
| Command | Purpose |
|---------|---------|
| `penguin-cli perf-test [-i N]` | Benchmark startup time with and without *fast-startup* |
| `penguin-cli profile [-o FILE] [--view]` | Launch Penguin under `cProfile` and save results |
| `penguin-cli chat` | Explicit synonym for starting interactive chat |
---

## In‑Chat Commands (Interactive Session)
When running `penguin` interactively, you can use slash‑style commands to control models, streaming, context, checkpoints, and Run Mode. Type `/help` to list all commands.

### Models & Streaming
```text
/models                 # Interactive model selector
/model set <MODEL_ID>   # Set a specific model (provider/model ID)
/stream on|off          # Toggle token streaming
```

### Checkpoints & Branching
```text
/checkpoint [name] [description]  # Save a conversation checkpoint
/checkpoints [limit]               # List checkpoints
/rollback <checkpoint_id>         # Restore to a checkpoint
/branch <checkpoint_id> [name]    # Branch a new conversation from a checkpoint
```

### Context & Diagnostics

The `/context` command allows you to load documentation and reference files into the conversation. Files can be loaded from multiple locations:

- **Workspace `context/` folder**: The main location for context files in your workspace
- **Project root**: Automatically discovers common documentation files (README.md, ARCHITECTURE.md, etc.)
- **Current directory**: Any file in your current working directory

```text
/context list                     # List available context files from all locations
/context load <file>              # Load a context file into conversation
/context add <file>               # Alias for /context load
```

**Examples:**
```text
/context add architecture.md      # Load from project root or context/
/context load FILE_PICKER_FEATURE_PLAN.md  # Load from context/ folder
/context list                     # See all available files
```

Additional context management commands:
```text
/context write|edit|remove|note   # Manage context artifacts
/context clear                    # Clear current context
```

### Token Monitoring
```text
/tokens                           # Token usage summary
/tokens detail                    # Detailed token breakdown
/truncations [limit]              # Recent context window trimming events
```

### Run Mode (Autonomous Execution)
```text
/run task "Name" [description]           # Start autonomous execution for a specific task target
/run continuous ["Name" [description]]   # Continuous Run Mode (public product-language alias: --247)
/run stop                                # Stop current Run Mode execution (if supported)
```

Current truth for continuous mode:
- project-scoped runs work the ready frontier and may stop honestly when no tasks are ready
- non-project runs may continue exploratorily by determining next steps
- `--time-limit` currently represents an explicit CLI-supplied run cap; it should not be read as proof that blueprint/task-defined timing fields are fully surfaced through this CLI

When Run Mode needs human input, the interactive CLI now surfaces both:
- `clarification_needed` status
- `clarification_answered` acknowledgement

That keeps the pause/resume loop visible instead of making the CLI look stuck.

## Examples
```bash
# Create a project and a task, then start the task
penguin-cli project create "Demo" -d "Playground project"

# Create a project with an explicit exact-path workspace
penguin-cli project create "Demo" --workspace /tmp/demo-workspace

# List projects and copy the ID from the table
penguin-cli project list

# Create and start a task (replace <PROJECT_ID> and <TASK_ID>).
# Task commands are namespaced under `project task`, not top-level `task`.
penguin-cli project task create <PROJECT_ID> "Research llama models"
penguin-cli project task list <PROJECT_ID>
penguin-cli project task start <TASK_ID>
```

---

## Missing features
Earlier versions of the docs referenced commands such as `penguin memory`, `penguin db`, advanced task dependency graphs, and full web-server management. These features are **work-in-progress** and are **not** available in the current release. Attempting to run them will result in a "No such command" error.
---

*Last updated: April 15, 2026*  
If you find inaccuracies, please open an issue.
