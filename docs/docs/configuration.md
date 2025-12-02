---
sidebar_position: 3
---

# Configuring Penguin AI Assistant

Penguin AI Assistant v0.2.0 can be configured through environment variables and YAML configuration files. This guide explains all available options for core functionality, project management, web interface, and advanced features.

Simpliest way is to just do `penguin config setup`

## Configuration Architecture

Penguin uses a two-tier configuration system:

1. **Startup Configuration** (Immutable): Loaded from environment variables and YAML files at startup
2. **Runtime Configuration** (Mutable): Can be changed dynamically during operation without restart

### Runtime Configuration

The `RuntimeConfig` system allows you to change critical settings while the server is running:

- **Project Root**: The directory where your code/project lives (typically a git repository)
- **Workspace Root**: The Penguin workspace directory (for conversations, notes, memory)
- **Execution Mode**: Where file operations target (`project` or `workspace`)

**Key Features:**
- ✅ Changes take effect immediately without restart
- ✅ Observer pattern ensures all components stay synchronized
- ✅ Validated to prevent invalid configurations
- ✅ Accessible via CLI commands or Web API

**Example: Dynamic Configuration via CLI**
```bash
# Change project root at runtime
/config runtime set project_root /path/to/new/project

# Switch execution mode
/config runtime set execution_mode workspace

# View current runtime config
/config runtime show
```

**Example: Dynamic Configuration via Web API**
```bash
# Get current configuration
curl http://localhost:8000/api/v1/system/config

# Change project root
curl -X POST http://localhost:8000/api/v1/system/config/project-root \
  -H "Content-Type: application/json" \
  -d '{"path": "/Users/you/new-project"}'

# Switch execution mode
curl -X POST http://localhost:8000/api/v1/system/config/execution-mode \
  -H "Content-Type: application/json" \
  -d '{"path": "project"}'
```

