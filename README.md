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
# Recommended: use uv for less environment/package-management hassle,
# faster installs/syncs, and support for this repo's safer dependency workflow.
uv tool install penguin-ai

# Alternative: plain pip still works
pip install penguin-ai

# Set a model provider key (OpenRouter is the easiest starting point)
export OPENROUTER_API_KEY="your_api_key"

# Launch Penguin
penguin
```

`uv` is the recommended path for most users: it is generally faster than `pip`, keeps
Python environment management simpler, and supports this repo's `exclude-newer` safety rail
for dependency resolution in development workflows.

Other entrypoints:

- `penguin` - interactive Penguin TUI launcher
- `ptui` - direct TUI alias
- `penguin-cli` - headless CLI for automation and scripts
- `penguin-web` - FastAPI server for web/API usage

### Web Server Logs

`penguin-web` writes one server log file per web server run by default:

```text
{PENGUIN_WORKSPACE:-~/penguin_workspace}/server-logs/penguin-web-<timestamp>-<pid>.txt
```

The log file includes Penguin startup/application logs plus Uvicorn error and access
logs, with per-file rotation enabled. Override the directory, force a specific file,
or disable this behavior with:

```bash
export PENGUIN_WEB_LOG_DIR="/path/to/server-logs"
export PENGUIN_WEB_LOG_FILE="/path/to/logs.txt"
export PENGUIN_WEB_LOG_ENABLED=false
```

For local development and verification, keep the primary runtime on port `9000`
untouched and start the isolated test server on `127.0.0.1:8080`:

```bash
uv run python scripts/run_runtime_reliability_server.py
```

The runner creates a unique test workspace, isolates mutable runtime stores, and
refuses to replace an existing process on port `8080`. Use `--debug` for reload mode
or `--describe` to inspect the resolved paths without starting a server.

For a repeatable fresh-session and large-persisted-session timing baseline without a
live provider or network listener, run:

```bash
uv run python scripts/benchmark_runtime_reliability.py \
  --base-directory /tmp/penguin-runtime-baselines
```

The harness uses the same isolated test-role storage contract, calls the production
chat handler directly, and records provider, tool, context, session, ledger, and
end-to-end stages. Its JSON output states the remaining gap to a full PenguinCore and
HTTP-socket benchmark.

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

### Web/API Surface Notes

- Task/project endpoints now expose current runtime state rather than only legacy task summaries.
  - Task payloads include `status`, `phase`, `dependencies`, `dependency_specs`, `artifact_evidence`, `recipe`, `metadata`, and `clarification_requests` where relevant.
- `POST /api/v1/tasks/{task_id}/execute` now routes through `RunMode`, so non-terminal outcomes like `waiting_input` and clarification-needed results are preserved instead of being flattened into fake completion/failure states.
- `POST /api/v1/tasks/{task_id}/clarification/resume` answers the latest open clarification request and resumes execution through the same `RunMode` lifecycle.
- `GET /api/v1/events/sse` streams OpenCode-compatible events and now includes session-scoped clarification status visibility for web clients.
- REST and WebSocket chat return explicit terminal truth (`completed`, `state`,
  `terminal_reason`, partial output, recovery/cancellation details, and
  iteration/action counts). A 2xx/`complete` transport envelope is not treated
  as Penguin success unless `completed` is true.
- Recoverable chat stops offer Retry/Resume only through a server-generated,
  durably persisted one-shot continuation. Clients do not guess or
  automatically send a plain-text `resume` turn.
- `PenguinAPI.run_task(...)` and `PenguinAPI.resume_with_clarification(...)` are aligned with the web route behavior so programmatic callers see the same lifecycle truth.

These surfaces are still under active audit, but the current direction is explicit: web/API consumers should receive the same task/clarification truth that the backend runtime uses internally.

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

# Safe default: respects `[tool.uv] exclude-newer = "7 days"`
uv sync

# Editable dev/test install via pip still works if you prefer it
pip install -e .[dev,test]
```

### Safer `uv` Installs

This repo configures `uv` to ignore package releases newer than 7 days by default:

```toml
[tool.uv]
exclude-newer = "7 days"
```

That gives the ecosystem a little time to detect and yank malicious releases before you
pull them in. It's a useful guardrail, not a complete supply-chain strategy.

Convenience shortcuts:

```bash
make sync-safe    # use the default 7-day delay
make lock-safe    # refresh lockfile with the 7-day delay
make lock-latest  # intentionally override and resolve newest compatible releases
make sync-latest  # resolve + sync using newest compatible releases
```

Under the hood, the `latest` targets override the project default with `--exclude-newer 2999-12-31T23:59:59Z`.

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
| `[mcp]` | Model Context Protocol client/server dependencies (Python 3.10+ for the MCP SDK) |
| `[browser]` | Browser automation support. Installs PyDoll fallback; browser-harness must be installed from a local/source checkout because it is not published on PyPI yet. |
| `[pydoll]` | PyDoll browser automation fallback only |
| `[all]` | Everything above that is available from PyPI |

