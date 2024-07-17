# Penguin AI Assistant

Penguin is a modular, extensible AI coding assistant. (as of now only using Claude 3.5 Sonnet)

It provides a command-line interface for interactive conversations, file manipulation, web searches, and automated task execution. Designed for developers, Penguin AI can assist with coding tasks, answer questions, and interact with the local file system, making it a versatile tool for software development and general problem-solving.


## Features


- Automated Task Execution
- Create project structures with folders and files
- Write clean, efficient, and well-documented code
- Debug complex issues and provide detailed explanations
- Offer architectural insights and design patterns
- Stay up-to-date with the latest technologies and industry trends
- Read and analyze existing files in the project directory
- List files in the root directory of the project
- Perform web searches for up-to-date information

## Setup

1. Clone the repository
2. Create a virtual environment and activate it
3. Install the required dependencies: `pip install -r requirements.txt`
4. Set up your API keys in `config.py`

## Usage

Run the Penguin AI assistant:

```
python main.py
```

Follow the on-screen instructions to interact with the AI assistant.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the GNU Affero General Public License v3.0 - see the [LICENSE](LICENSE) file for details or visit [https://www.gnu.org/licenses/agpl-3.0.en.html](https://www.gnu.org/licenses/agpl-3.0.en.html) for the full license text.

## Acknowledgments

This project was inspired by the following projects:
- [Claude-Engineer](https://github.com/Doriandarko/claude-engineer)
- [Aider](https://github.com/paul-gauthier/aider)
- [RawDog](https://github.com/AbanteAI/rawdog)

Special thanks to [Claude-Engineer](https://github.com/Doriandarko/claude-engineer) for providing some of the code used in this project. Specifically, the prompt structure, tool system, and automode functionality were adapted from Claude-Engineer. While these components have been significantly rewritten, they served as a valuable starting point. This code is used under the terms of the MIT license.