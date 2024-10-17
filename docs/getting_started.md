---
title: Getting Started
---

# Getting Started with Penguin AI Assistant

This guide will help you set up and run the Penguin AI Assistant on your local machine.

## Prerequisites

- Python 3.9 or higher
- pip (Python package manager)
- Git

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo-url/penguin-ai.git
   cd penguin-ai
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set up your API keys:
   - Copy the `.env.example` file to `.env`
   - Edit `.env` and add your API keys for the language models you want to use

## Running Penguin AI

To start the Penguin AI Assistant, run:

```bash
python main.py
```

You'll be greeted with a welcome message and can start interacting with the AI.

## Basic Usage

- Type your questions or commands and press Enter to send them to the AI.
- Use special commands like `task`, `project`, or `image` for specific functionalities.
- Type `exit` to end the session.

For more detailed usage instructions, see the [Basic Usage](usage/basic_usage.md) guide.

## Next Steps

- Explore the [Configuration](configuration.md) options to customize Penguin AI.
- Learn about [Automode](usage/automode.md) for automated task execution.
- Discover how to manage [Tasks](usage/task_management.md) and [Projects](usage/project_management.md).





# Configuring Penguin AI Assistant

Penguin AI Assistant can be configured through environment variables and configuration files. This guide explains the available options and how to set them.

## Environment Variables

Create a `.env` file in the root directory of the project and set the following variables:

- `OPENAI_API_KEY`: Your OpenAI API key (required for OpenAI models)
- `ANTHROPIC_API_KEY`: Your Anthropic API key (required for Claude models)
- `DEFAULT_MODEL`: The default language model to use (e.g., `gpt-3.5-turbo`, `gpt-4`, `claude-v1`)
- `DEFAULT_PROVIDER`: The default provider for the language model (e.g., `openai`, `anthropic`)

Example `.env` file:

```
ANTHROPIC_API_KEY=insert_your_key_here
OPENAI_API_KEY=insert_your_key_here
```


- For configuring different language models and providers, refer to the [LiteLLM documentation](https://docs.litellm.ai/docs/providers)

5. Configure your model (optional):
   - Open the `config.yml` file in the root directory
   - Modify the `model`, `provider`, and `model_configs` sections as needed
   - For detailed configuration options, consult the LiteLLM documentation



# todo: add configuration for ollama!

