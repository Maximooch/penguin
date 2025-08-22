---
sidebar_position: 2
---

# Getting Started (v0.3.1)

Welcome! This guide will get you up and running with Penguin v0.3.1, featuring advanced conversation management, real-time streaming, and comprehensive checkpoint capabilities.

---

## 1. Install

### Core Installation
```bash
pip install penguin-ai            # CLI + Python API
```

### Feature-Rich Installation
```bash
pip install "penguin-ai[full]"   # All features including web interface
```

### Installation Options
* `pip install "penguin-ai[web]"` – adds FastAPI server with web interface
* `pip install "penguin-ai[minimal]"` – lightweight library-only installation
* `pip install "penguin-ai[dev]"` – development dependencies for contributors

### What's Included

**Core Features:**
- Enhanced CLI interface with TUI (`penguin` command)
- Python API for programmatic use
- Advanced conversation management with checkpoints
- Real-time streaming with event-driven architecture
- SQLite-backed project and task management
- Enhanced token management with category-based budgets
- Runtime model switching capabilities

**Optional Features:**
- Web interface with REST API (`penguin-web`)
- Performance monitoring and diagnostics
- Comprehensive error handling and recovery
- Fast startup optimization

## 2. Verify Installation
```bash
penguin --version     # prints version string (v0.3.1)
penguin --help        # shows enhanced CLI options
penguin --diagnostics # shows system information and performance stats
```

### Check Configuration
```bash
penguin config show   # displays current configuration
penguin model list    # lists available models
```

---

## 3. First Steps

### Enhanced Interactive Chat
```bash
penguin               # opens advanced TUI with real-time streaming
penguin --no-tui      # CLI mode without graphical interface
```

### Streaming and Checkpoint Features
```bash
penguin -p "Help me debug this Python function"  # streaming response
penguin --checkpoint "Before major changes"      # create checkpoint
penguin --model claude-3-5-sonnet              # specify model
```

### Model Management
```bash
# Switch models dynamically
penguin model switch openai/gpt-5

# Get model information
penguin model info
```

### Advanced Project & Task Management
```bash
# Create project with enhanced features
penguin project create "AI Assistant Demo" -d "Demonstrating new features"

# List projects with metadata
penguin project list --detailed

# Create task with automatic checkpointing
penguin task create "Implement streaming chat" --project "demo-project"

# View task progress
penguin task status
```

### Enhanced Web Interface (optional)
```bash
pip install "penguin-ai[web]"
penguin-web   # Enhanced web interface at http://localhost:8000
# API docs at http://localhost:8000/api/docs
```

### Programmatic API with Streaming
```python
from penguin.web.app import PenguinAPI

# Initialize with enhanced features
api = PenguinAPI()

# Chat with streaming and checkpointing
response = await api.chat(
    "Help me refactor this code",
    streaming=True,
    conversation_id="my-session"
)

# Create checkpoints programmatically
checkpoint_id = await api.core.create_checkpoint(
    name="Before refactoring",
    description="Saving state before major changes"
)
```

### FastAPI Integration
```python
from fastapi import FastAPI
from penguin.web.app import create_app

# Embed Penguin in your FastAPI application
app = create_app()
# Penguin API is now available at /api/v1/
```

---

## 4. Enhanced Configuration

### Environment Variables
```bash
# API Keys
ANTHROPIC_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here

# Model Configuration
PENGUIN_DEFAULT_MODEL=openai/gpt-5
PENGUIN_CLIENT_PREFERENCE=native  # native, litellm, or openrouter
PENGUIN_STREAMING_ENABLED=true

# Performance Settings
PENGUIN_FAST_STARTUP=true
PENGUIN_MAX_TOKENS=400000
```

### Advanced Configuration File
Create `config.yml` for comprehensive settings:
```yaml
model:
  default: anthropic/claude-3-5-sonnet
  client_preference: openrouter
  streaming_enabled: true
  max_tokens: 200000

performance:
  fast_startup: true
  diagnostics_enabled: true

checkpoints:
  enabled: true
  frequency: 1
  retention:
    keep_all_hours: 24
    max_age_days: 30

memory:
  indexing_enabled: true
  providers:
    - chroma
    - lance
```

## Next Steps

### Essential Guides
- [CLI Commands Reference](usage/cli_commands.md) - Complete command documentation with new checkpoint features
- [Project Management](usage/project_management.md) - Enhanced project and task management
- [Web Interface Guide](usage/web_interface.md) - Using the enhanced web UI with streaming
- [Configuration Options](configuration.md) - Detailed configuration with model switching

### New v0.3.1 Features
- [Checkpoint Management](usage/checkpointing.md) - Conversation state management and branching
- [Streaming and Events](usage/streaming.md) - Real-time streaming and event-driven architecture
- [Model Management](usage/model_management.md) - Runtime model switching and configuration
- [Performance Optimization](usage/performance.md) - Fast startup and diagnostics

### Advanced Topics
- [System Architecture](system/) - Deep dive into conversation management and token budgeting
- [Custom Tools](advanced/custom_tools.md) - Extending Penguin with custom functionality
- [API Reference](api_reference/) - Complete Python API documentation with new methods
- [Event System](advanced/events.md) - Working with the event-driven architecture

### Troubleshooting

**Common Issues:**

1. **Command not found**: Ensure you installed with `pip install penguin-ai`, not the minimal option
2. **Web interface not starting**: Install with `pip install "penguin-ai[web]"` and check port 8000
3. **API errors**: Verify API keys and check `penguin --diagnostics` for configuration issues
4. **Streaming not working**: Ensure your model supports streaming and check client preference settings
5. **Checkpoint errors**: Check disk space and file permissions for the workspace directory
6. **Performance issues**: Try `fast_startup=true` in config or use `penguin --diagnostics` for profiling

### Getting Help

- **GitHub Issues**: [Report bugs and feature requests](https://github.com/Maximooch/penguin/issues)
- **Documentation**: Check the [System Documentation](system/) for advanced configuration
- **Performance**: Use `penguin --diagnostics` for system information and performance metrics
- **Configuration**: Run `penguin config show` to verify your current settings

**Quick Diagnostic Commands:**
```bash
penguin --version              # Check version
penguin --diagnostics          # System information and performance
penguin config show            # Current configuration
penguin model list             # Available models
penguin model info             # Current model details
```






