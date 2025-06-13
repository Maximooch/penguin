---
sidebar_position: 3
---

# Configuring Penguin AI Assistant

Penguin AI Assistant v0.2.0 can be configured through environment variables and YAML configuration files. This guide explains all available options for core functionality, project management, web interface, and advanced features.

Simpliest way is to just do `penguin config setup`

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
  
# Project Management System
project:
  storage:
    type: sqlite
    database_path: "${paths.workspace}/projects.db"
    backup_enabled: true
    backup_interval: 3600  # seconds
  defaults:
    workspace: ./projects
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