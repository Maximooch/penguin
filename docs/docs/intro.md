---
sidebar_position: 1
---

# Penguin AI Assistant Documentation

Welcome to the documentation for Penguin! Penguin v0.3.3.3.post1 is a modular, extensible AI coding agent with advanced conversation management, real-time streaming, comprehensive checkpoint/branching, and soon multi/sub-agent capabilities.

## Features

- **Advanced Conversation Management**: Checkpoint and snapshot system for conversation state management
- **Real-time Streaming**: Enhanced streaming with event-driven architecture and UI coordination
- **Token Management**: Context window management with category-based budgets and image handling
- **Runtime Model Switching**: Dynamic model switching with automatic configuration updates
- **Fast Startup**: Optional deferred initialization for improved performance
- **Comprehensive Diagnostics**: Performance monitoring and startup reporting
- **Event-Driven Architecture**: Real-time UI updates via comprehensive event system
- **File manipulation and code generation**
- **Web searches for up-to-date information**
- **Automated task execution with Run Mode**
- **Project management with SQLite persistence**
- **Custom tool integration**
- **PyDoll browser automation**
- **Memory search across conversations**
- **Pluggable memory providers with vector search**
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

- **`penguin.core`** - Central coordinator with event system and real-time streaming
- **`penguin.system`** - Advanced conversation management with checkpoints and snapshots
- **`penguin.llm`** - Enhanced API client with streaming and provider abstraction
- **`penguin.cli`** - Command-line interface with TUI and performance monitoring
- **`penguin.web`** - Web interface and REST API with programmatic access
- **`penguin.project`** - SQLite-backed project and task management
- **`penguin.tools`** - Extensible tool ecosystem with lazy initialization
- **`penguin.memory`** - Conversation and knowledge persistence

### Key Architecture Improvements

- **Event-Driven Communication**: Real-time UI updates via comprehensive event system
- **Checkpoint System**: Advanced conversation state management with branching
- **Enhanced Streaming**: Real-time response streaming with callback compatibility
- **Token Management**: Category-based budgeting with image optimization
- **Fast Startup**: Deferred initialization for improved performance
- **Provider Abstraction**: Multiple client handlers (native, LiteLLM, OpenRouter)
- **Configuration Management**: Enhanced config resolution with live updates

## Contributing

Contributions are welcome! Please see our [contributing guidelines](https://github.com/Maximooch/penguin/blob/main/CONTRIBUTING.md) for details.

## License

This project is licensed under the GNU Affero General Public License v3.0. See the [LICENSE](https://github.com/Maximooch/penguin/blob/main/LICENSE) file for details.
