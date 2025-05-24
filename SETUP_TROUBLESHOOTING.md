# Penguin Setup Troubleshooting Guide

## Setup Wizard Not Running

If the setup wizard doesn't run automatically on fresh installations, here are the most common causes and solutions:

### 1. Missing Dependencies

**Problem**: The setup wizard requires additional packages that aren't installed by default.

**Solution**: Install the required dependencies:
```bash
pip install questionary httpx
```

Or install Penguin with setup extras:
```bash
pip install penguin[setup]
```

**Required packages for setup wizard**:
- `questionary` - Interactive prompts
- `httpx` - API requests for model fetching
- `PyYAML` - Configuration file handling
- `rich` - Enhanced terminal output

### 2. Import Errors

**Problem**: Missing dependencies cause import failures that prevent the CLI from loading.

**Solution**: Use the debug command to identify missing packages:
```bash
penguin config debug
```

This will show you:
- Which dependencies are missing
- Where config files are expected
- Current configuration status

### 3. Config Path Issues

**Problem**: The setup wizard and main app look for config files in different locations.

**Solution**: The config is now loaded from these locations in priority order:
1. `PENGUIN_CONFIG_PATH` environment variable (if set)
2. User config directory:
   - Linux/macOS: `~/.config/penguin/config.yml`
   - Windows: `%APPDATA%/penguin/config.yml`
3. Development config (if running from source)
4. Package default config (fallback)

### 4. Manual Setup

**Problem**: If the automatic setup fails, you can configure manually.

**Solution**: Create a config file manually:

1. Create the config directory:
   ```bash
   # Linux/macOS
   mkdir -p ~/.config/penguin
   
   # Windows (PowerShell)
   New-Item -Type Directory -Path "$env:APPDATA\penguin" -Force
   ```

2. Create `config.yml`:
   ```yaml
   workspace:
     path: ~/penguin_workspace
     create_dirs:
       - conversations
       - memory_db
       - logs
       - projects
       - context

   model:
     default: anthropic/claude-3-5-sonnet-20240620
     provider: openrouter
     client_preference: openrouter
     streaming_enabled: true
     temperature: 0.7
     max_tokens: 8000

   api:
     base_url: null

   tools:
     enabled: true
     allow_web_access: true
     allow_file_operations: true
     allow_code_execution: true

   diagnostics:
     enabled: false
     verbose_logging: false
   ```

3. Set your API key as an environment variable:
   ```bash
   export OPENROUTER_API_KEY="your-api-key-here"
   # Or for Anthropic direct:
   # export ANTHROPIC_API_KEY="your-api-key-here"
   ```

## Debugging Commands

### Check Configuration Status
```bash
penguin config debug
```

This command shows:
- Setup wizard availability
- Missing dependencies
- Config file locations
- First run detection status
- Environment variables

### Manual Setup
```bash
penguin config setup
```

Force run the setup wizard (requires dependencies to be installed).

### Check Configuration
```bash
penguin config check
```

Verify if your current configuration is complete and valid.

### Edit Configuration
```bash
penguin config edit
```

Open the config file in your default editor.

## Environment Variables

You can override default behavior with these environment variables:

- `PENGUIN_CONFIG_PATH`: Override config file location
- `PENGUIN_WORKSPACE`: Override workspace directory
- `PENGUIN_ROOT`: Override project root (for development)
- `XDG_CONFIG_HOME`: Override config directory on Linux/macOS
- `APPDATA`: Override config directory on Windows

## API Keys

Penguin supports multiple AI providers. **Important**: Currently, most models are accessed through OpenRouter for unified API management.

### OpenRouter (Recommended)
OpenRouter provides unified access to models from multiple providers. When you select models like:
- `google/gemini-2-5-pro-preview`
- `openai/gpt-4o`
- `anthropic/claude-3-5-sonnet-20240620`
- `mistral/devstral`

These will be routed through OpenRouter, so you need an **OpenRouter API key**:
```bash
export OPENROUTER_API_KEY="your-openrouter-api-key"
```

Get your OpenRouter API key at: https://openrouter.ai/keys

### Direct Provider Access
For direct access to providers (not currently the default setup), you can set:

- **Anthropic**: `ANTHROPIC_API_KEY`
- **OpenAI**: `OPENAI_API_KEY`
- **Google**: `GOOGLE_API_KEY` or `GEMINI_API_KEY`
- **Mistral**: `MISTRAL_API_KEY`
- **DeepSeek**: `DEEPSEEK_API_KEY`

### Model Selection Behavior
When you select a model in the setup wizard:
1. **If the model was fetched from OpenRouter's catalog**: It will automatically use OpenRouter, regardless of the provider prefix
2. **If OpenRouter API wasn't available**: Falls back to a hardcoded list of known OpenRouter providers (`openai`, `anthropic`, `google`, `mistral`)
3. **For models not in OpenRouter**: Uses the provider directly (e.g., `ollama/llama3` → Ollama)
4. **For models without provider prefixes**: Uses the provider directly (e.g., `claude-3-sonnet` → Anthropic)

This means models like:
- `meta-llama/llama-3-70b-instruct` → **OpenRouter** ✓
- `deepseek/deepseek-chat` → **OpenRouter** ✓  
- `cohere/command-r-plus` → **OpenRouter** ✓
- `perplexity/llama-3.1-sonar-large-128k-online` → **OpenRouter** ✓

All correctly route through OpenRouter when they're available in OpenRouter's catalog.

You can test the routing logic with:
```bash
penguin config test-routing
```

**Note**: If you see the setup asking for a provider-specific API key (like Google or Anthropic) when you selected a model that should use OpenRouter, this indicates the improved routing logic wasn't applied.

## Getting Help

If you're still having issues:

1. Run `penguin config debug` and share the output
2. Check the logs in your workspace directory
3. Try manual configuration as described above
4. Open an issue on the Penguin GitHub repository with:
   - Your operating system
   - Python version
   - Installation method (pip, source, etc.)
   - Output from `penguin config debug`
   - Any error messages 