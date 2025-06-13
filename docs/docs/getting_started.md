---
sidebar_position: 2
---

# Getting Started (v0.1.x)

Welcome! This short guide will get you up and running with the current Penguin CLI and Python library.  A richer web UI and advanced project features are on the roadmap – see the [future considerations](../advanced/future_considerations.md).

---

## 1. Install
```bash
pip install penguin-ai            # CLI + Python API
```
Optional extras:
* `pip install "penguin-ai[web]"` – adds FastAPI server (`penguin-web`) **without** graphical UI yet.

This gives you:
- Complete CLI interface (`penguin` command)
- Python API for programmatic use
- SQLite-backed project management
- All core tools and memory features

## 2. Verify
```bash
penguin --version     # prints version string
penguin --help        # shows CLI options
```

---

## 3. First steps

### Interactive chat
```bash
penguin               # opens REPL-style chat
```

### One-shot prompt
```bash
echo "Explain asyncio" | penguin -p -
```

### Simple project & task (CLI)
```bash
penguin project create "Demo" -d "Example project"
PROJECT_ID=$(penguin project list --json | jq -r '.[0].ID')

penguin project task create "$PROJECT_ID" "Initial research"
```

### REST API server (optional)
```bash
pip install "penguin-ai[web]"
penguin-web   # Swagger UI at http://localhost:8000/docs
```

### Python API
```python
from penguin.agent import PenguinAgent

agent = PenguinAgent()
print(agent.chat("Hello!"))
```

---

## 4. Configuration basics
Create a `.env` file or set environment variables:
```bash
OPENAI_API_KEY=your_key_here        # or ANTHROPIC_API_KEY, OPENROUTER_API_KEY
DEFAULT_MODEL=gpt-4
```

## Next Steps

### Essential Guides
- [CLI Commands Reference](usage/cli_commands.md) - Complete command documentation
- [Project Management](usage/project_management.md) - Working with projects and tasks
- [Web Interface Guide](usage/web_interface.md) - Using the web UI effectively

### Advanced Topics
- [Configuration Options](configuration.md) - Detailed configuration reference
- [Custom Tools](advanced/custom_tools.md) - Extending Penguin with custom functionality
- [API Reference](api_reference/python_api_reference.md) - Complete Python API documentation

### Troubleshooting

**Common Issues:**

1. **Command not found**: Ensure you installed with the default option, not minimal
2. **Web interface not starting**: Install with `pip install penguin-ai[web]`
3. **API errors**: Check your `.env` file has valid API keys
4. **Permission errors**: Use virtual environments to avoid system-wide installation conflicts

For more help, see our [GitHub Issues](https://github.com/Maximooch/penguin/issues) or [Discord community](#).






