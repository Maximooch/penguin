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

<!-- [![Penguin](https://img.shields.io/badge/🐧-Penguin-00A7E1?style=for-the-badge&logoColor=white)](https://github.com/maximooch/penguin)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/) -->
[![PyPI version](https://img.shields.io/pypi/v/penguin-ai.svg)](https://pypi.org/project/penguin-ai/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/Maximooch/penguin/publish.yml?branch=main)](https://github.com/Maximooch/penguin/actions)
[![Documentation Status](https://img.shields.io/badge/docs-latest-brightgreen.svg)](https://penguin-rho.vercel.app)
[![Downloads](https://img.shields.io/pypi/dm/penguin-ai.svg)](https://pypi.org/project/penguin-ai/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)


<!-- To quickly understand the codebase, DeepWiki is recommended (note: it's ~90% accurate)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Maximooch/penguin) -->



## Table of Contents
- [Overview](#overview)
- [Quick Start](#quick-start)
- [Development Status](#development-status)  
- [Key Features](#key-features)
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [Support & Help](#support--help)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Overview

Penguin is a modular, open-source AI software engineer that combines autonomous code generation with project management, task coordination, and multi-agent orchestration to take projects from spec to implementation.


## Quick Start
```bash
# Install with CLI tools (recommended for most users)
pip install penguin-ai

# Optional: Install with web interface 
pip install penguin-ai[web]

# Set up your API key (OpenRouter recommended)
export OPENROUTER_API_KEY="your_api_key"  # On Windows: set OPENROUTER_API_KEY=...

# Run the setup wizard
penguin config setup

# Start using Penguin
penguin              # Interactive CLI chat
penguin-web          # Web API server (if [web] installed)
```

<!-- #TODO: double check if accurate.  -->

### Quick Python Usage
```python
from penguin import PenguinAgent

# PenguinAgent handles PenguinCore setup, workspace defaults, and project docs
with PenguinAgent() as agent:
    response = agent.chat("Summarize the current task charter")
    print(response["assistant_response"])

    # Register a specialized sub-agent if desired
    agent.register_agent("qa", system_prompt="You are the QA reviewer.")
```

`PenguinAgent` wraps the full `PenguinCore` stack (conversation manager, tool manager,
project docs autoloading) with a synchronous API so you can script multi-agent workflows
without reimplementing orchestration.

<!-- Actual roadmap is a #TODO: -->
<!-- # TODO: Actual roadmap -->

<!-- ## Development Status

### ✅ **Phase 2 Complete: Developer Preview (v0.2.x)**
- **Core Architecture**: Modular namespaces (`penguin.cli`, `penguin.web`, `penguin.project`)
- **CLI Interface**: Full project/task management with 20+ commands
- **Multi-Model Support**: OpenRouter, Anthropic, OpenAI via LiteLLM  
- **Project Management**: SQLite ACID transactions with dependency tracking
- **Hybrid Dependencies**: Smart defaults + optional extras ([web], [memory_*], [browser])
- **Web API**: Production FastAPI/WebSocket backend with OpenAPI docs
- **Automated Publishing**: GitHub Actions with trusted PyPI publishing

### 🚧 **Phase 3 Active: Performance & Benchmarking (v0.3.x)**

**Current Performance Work:**
- **Fast Startup Mode**: Deferred memory indexing reducing cold start by 60-80%
- **Lazy Loading**: Memory providers and tools loaded on-demand vs upfront
- **Background Processing**: Memory indexing moved to separate threads
- **Profiling Integration**: Built-in performance monitoring with detailed reports
- **Resource Optimization**: Memory usage tracking and garbage collection tuning

**Benchmarking Pipeline (In Progress):**
- **SWE-bench Integration**: Automated coding task evaluation
- **HumanEval Testing**: Code generation accuracy benchmarks  
- **Startup Performance**: Sub-250ms P95 target for CLI initialization
- **Memory Footprint**: <200MB baseline memory usage optimization
- **Token Efficiency**: Cost optimization with intelligent model routing

**Technical Debt & Architecture:**
- **Background Memory Daemon**: Separate process for indexing and search
- **Connection Pooling**: Database and API connection optimization
- **Async Optimization**: Converting blocking I/O to async patterns
- **Error Recovery**: Graceful degradation and circuit breaker patterns

### 📅 **Planned: Advanced Features (v0.4.x+)**
- **Rich Web UI**: React-based interface with real-time updates
- **Advanced Memory**: Vector search, knowledge graphs, cross-session learning
- **Multi-Agent Systems**: Coordinated AI agents for complex projects  
- **Plugin Ecosystem**: Third-party tool integration and marketplace

[View Full Roadmap →](https://penguin-rho.vercel.app/docs/advanced/roadmap) • [Performance Tracking →](https://github.com/maximooch/penguin/blob/main/test_startup_performance.py) -->

<!-- For now link roadmap to future considerations, or the Penguin super roadmap file. Then later on have a github projects roadmap? -->

# Penguin

Penguin is a modular, extensible AI coding assistant powered by LLMs. It functions as an intelligent software engineer that can assist with coding tasks while maintaining its own code execution, memory tools, and workspace environment. 

It is designed for full-lifecycle software development. It goes beyond code generation by managing tasks, coordinating sub-agents, tracking project progress, and executing long-running objectives with minimal human oversight. Its architecture includes persistent memory, a rich toolchain, CLI and Web interfaces, and an SQLite-backed project management system. Penguin enables scalable, intelligent workflows across complex codebases and development environments, making it a serious upgrade from prompt-based coding assistants.

## Key Features

### Core Orchestration
- Multi-agent runtime with planner/implementer/QA personas, lightweight "lite" agents, and
  per-agent routing through `agent_id`.
- Scoped sub-agent delegation that inherits context, tools, and memory while enforcing token
  and permission boundaries.
- Engine-managed reasoning loop that powers chat and Run Mode with configurable iterations and
  pluggable stop conditions (token budget, wall clock, external callbacks).
- MessageBus and telemetry streams that tag every event with agent/channel metadata for CLI,
  TUI, web, and dashboard consumers.

### Conversation & Memory Systems
- ConversationManager that blends session persistence, auto-save, context loading, checkpoints,
  and snapshot/restore support.
- ContextWindowManager with category-based token budgets, multimodal trimming, and live usage
  reporting to keep histories within model limits. This allows for theoretically infinite sessions.
- Shared memory layer with declarative notes, summary notes, and retrieval backed by SQLite plus
  pluggable vector providers (FAISS, LanceDB, Chroma, others).

### Development Tools & Workspace Automation
- Workspace-aware toolchain that respects project/workspace roots for file edits, diffs,
  pattern-based refactors, and repository operations.
- LLM-driven scaffolding for code, documentation, tests, and refactoring guidance.
- Analysis and execution utilities such as AST inspection, dependency mapping, linting,
  notebook-based execution, grep/workspace search, and Perplexity/web search integrations.
- Browser automation via headless navigator and PyDoll tools for scripted browsing and capture,
  plus repository helpers to scaffold PRs, manage branches, and push changes.

### Project & Task Management
- SQLite-backed ProjectManager with ACID transactions, dependency graphs, resource budgets,
  execution tracking, and event bus integration.
- CLI, Python, and web surfaces for project/task CRUD, status tracking, budgeting, and
  autonomous execution via Run Mode.

### Interfaces & Integrations
- Rich CLI with interactive TUI, setup wizard, and >20 commands covering projects, memory, and
  tooling.
- Async Python client (`PenguinClient`) that offers streaming chat, checkpoint workflows, model
  switching, and multi-agent routing.
- FastAPI web server with REST + WebSocket streaming endpoints and an embeddable `PenguinAPI`
  for custom applications (agent spawn/pause/delegate, conversation history, telemetry).
- Dashboard hooks and telemetry endpoints for observability integrations.

### Model & Provider Support
- Native and gateway adapters for OpenAI, Anthropic, OpenRouter, and LiteLLM-supported
  backends (Azure, Bedrock, DeepSeek, Ollama, and more).
- Runtime model/provider switching with layered configuration, capability detection, and
  multimodal (vision/image) support.
- Provider-aware token counting, cost reporting, and budgets exposed through the engine and
  telemetry APIs.

### Performance, Diagnostics & Governance
- Fast-startup path with lazy tool loading, deferred memory indexing, and background workers to
  reduce cold-start latency.
- Structured diagnostics covering startup profiling, operation timing, token usage, and error
  tracing.
- Telemetry collector aggregating message, agent, task, and token metrics for dashboards and
  alerting.
- Configurable logging, retries, and graceful error recovery across subsystems.

### Data & Context Ingestion
- Context loader and cataloging pipeline for PDFs, docs, and workspace artifacts so agents can
  ground responses in project materials.
- Memory indexing with semantic search and declarative knowledge capture integrated into the
  conversation loop.

### Extensibility & Configuration
- Tool registry and plugin architecture for declarative or dynamic tool registration without
  patching core modules.
- Comprehensive configuration surface through `config.yml`, environment variables, and CLI
  helpers (project/workspace roots, model defaults, streaming controls).
- Event bus and MessageBus hooks for integrating custom services with agent lifecycle events,
  tool invocations, and telemetry streams.

## Prerequisites

- [Python 3.9+](https://www.python.org/downloads/) (3.10+ recommended for best performance)
- Valid API key(s) for your chosen AI model provider(s)
- [UV package manager](https://docs.astral.sh/uv/getting-started/installation/) (optional, for development)

## Installation

### Recommended: PyPI Installation

```bash
# Core installation (includes CLI tools)
pip install penguin-ai

# With web interface
pip install penguin-ai[web]

# With memory providers
pip install penguin-ai[memory_faiss]    # FAISS + sentence-transformers  
pip install penguin-ai[memory_lance]    # LanceDB
pip install penguin-ai[memory_chroma]   # ChromaDB

# Full installation (all features)
pip install penguin-ai[all]
```

### Development Installation

For contributing or using the latest features:

```bash
git clone https://github.com/maximooch/penguin.git
cd penguin/penguin
pip install -e .                        # Editable install
# OR with UV (faster)
pip install uv && python uv_setup.py    # Automated UV setup
```

### Available Extras

| Extra | Description | 
|-------|-------------|
| `[web]` | FastAPI server + WebSocket support |
| `[memory_faiss]` | FAISS vector search + embeddings |
| `[memory_lance]` | LanceDB vector database |
| `[memory_chroma]` | ChromaDB integration |
| `[browser]` | Browser automation (Python 3.11+ only) |
| `[all]` | Everything above |

## Usage

```bash
# Interactive chat
penguin

# Run setup wizard
penguin config setup

# Project management
penguin project create "My Project"
penguin project task create PROJECT_ID "Task description"

# Web API server (requires [web] extra)
penguin-web
```

For detailed usage, see the [documentation](https://penguin-rho.vercel.app).

File operations default to your project root (git root). Use `--root workspace` or set
`defaults.write_root: workspace` if you want writes to go to the Penguin workspace instead.

### Common In‑Chat Commands
When running `penguin` interactively, you can use slash‑style commands to control models, streaming, context, checkpoints, and run mode. Type `/help` in chat to see them all. A few useful ones:

```text
/models                 # Interactive model selector
/model set <MODEL_ID>   # Set a specific model (e.g., openrouter/anthropic/...)
/stream on|off          # Toggle token streaming

# Checkpoints & branches
/checkpoint [name] [description]  # Save a conversation checkpoint
/checkpoints [limit]               # List checkpoints
/rollback <checkpoint_id>         # Restore to a checkpoint
/branch <checkpoint_id> [name]    # Branch a new convo from a checkpoint

# Context window & diagnostics
/truncations [limit]     # Recent context trimming events
/tokens|/tokens detail   # Token usage summary / details

# Context file helpers
/context add <glob>      # Copy files into workspace context
/context list|clear      # Inspect or clear context files
/context write|edit|remove|note   # Manage context artifacts

# Run Mode
/run task "Name" [desc]        # Run a specific task
/run continuous ["Name" [desc]] # Continuous Run Mode (alias: --247)
```

<!-- ## 🎬 Demo & Screenshots

### CLI Interface
```bash
# Interactive chat with project context
$ penguin
🐧 Penguin AI Assistant v0.2.3
📁 Workspace: /path/to/your/project
💭 Type your message or use /help for commands

You: Create a FastAPI app with user authentication
🤖 I'll help you create a FastAPI application with user authentication...
```

### Project Management
```bash
# Create and manage projects
$ penguin project create "E-commerce API" -d "REST API for online store"
✓ Created project: E-commerce API (ID: abc123)

$ penguin project task create abc123 "Setup FastAPI project structure"
✓ Created task: Setup FastAPI project structure (ID: task456)

$ penguin project task start task456
🚀 Starting task: Setup FastAPI project structure
```

### Web API Interface
```bash
# Start the web server
$ penguin-web
🌐 Starting Penguin Web API...
📡 Server running at http://localhost:8000
📚 API docs: http://localhost:8000/docs
```

> 📸 **Coming Soon**: Screenshots and GIFs demonstrating the full interface -->

## Architecture

Penguin follows a layered architecture that keeps reasoning, memory, tooling, and delivery
surfaces loosely coupled while sharing telemetry and configuration.

### Runtime Flow
1. **Interfaces** (CLI/TUI, Python client, web API) collect user prompts or task requests.
2. **PenguinCore** coordinates global configuration, instantiates shared services, and routes
   work into the **Engine**.
3. The **Engine** runs the reasoning loop: it prepares conversation state, chooses the right
   agent (planner, implementer, QA, lite agent, or sub-agent), requests completions through the
   `APIClient`, and dispatches tool invocations via `ActionExecutor`.
4. Results are persisted through the **Conversation layer** (ConversationManager, SessionManager,
   ContextWindowManager, CheckpointManager, SnapshotManager) and written back to interfaces via
   the MessageBus or streaming callbacks.
5. Project/task updates, memory notes, telemetry, and diagnostics are propagated to their
   dedicated subsystems for analytics and follow-up automation.

### Key Subsystems
- **Conversation Layer**: ConversationManager manages sessions, context files, checkpoints, and
  snapshots. ContextWindowManager enforces category-based token budgets and trimming, while
  SessionManager persists conversations under the workspace. CheckpointManager/SnapshotManager
  provide branch/restore support.
- **Engine & Multi-Agent Runtime**: Engine orchestrates the reasoning loop, Run Mode, and stop
  conditions. It registers multiple agents (planner/implementer/QA/lite/sub-agents) via
  `EngineAgent`, integrates with `MultiAgentCoordinator`, and honors per-agent configuration.
- **Tooling & Actions**: ToolManager exposes 15+ built-in tools and lazy-loads heavy resources.
  ActionExecutor parses tool calls, NotebookExecutor runs code in an IPython kernel, and the
  plugin/registry system allows declarative or dynamic tool additions.
- **Memory & Knowledge**: Declarative notes, summary notes, and semantic search live in
  `penguin.memory`. Providers (SQLite, FAISS, LanceDB, Chroma, etc.) can be swapped or combined,
  and background indexers keep embeddings fresh.
- **Project & Task Orchestration**: ProjectManager provides ACID-backed CRUD, dependency graphs,
  budgeting, execution records, and event bus hooks. WorkflowOrchestrator, ProjectTaskExecutor,
  and ValidationManager coordinate complex project flows and Run Mode automation.
- **Model & Provider Access**: APIClient chooses the best adapter (native SDK, LiteLLM, OpenRouter)
  based on configuration. ModelConfig centralizes provider details, token budgets, reasoning modes,
  and streaming preferences.
- **Interfaces**: The Typer-based CLI powers both quick commands and the Textual TUI. The Python
  client (`PenguinClient`) wraps PenguinCore for async automation, and the FastAPI app exposes REST
  + WebSocket APIs plus an embeddable `PenguinAPI` class.
- **Diagnostics & Telemetry**: Profiling helpers, startup timing, message/agent telemetry, and the
  event bus feed dashboards, logs, and alerting. Logging is standardized via `logging` with
  subsystem-specific loggers.
- **Configuration**: `config.yml`, environment variables, and CLI flags converge into the Config
  object passed through PenguinCore. Execution roots, workspace overrides, model/provider choices,
  and feature flags are resolved hierarchically.

For deeper technical diagrams and API references, explore the [documentation site](https://penguin-rho.vercel.app).

## Contributing

We welcome contributions! Penguin is open source and benefits from community involvement.

### Quick Start for Contributors

```bash
# 1. Fork and clone the repository
git clone https://github.com/Maximooch/penguin.git
cd penguin/penguin

# 2. Set up development environment  
pip install -e .[dev,test]        # Install in development mode
pip install pre-commit && pre-commit install  # Set up code formatting

# 3. Run tests to ensure everything works
pytest tests/

# 4. Make your changes and test
# 5. Submit a pull request
```

### How to Contribute

- **🐛 Bug Reports**: [Open an issue](https://github.com/Maximooch/penguin/issues) with details and reproduction steps
- **💡 Feature Requests**: [Discuss ideas](https://github.com/Maximooch/penguin/discussions) before implementing
- **📖 Documentation**: Help improve docs, examples, and guides
- **🧪 Testing**: Add test coverage for new features and edge cases
- **🎨 UI/UX**: Design improvements for CLI and web interfaces

### Development Guidelines

- Follow [PEP 8](https://pep8.org/) style guidelines (enforced by `black` and `ruff`)
- Add docstrings for public functions and classes
- Include tests for new functionality
- Update documentation for user-facing changes
- Use semantic commit messages

<!-- ### Community (right now it's just me :(

- [GitHub Discussions](https://github.com/Maximooch/penguin/discussions) - Questions and ideas
- [Issues](https://github.com/Maximooch/penguin/issues) - Bug reports and feature requests   -->
<!-- - [Roadmap](https://github.com/Maximooch/penguin/projects) - Development progress -->

For major changes, please open an issue first to discuss your approach.

## Support & Help

### Documentation & Resources
- **[Official Documentation](https://penguin-rho.vercel.app)** - Complete user guide and API reference
- **[GitHub Discussions](https://github.com/Maximooch/penguin/discussions)** - Community Q&A and ideas
- **[Examples & Tutorials](https://penguin-rho.vercel.app/docs/usage/)** - Step-by-step guides
<!-- - **[Roadmap](https://github.com/Maximooch/penguin/projects)** - Development progress and planned features -->

### Issues & Bug Reports
- **[Report a Bug](https://github.com/Maximooch/penguin/issues/new?template=bug_report.md)** - Something not working?
- **[Request a Feature](https://github.com/Maximooch/penguin/issues/new?template=feature_request.md)** - Ideas for improvements

<!-- TODO: Do this -->
<!-- - **[Performance Issues](https://github.com/Maximooch/penguin/blob/main/test_startup_performance.py)** - Use our performance test script -->

### Project Status
- **Current Version**: v0.4.0  
- **Active Development**: Phase 3 - Multi/Sub-agents, CLI/TUI refactor, GH integration, and achieving Claude Code parity then surpassing
- **Stability**: Core features stable, performance optimization in progress
- **Python Support**: 3.9+ (3.10+ recommended for best performance)

### Changelog & Releases
- **[Release Notes](https://github.com/Maximooch/penguin/releases)** - What's new in each version (right now it's just tags)
- (Soon) **[Development Blog](https://penguin-rho.vercel.app/blog)** - Technical deep-dives and progress updates

## License

### Open Source License

Penguin is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.

Key points:
- You must disclose source code when you deploy modified versions
- Changes must be shared under the same license
- Network use counts as distribution
- Include copyright and license notices

For the complete license text, see:
- [LICENSE](LICENSE) file in this repository
- [GNU AGPL v3](https://www.gnu.org/licenses/agpl-3.0.en.html) official text

### Enterprise License

An enterprise license without the copyleft requirements is under consideration for organizations that need different licensing terms. This would allow:
- Proprietary modifications and integrations
- No obligation to share source code changes
- Commercial redistribution rights
- Priority support and consulting services

**Interested in enterprise licensing?** Please contact me at MaximusPutnam@gmail.com to discuss your requirements and explore available options.



## Acknowledgments

Built upon insights from:
- [CodeAct](https://arxiv.org/abs/2402.01030)
- [Claude-Engineer](https://github.com/Doriandarko/claude-engineer)
- [Aider](https://github.com/paul-gauthier/aider)
- [RawDog](https://github.com/AbanteAI/rawdog)
