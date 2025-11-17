---
sidebar_position: 1
---

# Penguin AI Assistant Documentation

Welcome to the documentation for Penguin! Penguin v0.3.3.3.post1 is a modular, extensible AI coding agent with advanced conversation management, real-time streaming, comprehensive checkpoint/branching, and multi/sub-agent capabilities with coordinated orchestration.

## Features

- **Advanced Conversation Management**: Checkpoint and snapshot system with branching and rollback
- **Multi-Agent Architecture**: Per-agent conversations, model configs, tool defaults, and state isolation
- **Real-time Streaming**: Enhanced streaming with event-driven architecture, reasoning support, and UI coordination
- **Token Management**: Context window management with category-based budgets and image handling
- **Runtime Model Switching**: Dynamic model switching with automatic configuration updates
- **Fast Startup**: Deferred initialization for improved performance (fast_startup mode)
- **Comprehensive Diagnostics**: Performance monitoring, telemetry tracking, and startup reporting
- **Event-Driven Architecture**: Real-time UI updates via unified EventBus system
- **GitHub Integration**: Webhook support for automated workflows and CI/CD pipelines
- **Memory System**: Pluggable memory providers with vector search and semantic retrieval
- **Message Routing**: MessageBus protocol for agent-to-agent and human-to-agent communication
- **Agent Management**: Pause/resume controls, delegation patterns, and persona configurations
- **File manipulation and code generation**
- **Web searches for up-to-date information**
- **Automated task execution with Engine and Run Mode**
- **Project management with SQLite persistence**
- **Custom tool integration with lazy loading**
- **PyDoll browser automation**
- **REST API and WebSocket streaming**
- **Diagnostic logging and error handling**

## Quick Start

### Installation Options

**Default Installation (includes CLI tools):**
```bash
pip install penguin-ai
```

**With Web Interface:**
```bash
pip install penguin-ai[web]
```

**Minimal Installation (library only):**
```bash
pip install penguin-ai[minimal]
```

### Basic Usage

**Command Line Interface:**
```bash
# Interactive chat
penguin

# Direct commands
penguin "Write a hello world script"

# Project management
penguin project create "My Project"
penguin task create "Implement authentication"
```

Tip: Inside the interactive chat, type `/help` to see in‑chat commands for models, streaming, checkpoints, context files, and Run Mode. See also: Usage → CLI Commands.

**Web Interface:**
```bash
# Start web server (requires [web] extra)
penguin-web
```

**Python API:**
```python
from penguin import PenguinAgent

agent = PenguinAgent()
response = agent.chat("Help me debug this function")
```

## Documentation Structure

### Getting Started
- [Installation & Setup](getting_started.md)
- [Configuration](configuration.md)

### Usage Guides
- [CLI Commands](usage/cli_commands.md)
- [Project Management](usage/project_management.md)
- [Task Management](usage/task_management.md)
- [Web Interface](usage/web_interface.md)
- [API Usage](usage/api_usage.md)

### Advanced Topics
- [Custom Tools](advanced/custom_tools.md)
- [Error Handling](advanced/error_handling.md)
- [Diagnostics](advanced/diagnostics.md)
- [Extending Penguin](advanced/extensibility.md)
- [Multi-Agent Orchestration](advanced/multi_agents.md)
- [Sub-Agent Delegation](advanced/sub_agents.md)

### API Reference
- [Python API](api_reference/python_api_reference.md)
- [Project Management API](api_reference/project_api.md)
- [Core Engine](api_reference/core.md)
- [Tool Manager](api_reference/tool_manager.md)
- [Web API](api_reference/api_server.md)

## Architecture Overview

Penguin v0.3.3.3.post1 introduces an enhanced modular architecture with event-driven communication and advanced state management:

## Multi-Agent and Sub-Agent Workflows

Penguin's orchestration layer now speaks to both primary agents and scoped sub-agents so complex requests can fan out to specialized workers while preserving a shared context. See [Multi-Agent Orchestration](advanced/multi_agents.md) and [Sub-Agent Delegation](advanced/sub_agents.md) for deep dives.

- **Multi-Agent Conversations**: Every REST and WebSocket surface accepts an optional `agent_id` so callers can direct traffic to a specific persona or service partition. The coordinator keeps a per-agent conversation state while still exposing a unified system log and analytics feed.
- **Sub-Agent Delegation**: The core pipeline can spawn delegated subtasks that inherit the parent's tools, memory, and checkpoints. Sub-agents can be restricted to read-only or analysis-only modes and publish partial results back to the parent stream for review.
- **State Isolation with Shared Memory**: All agents share the same global memory store for recall, but runtime variables (current objective, active tools, run mode) are isolated per agent so experiments remain deterministic.
- **Client Support**: The Python client, REST API, and websocket streaming helpers all accept `agent_id`, enabling automation scripts or UI layers to switch personas mid-conversation without reinitializing the core.
- **Roadmap**: Upcoming iterations will add policy-based routing, automatic sub-agent scaling, and richer capability introspection so orchestration decisions can be data-driven.

### Core Components

- **`penguin.core`** - Central coordinator with multi-agent registry, event system, and streaming
- **`penguin.engine`** - High-level reasoning loop with multi-step task execution and stop conditions
- **`penguin.system`** - Advanced conversation management with per-agent sessions and checkpoints
- **`penguin.llm`** - Enhanced API client with streaming, reasoning models, and provider abstraction
- **`penguin.cli`** - Command-line interface with TUI, EventBus integration, and performance monitoring
- **`penguin.web`** - FastAPI server with REST API, WebSocket streaming, and GitHub webhooks
- **`penguin.multi`** - Multi-agent coordinator with role-based routing and delegation
- **`penguin.project`** - SQLite-backed project and task management with Engine integration
- **`penguin.tools`** - Extensible tool ecosystem with lazy loading and fast startup
- **`penguin.memory`** - Pluggable memory providers with vector search and persistence
- **`penguin.telemetry`** - Performance tracking, token usage, and diagnostics collection

### Key Architecture Improvements

- **Event-Driven Communication**: Unified EventBus for real-time UI updates and system coordination
- **Multi-Agent Support**: Per-agent conversations, API clients, model configs, and tool defaults
- **Checkpoint System**: Advanced conversation state management with branching and rollback
- **Enhanced Streaming**: Real-time response streaming with reasoning support and callback compatibility
- **Token Management**: Category-based budgeting with image optimization and per-agent tracking
- **Fast Startup**: Deferred memory indexing and lazy tool initialization (~2-3x faster)
- **Provider Abstraction**: Multiple client handlers (native, LiteLLM, OpenRouter) with auto-fallback
- **Configuration Management**: Enhanced config resolution with live updates and persona support
- **MessageBus Protocol**: Structured agent-to-agent and human-to-agent communication
- **GitHub Integration**: Webhook handlers for CI/CD, issue tracking, and automated workflows
- **Telemetry System**: Comprehensive performance tracking, token usage, and diagnostics
- **Engine Layer**: High-level task orchestration with stop conditions and iteration control

## Contributing

Contributions are welcome! Please see our [contributing guidelines](https://github.com/Maximooch/penguin/blob/main/CONTRIBUTING.md) for details.

## License

This project is licensed under the GNU Affero General Public License v3.0. See the [LICENSE](https://github.com/Maximooch/penguin/blob/main/LICENSE) file for details.
