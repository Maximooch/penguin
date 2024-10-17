---
sidebar_position: 2
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
   git clone https://github.com/Maximooch/penguin.git
   cd penguin
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