Browser-harness is Penguin's preferred `browser_*` backend on this branch, but it
is currently a local/source dependency rather than a PyPI package. For local
browser-harness testing, install Penguin's browser extra for the PyPI-available
fallback and then install browser-harness into the same environment from a source
checkout:

```bash
pip install "penguin-ai[browser]"
pip install -e /path/to/browser-harness
```

If browser-harness is unavailable, the `pydoll_browser_*` tools remain available
as the compatibility fallback.

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

- `PenguinCore` handles construction, delegation, and compatibility methods.
- `penguin.core_runtime` owns extracted runtime helpers for processing, model/provider behavior, checkpoints, token usage, action mapping, OpenCode/TUI bridging, diagnostics, and compatibility shims.
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
- `context/tasks/Penguin_SCAR_80_20_Roadmap.md`
- `context/tasks/tui-opencode-implementation.md`

## Version Highlights

### v0.9.1

- Added day-one GPT-5.6 support through Penguin's OpenAI/Codex OAuth catalog path, including Sol, Terra, and Luna when advertised and provisioned for the authenticated account.
- Preserved model-specific reasoning metadata through request execution and mapped Codex `ultra` mode to the OpenAI-safe `max` wire effort.
- Rejected unsupported reasoning variants before REST/WebSocket requests can persist or execute them.
- Preserved explicit reasoning opt-outs and supported configured efforts across catalog hydration and OAuth token refreshes.
- Added a dedicated CLI ACBRA decomposition campaign, with broader CLI ergonomics work sequenced after structural stabilization.

### v0.9.0

- Completed the ACBRA core-runtime decomposition campaign: `PenguinCore` is now a thin compatibility/orchestration facade over focused `penguin.core_runtime` modules.
- Added a durable runtime event ledger and canonical runtime-event envelope projection for web/TUI clients, giving downstream surfaces replayable and normalized runtime state.
- Closed the Penguin TUI upstream-adoption campaign through Phase 10, including stronger OpenCode-compatible event frames, prompt/session compatibility, notification controls, backend command registry foundations, provider/model catalog state, and session hydration state.
- Hardened the TUI around prompt context handling, paste handling, malformed tool input, inline tool errors, live assistant turn ordering, running-state submit blocking, model selection, session lists, usage telemetry, and startup performance.
- Expanded multi-agent/tool exposure for Responses-style providers and improved runtime compatibility edges across sessions, web, and TUI surfaces.
- Added per-run web server file logging with configurable log directory/file controls for easier operational debugging.

### v0.8.1

- Fixed Python 3.9 import compatibility for MCP configuration by avoiding a runtime PEP 604 union type alias.

### v0.8.0

- Shipped three weeks of daily dogfooding hardening across Penguin's core runtime, tool execution, task orchestration, and TUI/web surfaces.
- Added ordered batch tool execution and process-runtime foundations for more reliable multi-step agent workflows.
- Improved native tool-call runtime behavior across provider adapters, transcript replay, tool-result handling, and action execution metadata.
- Tightened RunMode, project-task, and clarification flows so API/web clients preserve non-terminal runtime truth instead of flattening everything into fake success/failure states.
- Continued OpenCode-compatible TUI integration work, including better event ordering, session scoping, sidecar packaging, and launcher behavior.
- Strengthened local web/API security and operational surfaces around auth, settings, credentials, provider routes, SSE/WebSocket behavior, and GitHub integration.
- Expanded test coverage around provider contracts, streaming, session isolation, task state, permission/question flows, package exports, and TUI launcher behavior.
- Added and updated assurance and architecture documentation for the next phase of core refactoring and testing discipline.

### v0.7.0

- Hardened the native tool-call runtime across provider adapters, transcript replay, tool-result adjacency, and TUI event ordering.
- Shipped a safer local web/TUI auth flow with protected HTTP, SSE, and WebSocket bootstrap paths plus stronger upload and webhook guards.
- Expanded project bootstrap and task orchestration surfaces across TUI, web/API routes, and Run Mode while preserving non-terminal runtime truth.
- Added OpenAI/Codex fast-mode service-tier support and improved OAuth-backed Codex/latest-model access.
- Added Penguin TUI themes and defaulted the packaged TUI experience to the Emperor theme.

### v0.6.3

- Expanded native OpenAI / Codex integration, including stronger Responses API handling and OAuth-backed Codex response support.
- Improved OpenAI-compatible provider support and model/runtime normalization for native and gateway flows.
- Better handling of tool-only OpenAI/Codex turns and Responses-style tool calls in the runtime loop.
- Continued runtime/docs alignment work across task clarification, dependency-policy, and public surface verification.

## Documentation

- [Official Documentation](https://penguin-rho.vercel.app)
- [Release Notes](https://github.com/Maximooch/penguin/releases)
- `architecture.md`
- `context/tasks/Penguin_SCAR_80_20_Roadmap.md`

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
