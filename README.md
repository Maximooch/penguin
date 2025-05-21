[![Penguin](https://img.shields.io/badge/🐧-Penguin-00A7E1?style=for-the-badge&logoColor=white)](https://github.com/maximooch/penguin)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Documentation Status](https://img.shields.io/badge/docs-latest-brightgreen.svg)](https://penguin-rho.vercel.app)
[![Version](https://img.shields.io/badge/version-0.1.0-orange)](https://github.com/maximooch/penguin)

## 📋 Table of Contents
- [Overview](#overview)
- [Features](#key-features)
- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgments](#acknowledgments)


## 🚀 Quick Start
```bash
# Clone and install Penguin
git clone https://github.com/maximooch/penguin.git
cd penguin

# Install Penguin (recommended with UV)
pip install -e .

# Set your API key
cp .env.example .env
# Edit .env with your API key

# Run Penguin
penguin  # CLI interface
# OR
penguin-web  # Web interface 
```

## 🎯 Development Status
- ✅ Core functionality
- ✅ Basic CLI interface (penguin)
- ✅ Model integration (OpenRouter, Ollama and other open source inference engines soon))
- 🚧 Advanced features (in progress)
   - 
- 📅 Web interface (penguin-web and Link, planned)
- 📅 Plugin system (planned)

[View Roadmap →](https://github.com/maximooch/penguin/projects)

⚠️ **Note**: Penguin is under active development. While I  strive for stability, you may encounter occasional issues. Your feedback and contributions are valuable in improving the project.

# Penguin AI Assistant

Penguin is a modular, extensible AI coding assistant powered by LLMs, enabling support for multiple AI models thanks to LiteLLM. It functions as an intelligent software engineer that can assist with coding tasks while maintaining its own code execution, memory tools, and workspace environment.

## Key Features

- **Multi-Model Support**: Compatible with various AI models through LiteLLM integration

- **Cognitive Architecture**:
  - Reasoning and response generation system
  - Persistent memory and context management
  - Tool and action processing capabilities
  - Task coordination and project management
  - Performance monitoring and diagnostics
- **Development Capabilities**:
  - Automated task execution and project scaffolding
  - Code generation with documentation
  - Debugging and problem analysis
  - Architectural design recommendations
  - File system operations and management
  - Web search integration for up-to-date information

## Prerequisites

- [Python 3.10 (recommended) or Python 3.8+](https://www.python.org/downloads/)
- Valid API key(s) for your chosen AI model provider(s)
- [UV package manager](https://docs.astral.sh/uv/getting-started/installation/) (recommended)

## Installation

### Option 1: Recommended Setup (using UV)

1. Install UV package manager (if not already installed):
```bash
pip install uv
```

2. Clone the repository:
```bash
git clone https://github.com/maximooch/penguin.git
cd penguin
```

3. Run the UV setup script:
```bash
python uv_setup.py
```
This will:
- Create a Python 3.10 virtual environment
- Install all dependencies using UV
- Offer to launch Penguin

### Option 2: Standard Setup

1. Clone the repository:
```bash
git clone https://github.com/maximooch/penguin.git
cd penguin
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  
# On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Rename `.env.example` to `.env` and configure your environment:

    Then Edit `penguin/.env` with your API key(s)

## Usage

Start the Penguin AI assistant:
```bash
penguin  # Start CLI interface
penguin-web  # Start Web interface
```

Play around with Penguin! It's recommended to check out the User Manual, and the Docs for more in depth information to get the most out of Penguin!

To change models, go to the `config.yml` file and change the `model` field to the model you want to use.

For more information on how to use Penguin, check out the [documentation](https://penguin-rho.vercel.app)! 


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

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss proposed changes.

## License

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



## Acknowledgments

Built upon insights from:
- [CodeAct](https://arxiv.org/abs/2402.01030)
- [Claude-Engineer](https://github.com/Doriandarko/claude-engineer)
- [Aider](https://github.com/paul-gauthier/aider)
- [RawDog](https://github.com/AbanteAI/rawdog)

