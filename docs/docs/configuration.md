---
sidebar_position: 3
---

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