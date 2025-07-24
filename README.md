[![Penguin](https://img.shields.io/badge/🐧-Penguin-00A7E1?style=for-the-badge&logoColor=white)](https://github.com/maximooch/penguin)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/pypi/v/penguin-ai.svg)](https://pypi.org/project/penguin-ai/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![GitHub Actions](https://img.shields.io/github/actions/workflow/status/Maximooch/penguin/publish.yml?branch=main)](https://github.com/Maximooch/penguin/actions)
[![Documentation Status](https://img.shields.io/badge/docs-latest-brightgreen.svg)](https://penguin-rho.vercel.app)
[![Downloads](https://img.shields.io/pypi/dm/penguin-ai.svg)](https://pypi.org/project/penguin-ai/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Maximooch/penguin)



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

Penguin is an autonomous software engineering agent that goes beyond code completion—it manages entire projects from planning to execution. Unlike other AI coding assistants that require constant supervision, Penguin features built-in project management, autonomous task execution, and a modular architecture that handles everything from writing code to coordinating complex development workflows. Think of it as your AI software engineer that can take a project spec and deliver working software, not just code snippets.

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

## Development Status

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

[View Full Roadmap →](https://penguin-rho.vercel.app/docs/advanced/roadmap) • [Performance Tracking →](https://github.com/maximooch/penguin/blob/main/test_startup_performance.py)

<!-- For now link roadmap to future considerations, or the Penguin super roadmap file. Then later on have a github projects roadmap? -->

# Penguin AI Assistant

Penguin is a modular, extensible AI coding assistant powered by LLMs, enabling support for multiple AI models thanks to LiteLLM. It functions as an intelligent software engineer that can assist with coding tasks while maintaining its own code execution, memory tools, and workspace environment.

## Key Features

### **Cognitive Architecture**
Penguin implements a sophisticated multi-system cognitive architecture:

- **Reasoning & Response Generation**: Advanced prompt engineering with context-aware decision making
- **Persistent Memory Management**: Conversation history with cross-session knowledge retention  
- **Pluggable Memory Providers**: Support for SQLite, FAISS, LanceDB, and ChromaDB backends
- **Tool & Action Processing**: Modular system with 15+ built-in tools and extensible action handlers
- **Task Coordination**: SQLite-backed project management with dependency tracking
- **Performance Monitoring**: Built-in diagnostics, error tracking, and execution metrics

### **Development Capabilities**
Comprehensive coding assistance and automation:

- **Code Execution**: IPython notebook integration for running, testing, and debugging code
- **Project Scaffolding**: Automated project structure generation with best practices
- **Code Generation**: Documentation, unit tests, and architectural recommendations
- **File System Operations**: Complete file management (create, read, write, search, organize)
- **Web Search Integration**: Real-time information retrieval during conversations
- **Browser Use**: PyDoll integration for web interaction and Chrome debugging
- **Debugging & Analysis**: Intelligent error detection and resolution suggestions

### **Project Management**
Enterprise-grade project coordination:

- **SQLite-backed Storage**: ACID transactions for reliable project and task data
- **Task Dependencies**: Complex workflow management with dependency graphs
- **Progress Tracking**: Real-time status updates and detailed execution history
- **Resource Management**: Token budgets, time limits, and tool constraints per task
- **Workspace Organization**: Structured file and project management
- **Memory Search**: Semantic search across conversations and project history

### **Multi-Interface Support**
Flexible interaction methods:

- **Interactive CLI**: Full-featured command-line with project/task management commands
- **Web API**: Production-ready REST/WebSocket backend (FastAPI-powered)
- **Python Library**: Rich programmatic API for integration and automation
- **Multi-Model Support**: OpenAI, Anthropic, OpenRouter, and local models via LiteLLM

### **Advanced Features**
- **Automatic Checkpoints**: Conversation branching and rollback capabilities *(planned)*
- **Plugin Architecture**: Extensible tool system for third-party integrations *(in development)*
- **Team Collaboration**: Multi-user workspaces and shared projects *(planned)*
- **Rich Web UI**: Complete browser interface with real-time updates *(in development)*

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

For contributing or using latest features:

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

Penguin uses a modular architecture with these key systems:
- **Core**: Central coordinator between systems
- **Cognition**: Handles reasoning and response generation
- **Memory**: Manages context and knowledge persistence
- **Processor**: Controls tools and actions (ToolManager, Parser (ActionManager), and utils)
- **Task**: Coordinates projects and tasks
- **Diagnostic**: Monitors performance


### System Design
- Core acts as coordinator between systems
- Each system has clear responsibilities
- State management through hierarchical state machines
- Event-based communication between modules
- Memory persistence across sessions
- Tool extensibility through plugin architecture

### Key Components
1. **Cognition System**
   - Reasoning and response generation
   - Model integration via LiteLLM
   - Context management

2. **Memory System**
   - Short-term conversation memory
   - Long-term knowledge persistence
   - Embeddings and vector storage
   - Pluggable providers (SQLite, file, FAISS, LanceDB, Chroma)
   - Backup and restore utilities

3. **Processor System**
   - ToolManager: Central registry and executor for available tools
   - ActionExecutor: Parses and routes actions to appropriate handlers
   - NotebookExecutor: Handles code execution in IPython environment

4. **Task System**
   - Project and task coordination
   - Workspace management
   - File operations

5. **Diagnostic System**
   - Performance monitoring
   - Error tracking
   - System health checks

### Development Standards (Not implemented yet)
- Comprehensive type annotations
- Detailed docstrings
- High test coverage (90%+)
- Robust exception handling
- Extensive logging

For detailed technical documentation, visit our [docs](https://penguin-rho.vercel.app).

## Contributing

We welcome contributions! Penguin is open source and benefits from community involvement.

### Quick Start for Contributors

```bash
# 1. Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/penguin.git
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

### Community

- [GitHub Discussions](https://github.com/Maximooch/penguin/discussions) - Questions and ideas
- [Issues](https://github.com/Maximooch/penguin/issues) - Bug reports and feature requests  
- [Roadmap](https://github.com/Maximooch/penguin/projects) - Development progress

For major changes, please open an issue first to discuss your approach.

## Support & Help

### Documentation & Resources
- **[Official Documentation](https://penguin-rho.vercel.app)** - Complete user guide and API reference
- **[GitHub Discussions](https://github.com/Maximooch/penguin/discussions)** - Community Q&A and ideas
- **[Examples & Tutorials](https://penguin-rho.vercel.app/docs/usage/)** - Step-by-step guides
- **[Roadmap](https://github.com/Maximooch/penguin/projects)** - Development progress and planned features

### Issues & Bug Reports
- **[Report a Bug](https://github.com/Maximooch/penguin/issues/new?template=bug_report.md)** - Something not working?
- **[Request a Feature](https://github.com/Maximooch/penguin/issues/new?template=feature_request.md)** - Ideas for improvements
- **[Performance Issues](https://github.com/Maximooch/penguin/blob/main/test_startup_performance.py)** - Use our performance test script

### Project Status
- **Current Version**: v0.3.1 (Phase 3 Complete)  
- **Active Development**: Phase 3 - Performance & Benchmarking
- **Stability**: Core features stable, performance optimization in progress
- **Python Support**: 3.9+ (3.10+ recommended for best performance)

### Changelog & Releases
- **[Release Notes](https://github.com/Maximooch/penguin/releases)** - What's new in each version
- **[Development Blog](https://penguin-rho.vercel.app/blog)** - Technical deep-dives and progress updates

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

**Interested in enterprise licensing?** Please contact the maintainer to discuss your requirements and explore available options.



## Acknowledgments

Built upon insights from:
- [CodeAct](https://arxiv.org/abs/2402.01030)
- [Claude-Engineer](https://github.com/Doriandarko/claude-engineer)
- [Aider](https://github.com/paul-gauthier/aider)
- [RawDog](https://github.com/AbanteAI/rawdog)

