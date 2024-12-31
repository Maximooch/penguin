## Development Status

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
python main.py
```

Play around with Penguin! It's recommended to check out the User Manual, and the Docs for more in depth information to get the most out of Penguin!

To change models, go to the `config.yml` file and change the `model` field to the model you want to use.

For more information on how to use Penguin, check out the [documentation](https://penguin-rho.vercel.app)! 


## Architecture

Penguin uses a modular architecture with these key systems:
- **Core**: Central coordinator between systems
- **Cognition**: Handles reasoning and response generation
- **Memory**: Manages context and knowledge persistence
- **Processor**: Controls tools and actions
- **Task**: Coordinates projects and tasks
- **Diagnostic**: Monitors performance


## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss proposed changes.

## License

This project is licensed under the GNU Affero General Public License v3.0 - see the [LICENSE](LICENSE) file for details or visit [https://www.gnu.org/licenses/agpl-3.0.en.html](https://www.gnu.org/licenses/agpl-3.0.en.html) for the full license text.

## Acknowledgments

Built upon insights from:
- [CodeAct](https://arxiv.org/abs/2402.01030)
- [Claude-Engineer](https://github.com/Doriandarko/claude-engineer)
- [Aider](https://github.com/paul-gauthier/aider)
- [RawDog](https://github.com/AbanteAI/rawdog)

