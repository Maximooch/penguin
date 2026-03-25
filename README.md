```
ooooooooo.                                                 o8o
`888   `Y88.                                               `"'
 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo  ooo. .oo.
 888ooo88P'  d88' `88b `888P"Y88b  888' `88b  `888  `888  `888  `888P"Y88b
 888         888ooo888  888   888  888   888   888   888   888   888   888
 888         888    .o  888   888  `88bod8P'   888   888   888   888   888
o888o        `Y8bod8P' o888o o888o `8oooooo.   `V88V"V8P' o888o o888o o888o
                                   d"     YD
                                   "Y88888P'
```

[![PyPI version](https://img.shields.io/pypi/v/penguin-ai.svg)](https://pypi.org/project/penguin-ai/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/Maximooch/penguin/publish.yml?branch=main)](https://github.com/Maximooch/penguin/actions)
[![Documentation Status](https://img.shields.io/badge/docs-latest-brightgreen.svg)](https://penguin-rho.vercel.app)
[![Downloads](https://img.shields.io/pypi/dm/penguin-ai.svg)](https://pypi.org/project/penguin-ai/)

Penguin is an open-source coding agent built on a scalable cognitive architecture runtime.

It is designed for long-running, tool-using, multi-agent software workflows: from
interactive coding in the TUI to persistent sessions, subagent delegation, and
API-driven automation. Penguin combines a coding-focused agent runtime with durable
state, workspace-aware tools, and multiple interfaces on top of the same core.

## Why Penguin

- Purpose-built for software engineering workflows, with coding tools, sessions, and subagents.
- Stateful runtime: sessions, checkpoints, tool history, and replayable transcripts.
- Context Window Manager: long sessions stay coherent through category-aware token budgeting,
  truncation, and replay, preserving recency and message-category priorities across long-running sessions.
- Multi-agent orchestration: planner/implementer/QA patterns, subagents, and scoped delegation.
- Multiple surfaces: TUI, CLI, web API, and Python client on the same backend.
- OpenCode-compatible TUI path: Penguin web/core now powers an OpenCode-style terminal UX.

## Quick Start

```bash
# Recommended install
pip install penguin-ai

# Set a model provider key (OpenRouter is the easiest starting point)
export OPENROUTER_API_KEY="your_api_key"

# Launch Penguin TUI
penguin
```

Other entrypoints:

- `penguin` - interactive Penguin TUI launcher
- `ptui` - direct TUI alias
- `penguin-cli` - headless CLI for automation and scripts
- `penguin-web` - FastAPI server for web/API usage

## What You Get

- Coding workflow tools: file reads/writes/diffs, shell commands, test execution, search,
  code analysis, and background process management.
- Context Window Manager: category-based token budgets, multimodal truncation, and live usage
  reporting to keep histories within model limits. This supports theoretically infinite sessions.
- Persistent memory and file-backed context: declarative notes, summary notes, `context/`
  artifacts, docs cache, and daily journal continuity.
- Multi-agent execution: isolated or shared-context subagents, delegation, planner/
  implementer/QA patterns, and background task execution.
- Browser and research support: web search plus browser automation for documentation,
  web workflows, and UI testing.
- Session durability: checkpoints, rollback, branching, transcript replay, and long-running
  task continuity.
- Project and task orchestration backed by SQLite, including todo tracking and Run Mode.
- Native and gateway model support across OpenAI, Anthropic, and OpenRouter by default, with LiteLLM available as an optional extra.

## Interfaces

Penguin exposes the same runtime through several surfaces:

- `penguin` / `ptui` - terminal-first coding workflow with streaming, tools, and session navigation.
- `penguin-cli` - scriptable CLI interface for prompts, tasks, config, and automation.
- `penguin-web` - REST + WebSocket/SSE backend for the TUI and custom integrations.
- Python API - `PenguinAgent`, `PenguinClient`, and `PenguinAPI` for embedding Penguin in code.

### Quick Python Example

```python
from penguin import PenguinAgent

with PenguinAgent() as agent:
    response = agent.chat("Summarize the current task charter")
    print(response["assistant_response"])
```

## Installation

### Recommended

```bash
# Default install: CLI + web runtime + OpenCode TUI launcher support
pip install penguin-ai

# Compatibility alias for older install commands
pip install penguin-ai[web]

# Compatibility alias for older install commands
pip install "penguin-ai[tui]"

# Legacy Textual prototype / experimental UI support
pip install "penguin-ai[legacy_tui]"