See [Runtime Configuration API](api_reference/api_server.md#runtime-configuration-management) for full API documentation.

## Configuration Methods

### 1. Environment Variables

Create a `.env` file in your working directory or project root:

```bash
# Language Model Providers (at least one required)
OPENAI_API_KEY=your_openai_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
GOOGLE_API_KEY=your_google_key_here

# Default Model Configuration
DEFAULT_MODEL=gpt-4
DEFAULT_PROVIDER=openai
TEMPERATURE=0.7

# Runtime Configuration (can be changed via API while running)
PENGUIN_PROJECT_ROOT=/path/to/your/project    # Initial project root
PENGUIN_WORKSPACE=/path/to/workspace          # Initial workspace root
PENGUIN_WRITE_ROOT=project                     # Initial execution mode (project|workspace)

# Task Management
TASK_COMPLETION_PHRASE=TASK_COMPLETED

# Web Interface (if using penguin-ai[web])
WEB_HOST=localhost
WEB_PORT=8000
WEB_DEBUG=false

# Project Management
PROJECT_AUTO_CHECKPOINT=true
PROJECT_BACKUP_INTERVAL=3600

# Memory System
MEMORY_PROVIDER=sqlite
MEMORY_STORAGE_PATH=./memory
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

### 2. YAML Configuration File

Create a `config.yml` file for advanced configuration:

```yaml
# Model Configuration
model:
  default: gpt-4
  provider: openai
  temperature: 0.7
  max_tokens: 4000
  timeout: 30

# Provider-specific settings
providers:
  openai:
    base_url: https://api.openai.com/v1
    api_version: v1
  anthropic:
    base_url: https://api.anthropic.com
    api_version: "2023-06-01"

# Project and Workspace Configuration
project:
  # Runtime configuration
  root_strategy: git-root  # 'git-root' (default) or 'cwd'
  additional_directories:  # Additional allowed directories for security
    - /path/to/extra/dir
  
  # Project management storage
  storage:
    type: sqlite
    database_path: "${paths.workspace}/projects.db"
    backup_enabled: true
    backup_interval: 3600  # seconds
  defaults:
    workspace: ./projects
    write_root: workspace  # Default execution mode: 'project' or 'workspace'
    auto_checkpoint: true
    max_iterations: 10
  constraints:
    max_projects: 100
    max_tasks_per_project: 500
    max_task_depth: 5

# Memory System Configuration
memory:
  provider: sqlite  # auto, sqlite, file, faiss, lance, chroma
  storage_path: "${paths.memory_db}"
  embedding_model: sentence-transformers/all-MiniLM-L6-v2
  max_memories: 10000
  similarity_threshold: 0.7
  
  providers:
    sqlite:
      database_file: penguin_memory.db
      enable_fts: true
      chunk_size: 512
    
    file:
      storage_dir: file_memory
      enable_embeddings: true
      max_file_size: 10485760  # 10MB
    
    chroma:
      persist_directory: ./chroma_db
      collection_name: penguin_memories
    
    lance:
      uri: ./memory.lance
      table_name: memories

# Web Interface (requires penguin-ai[web])
web:
  host: localhost
  port: 8000
  debug: false
  cors_origins:
    - http://localhost:3000
    - http://localhost:8080
  
  # Authentication (future feature)
  auth:
    enabled: false
    provider: local
    
  # WebSocket configuration
  websocket:
    heartbeat_interval: 30
    max_connections: 100
    
  # Static file serving
  static:
    enabled: true
    directory: ./static
    max_file_size: 52428800  # 50MB

# CLI Configuration
cli:
  interactive_mode: true
  auto_save: true
  history_size: 1000
  color_output: true
  
  # Command aliases
  aliases:
    p: project
    t: task
    c: chat

# Tool System
tools:
  enabled_tools:
    - file_operations
    - web_search
    - code_execution
    - image_generation
  
  file_operations:
    max_file_size: 10485760  # 10MB
    allowed_extensions: [".py", ".js", ".html", ".css", ".md", ".txt"]
    
  web_search:
    provider: duckduckgo
    max_results: 10
    
  code_execution:
    timeout: 30
    max_memory: 512  # MB
    
# Logging and Diagnostics
logging:
  level: INFO
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: penguin.log
  max_size: 10485760  # 10MB
  backup_count: 5

# Performance and Resource Management
performance:
  max_concurrent_tasks: 5
  request_timeout: 60
  retry_attempts: 3
  cache_size: 1000
  
  # Rate limiting
  rate_limits:
    requests_per_minute: 60
    tokens_per_hour: 100000

# Paths (auto-configured but can be overridden)
paths:
  workspace: ./workspace
  memory_db: ./memory
  logs: ./logs
  cache: ./cache
  temp: ./temp
```

## Output Formatting

Penguin’s assistant reply style is configurable and separate from the CLI’s program output format. Use this to choose how the assistant structures its messages in the TUI and interactive sessions.

### YAML (project or user config)

```yaml
output:
  # One of: steps_final (default) | plain | json_guided
  prompt_style: steps_final
```

Styles:
- steps_final: Keeps the “Plan / Steps” collapsible details block and a clear “Final” section.
- plain: Concise, well-structured answers without a collapsible steps block.
- json_guided: Assistant includes a concise JSON summary for structure (e.g., fields like type, answer, next_steps), and places larger code snippets in fenced code blocks.

Note: This controls the assistant’s reply style. It does not change the CLI non-interactive output, which is controlled by `--output-format` (see below).

### TUI Commands

- `/output style get` — show the current style
- `/output style set steps_final|plain|json_guided` — change the style at runtime

To persist as default:

```text
/config set output.prompt_style "plain"          # project-local
/config --global set output.prompt_style "plain" # user config
```

### CLI Non-Interactive vs. Reply Style

In non-interactive mode (`-p/--prompt`), you can select the program output format:

```bash
penguin -p "…" --output-format text|json|stream-json
```

- `--output-format` affects how the CLI prints its final response object (useful for scripting).
- `output.prompt_style` affects how the assistant structures its messages (Steps + Final, plain, JSON-guided) during interactive sessions or when rendering assistant content.

## Model Provider Configuration

### OpenAI
```yaml
providers:
  openai:
    api_key: ${OPENAI_API_KEY}
    base_url: https://api.openai.com/v1
    models:
      - gpt-4
      - gpt-3.5-turbo
      - gpt-4-turbo-preview
```

### Anthropic
```yaml
providers:
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}
    base_url: https://api.anthropic.com
    api_version: "2023-06-01"
    models:
      - claude-3-opus-20240229
      - claude-3-sonnet-20240229
```

### Local Models (Ollama)
```yaml
providers:
  ollama:
    base_url: http://localhost:11434
    models:
      - llama2
      - codellama
      - mistral
```

For a complete list of supported providers, see the [LiteLLM documentation](https://docs.litellm.ai/docs/providers).

## Project Management Configuration

### Database Settings
```yaml
project:
  storage:
    type: sqlite
    database_path: ./projects.db
    
    # Connection pool settings
    max_connections: 10
    timeout: 30
    
    # Performance tuning
    journal_mode: WAL
    synchronous: NORMAL
    cache_size: 10000
```

### Task Execution Settings
```yaml
project:
  execution:
    max_iterations: 10
    timeout_minutes: 60
    auto_checkpoint: true
    
    # Resource constraints
    max_memory_mb: 1024
    max_files: 100
    max_tokens: 100000
```

## Memory System Configuration

### SQLite Provider (Recommended)
```yaml
memory:
  provider: sqlite
  providers:
    sqlite:
      database_file: penguin_memory.db
      enable_fts: true      # Full-text search
      enable_vector: true   # Vector similarity search
      chunk_size: 512       # Text chunk size for embeddings
      overlap: 50           # Overlap between chunks
