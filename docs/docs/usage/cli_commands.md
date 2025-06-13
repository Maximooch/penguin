# Penguin CLI – Current Command Reference (v0.1.x)

> **NOTE**  
> Penguin is under active development.  The command-line interface already offers a solid core, but many advanced features shown in earlier drafts of the docs have **not been implemented yet**.  This page only documents functionality that is _actually available today_.  Anything else should be considered experimental and subject to change.

---

## Getting help
```bash
# Global help
penguin --help

# Help for a specific sub-command
penguin project --help
penguin project task --help
penguin config --help
```

---

## Quick start
### 1. Interactive chat (default)
```bash
# Start an interactive chat session
penguin
```

### 2. One-off prompts (non-interactive)
```bash
# Ask a single question (prints assistant reply and exits)
penguin -p "Explain async/await in Python"

# Read the prompt from stdin (use "-" as the placeholder)
echo "Give me a limerick about penguins" | penguin -p -
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
| `--run <TASK_NAME>`     | Execute a stored task in autonomous **run-mode** |
| `--247 / --continuous`  | Keep run-mode running continuously until interrupted |
| `--time-limit <MIN>`    | Set a time limit for run-mode |
| `--version/-v`          | Print Penguin version and exit |

---

## Sub-commands

### `project`
Project management helpers (backed by `ProjectManager`).

| Command | Summary |
|---------|---------|
| `penguin project create <NAME> [--description/-d TEXT]` | Create a new project |
| `penguin project list` | List existing projects |
| `penguin project delete <PROJECT_ID> [--force/-f]` | Delete a project |

Tasks are namespaced under a project:

| Command | Summary |
|---------|---------|
| `penguin project task create <PROJECT_ID> <TITLE>` | Create a task |
| `penguin project task list [<PROJECT_ID>] [--status/-s STATUS]` | List tasks (optionally filtered) |
| `penguin project task start <TASK_ID>` | Mark task **running** |
| `penguin project task complete <TASK_ID>` | Mark task **completed** |
| `penguin project task delete <TASK_ID> [--force/-f]` | Delete task |

Status values can be `pending`, `active`, `completed`, or `failed`.

### `config`
Manage the Penguin configuration file and first-run setup wizard.

| Command | What it does |
|---------|--------------|
| `penguin config setup`        | Run (or re-run) the interactive setup wizard |
| `penguin config edit`         | Open the config file in your default editor |
| `penguin config check`        | Validate that required keys are present |
| `penguin config test-routing` | Debug provider/model routing logic |
| `penguin config debug`        | Print an extended diagnostic report |

### Developer utilities
| Command | Purpose |
|---------|---------|
| `penguin perf-test [-i N]` | Benchmark startup time with and without *fast-startup* |
| `penguin profile [-o FILE] [--view]` | Launch Penguin under `cProfile` and save results |
| `penguin chat` | Explicit synonym for starting interactive chat (identical to running `penguin` with no arguments) |

---

## Examples
```bash
# Create a project and a task, then start the task interactively
penguin project create "Demo" -d "Playground project"
PROJECT_ID=$(penguin project list --json | jq -r '.[0].ID')

penguin project task create "$PROJECT_ID" "Research llama-models"
TASK_ID=$(penguin project task list $PROJECT_ID --json | jq -r '.[0].ID')

penguin project task start $TASK_ID
```

---

## Missing features
Earlier versions of the docs referenced commands such as `penguin memory`, `penguin db`, advanced task dependency graphs, and full web-server management.  These features are **work-in-progress** and are **not** available in the current release.  Attempting to run them will result in a "No such command" error.

---

*Last updated: June 13th 2025*  
Please open an issue on GitHub if you find any inaccuracies.