# Full feature set
pip install penguin-ai[all]
```

### Development

```bash
git clone https://github.com/Maximooch/penguin.git
cd penguin/penguin
pip install -e .[dev,test]
```

### Extras

| Extra | Description |
|---|---|
| `[tui]` | Compatibility alias; default install already includes TUI launcher runtime |
| `[web]` | Compatibility alias; default install already includes web runtime |
| `[legacy_tui]` | Legacy Textual prototype / experimental UI support |
| `[llm_litellm]` | Optional LiteLLM support for legacy/custom gateway workflows |
| `[memory_faiss]` | FAISS vector search + embeddings |
| `[memory_lance]` | LanceDB vector database |
| `[memory_chroma]` | ChromaDB integration |
| `[browser]` | Browser automation (Python 3.11+ only) |
| `[all]` | Everything above |

## TUI Runtime

The Penguin TUI launcher supports both development and packaged installs.

- In a source checkout, `penguin` prefers local `penguin-tui/packages/opencode` sources.
- Outside a source checkout, it bootstraps a cached sidecar binary under `~/.cache/penguin/tui`.
- Stable installs prefer a sidecar that matches the installed Penguin version.
- You can override the source or binary path when needed:

```bash
# Force local source mode
export PENGUIN_OPENCODE_DIR="/path/to/penguin/penguin-tui/packages/opencode"

# Force a specific sidecar binary
export PENGUIN_TUI_BIN_PATH="/path/to/opencode"
```

You can also override the release endpoint for staging/testing with `PENGUIN_TUI_RELEASE_URL`.

## Common Commands

```text
/models                 # interactive model selector
/model set <MODEL_ID>   # set a specific model
/stream on|off          # toggle streaming
/checkpoint [name]      # save a checkpoint
/checkpoints [limit]    # list checkpoints
/rollback <checkpoint>  # restore a checkpoint
/tokens                 # token usage summary
/run task "Name"       # start a specific task
```

## Architecture

Penguin is structured as a runtime for long-lived agent workflows.

- `PenguinCore` coordinates configuration, interfaces, events, and runtime state.
- `Engine` runs the reasoning loop, model calls, and tool orchestration.
- `ConversationManager` persists sessions, checkpoints, and conversation state.
- `ContextWindowManager` manages long-session token budgets with category-aware truncation,
  multimodal handling, and replay-friendly context continuity.
- `ToolManager` and `ActionExecutor` run workspace-aware tools and action pipelines.
- CLI, TUI, web, and Python APIs all sit on top of the same backend services.

Penguin's long-term direction is a scalable cognitive architecture runtime: a persistent
agent kernel with userland surfaces for sessions, tools, orchestration, and observability.

Read more:

- `architecture.md`
- `context/architecture/Penguin_SCAR_80_20_Roadmap.md`
- `context/architecture/tui-opencode-implementation.md`

## Version Highlights

### v0.6.2.1

- Canonical file editing now centers on `read_file`, `write_file`, `patch_file`, and `patch_files`.
- JSON-first edit payloads, generated prompt docs, and centralized compatibility aliases keep parser, tools, and UI metadata aligned.
- File edit validation, multifile permissions/rollback, overwrite behavior, and diff output consistency are materially more reliable.
- OpenCode-compatible Penguin TUI flow remains backed by Penguin web/core.

## Documentation

- [Official Documentation](https://penguin-rho.vercel.app)
- [Release Notes](https://github.com/Maximooch/penguin/releases)
- `architecture.md`
- `context/architecture/Penguin_SCAR_80_20_Roadmap.md`

## Contributing

```bash
git clone https://github.com/Maximooch/penguin.git
cd penguin/penguin
pip install -e .[dev,test]
pytest -q
```

- Open issues: [GitHub Issues](https://github.com/Maximooch/penguin/issues)
- Discuss ideas: [GitHub Discussions](https://github.com/Maximooch/penguin/discussions)

## Support

- [Documentation](https://penguin-rho.vercel.app)
- [Examples and tutorials](https://penguin-rho.vercel.app/docs/usage/)
- [Bug reports](https://github.com/Maximooch/penguin/issues/new?template=bug_report.md)
- [Feature requests](https://github.com/Maximooch/penguin/issues/new?template=feature_request.md)

## License

Licensing in this repository is split by component:

- `penguin/` and the main Penguin runtime are licensed under the GNU Affero General Public
  License v3.0 or later.
- `penguin-tui/` contains OpenCode-derived TUI code that remains MIT-licensed; see
  `penguin-tui/LICENSE`.
- Read the official [GNU AGPL v3 text](https://www.gnu.org/licenses/agpl-3.0.en.html)

Enterprise licensing without AGPL copyleft requirements is under consideration. If
you are interested, contact MaximusPutnam@gmail.com.

## Acknowledgments

Built upon insights from:

- [CodeAct](https://arxiv.org/abs/2402.01030)
- [OpenCode](https://github.com/sst/opencode) for the upstream TUI and UX foundation used in `penguin-tui/`
- [Claude-Engineer](https://github.com/Doriandarko/claude-engineer)
- [Aider](https://github.com/paul-gauthier/aider)
- [RawDog](https://github.com/AbanteAI/rawdog)