```

### Vector Database Providers
```yaml
memory:
  provider: chroma  # or lance, faiss
  providers:
    chroma:
      persist_directory: ./chroma_db
      collection_name: penguin_memories
      embedding_function: sentence-transformers/all-MiniLM-L6-v2
```

## Web Interface Configuration

### Basic Server Settings
```yaml
web:
  host: 0.0.0.0        # Bind to all interfaces
  port: 8000
  workers: 1           # Number of worker processes
  reload: false        # Auto-reload on file changes (development only)
```

### Security Settings
```yaml
web:
  security:
    cors_origins:
      - http://localhost:3000
      - https://myapp.com
    cors_methods: ["GET", "POST", "PUT", "DELETE"]
    cors_headers: ["*"]
    
    # Rate limiting
    rate_limit:
      enabled: true
      requests_per_minute: 100
      
    # Request size limits
    max_request_size: 10485760  # 10MB
```

## Security Configuration

Penguin includes a comprehensive permission system that controls what operations the AI agent can perform. See [Security & Permissions](advanced/security.md) for full documentation.

### Security Modes

```yaml
security:
  # Security mode: read_only, workspace, or full
  mode: workspace
  
  # Enable/disable permission checks (set to false or use PENGUIN_YOLO=true to disable)
  enabled: true
  
  # Additional allowed paths beyond workspace/project
  allowed_paths:
    - /path/to/shared/resources
  
  # Explicitly denied paths (always blocked)
  denied_paths:
    - ~/.ssh
    - ~/.aws
    - /etc
  
  # Operations requiring user approval before execution
  require_approval:
    - filesystem.delete
    - git.push
    - git.force
```

**Mode Descriptions:**
- `read_only`: Agent can only read files, no modifications allowed
- `workspace`: Operations restricted to workspace and project directories (default)
- `full`: Minimal restrictions, use with caution in trusted environments

### Audit Logging

Configure permission audit logging for debugging and compliance:

```yaml
security:
  audit:
    enabled: true
    log_file: ".penguin/permission_audit.log"
    
    # Per-category verbosity: off, deny_only, ask_and_deny, all
    categories:
      filesystem: all
      process: ask_and_deny
      network: deny_only
      git: ask_and_deny
      memory: off
    
    # Maximum entries to keep in memory for API queries
    max_memory_entries: 1000
    
    # Include full context in logs (may contain sensitive data)
    include_context: false
```

### Multi-Agent Permissions

Define per-agent permission restrictions:

```yaml
agents:
  code-reviewer:
    persona: "Code Review Expert"
    permissions:
      mode: read_only
      operations:
        - filesystem.read
        - memory.read
      allowed_paths:
        - ./src
        - ./tests
```

## Advanced Configuration

### Custom Tool Configuration
```yaml
tools:
  custom_tools_path: ./custom_tools
  
  # Tool-specific settings
  file_operations:
    sandbox_mode: true
    allowed_paths:
      - ./workspace
      - ./projects
    
  web_search:
    cache_results: true
    cache_ttl: 3600
```

### Performance Tuning
```yaml
performance:
  # Async settings
  max_concurrent_requests: 10
  connection_pool_size: 20
  
  # Caching
  cache:
    provider: memory  # memory, redis, file
    ttl: 3600
    max_size: 1000
    
  # Background tasks
  background_tasks:
    enabled: true
    max_workers: 5
```

## Configuration Validation

Penguin validates your configuration on startup. Common validation errors:

- **Missing API keys**: Ensure at least one model provider is configured
- **Invalid paths**: Check that specified directories exist and are writable
- **Resource limits**: Ensure memory and timeout values are reasonable
- **Network settings**: Verify ports are available and addresses are valid

## Environment-Specific Configurations

### Development
```yaml
# config.dev.yml
logging:
  level: DEBUG
web:
  debug: true
  reload: true
performance:
  cache_size: 100
```

### Production
```yaml
# config.prod.yml
logging:
  level: WARNING
web:
  debug: false
  workers: 4
security:
  rate_limit:
    enabled: true
performance:
  cache_size: 5000
```

Load environment-specific config:
```bash
penguin --config config.prod.yml
```

## Configuration Troubleshooting

**Common Issues:**

1. **Configuration not loading**: Check YAML syntax and file permissions
2. **API connection errors**: Verify API keys and network connectivity
3. **Database errors**: Ensure SQLite database is writable
4. **Memory issues**: Adjust cache sizes and memory limits
5. **Web interface not accessible**: Check firewall settings and port availability

For detailed debugging, enable debug logging:
```yaml
logging:
  level: DEBUG
```

# todo: add configuration for ollama!
